"""Tushare CN 连接管理 — 委托共享 TushareClient。

原有实现自带一份 DB-token 读取（system_configs.data_source_configs），
与 app/utils/ds_key_utils.get_datasource_api_key 近似重复且行为略不同；
现已统一走 TushareClient → get_datasource_api_key（DB 优先 + ENV 回退）。
本模块保留 TushareConnection 外观与单例接口，供 CN api/ 子模块与
Provider 兼容调用（conn.api / conn.is_available() / conn.connect()）。
"""

import logging
import threading
from typing import Optional

from app.data.sources.tushare_common.client import TushareClient

logger = logging.getLogger(__name__)


class TushareConnection:
    """Tushare API 连接管理器（外观：包装共享 TushareClient）"""

    def __init__(self, client: Optional[TushareClient] = None):
        self._client = client or TushareClient(
            source_name="tushare",
            probe_endpoint="stock_basic",
            probe_kwargs={"list_status": "L", "limit": 1},
            min_credits=120,
        )

    # ── 外观属性：CN api/ 模块与既有调用方依赖 conn.api ────────

    @property
    def api(self):
        return self._client.api

    @property
    def connected(self) -> bool:
        return self._client.connected

    @property
    def token_source(self) -> Optional[str]:
        return self._client.token_source

    def connect_sync(self) -> bool:
        return self._client.connect_sync()

    async def connect(self) -> bool:
        """异步连接"""
        return await self._client.connect()

    def is_available(self) -> bool:
        return self._client.is_available()

    def invalidate(self) -> None:
        """作废缓存 api（允许一次性重建）。"""
        self._client.invalidate()

    def query(self, api_name: str, **kwargs):
        """通用 Tushare API 查询"""
        return self._client.query(api_name, **kwargs)


# 单例
_instance: Optional[TushareConnection] = None
_instance_lock = threading.Lock()


def get_tushare_api() -> TushareConnection:
    """获取 Tushare 连接单例"""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = TushareConnection()
                _instance.connect_sync()
    return _instance
