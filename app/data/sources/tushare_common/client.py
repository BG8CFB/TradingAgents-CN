"""Tushare 统一客户端 — Token 解析、连接建立、试探探测、错误分类。

三市场（CN/HK/US）共用一个客户端实现，差异通过构造参数注入：

- ``source_name``：决定 Token 解析链（复用 ds_key_utils._DS_ENV_MAP 既有映射，
  DB 优先、ENV 回退），如 "tushare" / "tushare_hk" / "tushare_us"
- ``probe_endpoint`` / ``probe_kwargs``：连接试探接口（stock_basic / hk_basic / us_basic）
- ``min_credits``：积分门槛（仅用于错误消息，来自 markets.yaml）

错误分类优先使用 map_tushare_code（Tushare 官方错误码），
错误码缺失时保留最小限度的消息嗅探兜底（tushare 对无效 Token 的
响应部分场景不带 code 字段）。
"""

import asyncio
import logging
import threading
from typing import Any, Dict, List, Optional

from app.data.sources.base.exceptions import (
    InsufficientCreditsError,
    TokenInvalidError,
)
from app.data.sources.base.mappers import map_tushare_code

try:
    import tushare as ts

    TUSHARE_AVAILABLE = True
except ImportError:
    TUSHARE_AVAILABLE = False
    ts = None

logger = logging.getLogger(__name__)

# 与 tushare 官方错误码映射保持一致的兜底消息关键字（仅在异常无 code 时使用）
_TOKEN_INVALID_KEYWORDS = ("token", "登录", "未登录", "权限")
_CREDITS_KEYWORDS = ("积分", "credit")


def classify_tushare_error(
    exc: Exception,
    source: str,
    domain: str,
    min_credits: int = 0,
) -> Optional[Exception]:
    """把 Tushare 异常分类为 DataSourceError 子类。

    优先按异常携带的 code 属性走 map_tushare_code；无 code 时按消息关键字
    兜底识别凭据/积分类错误（这两类对调用方语义重要：不可重试、需人工介入）。
    无法识别时返回 None（交由调用方按未知异常处理）。
    """
    error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
    mapped = map_tushare_code(error_code, source, domain, str(exc))
    if mapped is not None:
        return mapped

    msg = str(exc).lower()
    if any(kw in msg for kw in _TOKEN_INVALID_KEYWORDS):
        return TokenInvalidError(source, domain, f"Token 无效: {exc}")
    if any(kw in str(exc) for kw in _CREDITS_KEYWORDS) or "credit" in msg:
        return InsufficientCreditsError(source, domain, f"积分不足(需≥{min_credits}): {exc}", required=min_credits)
    return None


class TushareClient:
    """单市场 Tushare API 客户端（每市场一个实例）。"""

    def __init__(
        self,
        source_name: str,
        env_chain: Optional[List[str]] = None,
        probe_endpoint: str = "stock_basic",
        probe_kwargs: Optional[Dict[str, Any]] = None,
        min_credits: int = 0,
    ):
        self.source_name = source_name
        self.env_chain = env_chain
        self.probe_endpoint = probe_endpoint
        self.probe_kwargs = probe_kwargs or {}
        self.min_credits = min_credits

        self.api = None
        self.connected = False
        self.token_source: Optional[str] = None
        self._token: Optional[str] = None
        # 一次性重连支持：api 失效缓存后允许重建（最多重建一次）
        self._rebuild_count = 0
        self._lock = threading.Lock()

    # ── Token 解析 ──────────────────────────────────────────

    def resolve_token(self) -> Optional[str]:
        """解析 Token：统一走 ds_key_utils（DB 优先 + ENV 链回退）。

        env_chain 仅作显式覆盖；默认复用 ds_key_utils._DS_ENV_MAP 既有映射，
        不在此处自造环境变量链。
        """
        from app.utils.ds_key_utils import get_datasource_api_key

        token = get_datasource_api_key(self.source_name)
        if token:
            self.token_source = "ds_key_utils"
            return token
        if self.env_chain:
            from app.core.env import get_env

            for env_key in self.env_chain:
                val = get_env(env_key)
                if val and val.strip() and not val.startswith("your_"):
                    self.token_source = f"env:{env_key}"
                    return val.strip()
        return None

    # ── 连接建立 ────────────────────────────────────────────

    def connect_sync(self) -> bool:
        """同步连接：Token → set_token → pro_api → 试探探测。"""
        if not TUSHARE_AVAILABLE:
            logger.error(f"{self.source_name}: tushare 库不可用")
            return False

        token = self._token or self.resolve_token()
        if not token:
            logger.warning(f"{self.source_name}: Token 未配置，无法连接")
            return False

        try:
            ts.set_token(token)
            api = ts.pro_api()
        except Exception as e:
            logger.error(f"{self.source_name}: set_token/pro_api 失败: {e}")
            return False

        probe = getattr(api, self.probe_endpoint, None)
        if probe is None:
            logger.error(f"{self.source_name}: 试探接口不存在: {self.probe_endpoint}")
            return False

        try:
            result = probe(**self.probe_kwargs)
            if result is not None and not getattr(result, "empty", True):
                with self._lock:
                    self.api = api
                    self.connected = True
                    self._token = token
                    self._rebuild_count = 0
                logger.info(f"{self.source_name} 连接成功 (Token 来源: {self.token_source})")
                return True
            logger.warning(f"{self.source_name} 试探 {self.probe_endpoint} 返回空数据")
            return False
        except Exception as e:
            classified = classify_tushare_error(e, self.source_name, self.probe_endpoint, self.min_credits)
            if classified is not None:
                raise classified
            logger.error(f"{self.source_name} 连接失败: {e}")
            return False

    async def connect(self) -> bool:
        """异步连接。"""
        return await asyncio.to_thread(self.connect_sync)

    def is_available(self) -> bool:
        return TUSHARE_AVAILABLE and self.connected and self.api is not None

    # ── API 获取与一次性重连 ─────────────────────────────────

    def get_api(self):
        """获取缓存的 pro_api 实例；未建立时惰性尝试构建。

        失效缓存（invalidate）后允许重建一次，避免 API 实例因长连接
        过期而永久不可用。
        """
        if self.api is not None:
            return self.api
        if self._rebuild_count >= 1:
            return None
        with self._lock:
            if self.api is not None:
                return self.api
            if self._rebuild_count >= 1:
                return None
            self._rebuild_count += 1
        try:
            if self.connect_sync():
                return self.api
        except Exception as e:
            logger.debug(f"{self.source_name} 重建连接失败: {e}")
        return None

    def invalidate(self) -> None:
        """作废缓存的 api 实例（下次 get_api 时允许重建一次）。"""
        with self._lock:
            self.api = None
            self.connected = False

    # ── 通用查询（向后兼容 CN TushareConnection.query）─────────

    def query(self, api_name: str, **kwargs):
        """通用 Tushare API 查询。"""
        if not self.is_available():
            return None
        try:
            method = getattr(self.api, api_name, None)
            if method:
                return method(**kwargs)
            return self.api.query(api_name, **kwargs)
        except Exception as e:
            logger.error(f"{self.source_name} query({api_name}) 失败: {e}")
            raise
