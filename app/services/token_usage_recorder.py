# data-access-exempt: 用量统计直写 Mongo（同 usage_statistics_service 聚合层）
"""LLM Token 用量记录器

- 每次 LLM API 调用记一条到 Mongo `token_usage` 集合（per-call 粒度，
  聚合交给 usage_statistics_service 的服务端 $facet）
- fire-and-forget：record() 同步入口、全吞错，绝不阻塞/影响 LLM 调用路径
- 跨线程：分析在工作线程事件循环中执行，Mongo 异步写入经
  run_coroutine_threadsafe 调度回 FastAPI 主循环（模式同 analysis_events）
- 时间戳统一 now_utc().isoformat()（与统计查询侧一致）
- 开关：环境变量 TOKEN_USAGE_RECORDING_ENABLED（缺省 true）可即时关闭
"""
# data-access-exempt: 应用层集合（用量统计）

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from app.core.env import get_env
from app.utils.timezone import now_utc

logger = logging.getLogger("app.services.token_usage_recorder")

COLLECTION_NAME = "token_usage"


class PricingCalculator:
    """模型定价计算（config/pricing.json，缓存加载）

    缓存价可选：cache_read_price_per_1k / cache_write_price_per_1k，
    缺省回退 input_price_per_1k（未配置时成本行为与旧实现一致）。
    """

    def __init__(self, pricing_file: str = "config/pricing.json"):
        self._pricing_file = Path(pricing_file)
        self._pricing_cache: list = []
        self._loaded = False

    def _load(self) -> list:
        if self._loaded:
            return self._pricing_cache
        try:
            if self._pricing_file.exists():
                with open(self._pricing_file, "r", encoding="utf-8") as f:
                    self._pricing_cache = json.load(f)
            self._loaded = True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"加载定价配置失败: {e}")
        return self._pricing_cache

    def reload(self) -> None:
        """强制重载（pricing.json 更新后调用）"""
        self._loaded = False
        self._load()

    def calculate_cost(
        self,
        provider: str,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> tuple:
        """计算成本。Returns: (cost, currency)；无匹配定价时 (0.0, "CNY")"""
        for pricing in self._load():
            if not isinstance(pricing, dict):
                continue
            if pricing.get("provider") != provider or pricing.get("model_name") != model_name:
                continue
            inp = pricing.get("input_price_per_1k", 0)
            out = pricing.get("output_price_per_1k", 0)
            # 缓存价缺省回退输入价（兼容未配置缓存的旧 pricing.json）
            cache_read_price = pricing.get("cache_read_price_per_1k", inp)
            cache_write_price = pricing.get("cache_write_price_per_1k", inp)
            # input_tokens 含缓存部分（两家 API 语义一致），缓存部分按折扣价计
            billable_plain_input = max(0, input_tokens - cache_read_tokens - cache_creation_tokens)
            total = (
                (billable_plain_input / 1000) * inp
                + (cache_read_tokens / 1000) * cache_read_price
                + (cache_creation_tokens / 1000) * cache_write_price
                + (output_tokens / 1000) * out
            )
            return round(total, 6), pricing.get("currency", "CNY")
        return 0.0, "CNY"


class TokenUsageRecorder:
    """LLM token 用量记录器（fire-and-forget）"""

    def __init__(self):
        self._server_loop: Optional[asyncio.AbstractEventLoop] = None
        self._pricing = PricingCalculator()

    def set_server_loop(self, loop: Optional[asyncio.AbstractEventLoop]) -> None:
        """FastAPI startup 注入主事件循环；传 None 可注销（测试隔离用）"""
        self._server_loop = loop
        if loop is not None and loop.is_running():
            loop.create_task(self._ensure_indexes())

    async def _ensure_indexes(self) -> None:
        """幂等创建查询索引（timestamp 范围 / task_id 点查），避免聚合全表扫描"""
        try:
            from app.core.database import get_mongo_db

            db = get_mongo_db()
            col = db[COLLECTION_NAME]
            await col.create_index([("timestamp", 1)])
            await col.create_index([("task_id", 1)])
        except Exception as e:  # noqa: BLE001 - 索引失败不影响记录
            logger.warning(f"⚠️ [Token记录] 创建索引失败: {e}")

    def _enabled(self) -> bool:
        # 仅启动时读一次环境变量即可；此处保持每次读取以便测试/运行时切换
        return str(get_env("TOKEN_USAGE_RECORDING_ENABLED", "true")).lower() not in (
            "false",
            "0",
            "no",
        )

    def record(
        self,
        *,
        provider: str,
        model_name: str,
        usage,
        task_id: str = "",
        user_id: str = "",
        agent_key: str = "",
        phase: str = "",
        analysis_type: str = "stock_analysis",
    ) -> None:
        """记录一次 LLM 调用的 usage。同步入口，任何失败只告警不上抛。

        Args:
            usage: app.llm.core.types.Usage（含缓存字段）
        """
        if not self._enabled():
            return
        try:
            input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
            output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
            cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
            cache_creation = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)

            cost, currency = self._pricing.calculate_cost(
                provider,
                model_name,
                input_tokens,
                output_tokens,
                cache_read_tokens=cache_read,
                cache_creation_tokens=cache_creation,
            )

            doc = {
                "timestamp": now_utc().isoformat(),
                "provider": provider,
                "model_name": model_name,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read,
                "cost": cost,
                "currency": currency,
                # session_id 语义升级为 task_id（保留字段兼容旧读取端）
                "session_id": task_id or "",
                "analysis_type": analysis_type,
                "task_id": task_id,
                "user_id": user_id,
                "agent_key": agent_key,
                "phase": phase,
            }
            self._schedule_insert(doc)
        except Exception as e:  # noqa: BLE001 - 统计失败绝不影响分析
            logger.warning(f"⚠️ [Token记录] 构建记录失败（已丢弃）: {e}")

    def _schedule_insert(self, doc: dict) -> None:
        loop = self._server_loop
        try:
            if loop is not None and loop.is_running():
                fut = asyncio.run_coroutine_threadsafe(self._insert(doc), loop)
                fut.add_done_callback(
                    lambda f: (
                        logger.warning(f"⚠️ [Token记录] 写入失败: {f.exception()}")
                        if f.exception()
                        else None
                    )
                )
            else:
                # 无主循环（脚本/测试）：当前循环直接调度
                asyncio.get_running_loop().create_task(self._insert(doc))
        except RuntimeError:
            # 无运行中的事件循环（纯同步上下文）：同步客户端兜底写入
            self._insert_sync_fallback(doc)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"⚠️ [Token记录] 调度写入失败（已丢弃）: {e}")

    def _insert_sync_fallback(self, doc: dict) -> None:
        try:
            from app.core.database import get_mongo_db_sync

            db = get_mongo_db_sync()
            if db is None:
                return
            result = db[COLLECTION_NAME].insert_one(doc)
            if hasattr(result, "__await__"):
                logger.warning("⚠️ [Token记录] get_mongo_db_sync() 返回了 Motor 异步数据库，跳过同步写入")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"⚠️ [Token记录] 同步兜底写入失败（已丢弃）: {e}")

    async def _insert(self, doc: dict) -> None:
        try:
            from app.core.database import get_mongo_db

            db = get_mongo_db()
            await db[COLLECTION_NAME].insert_one(doc)
            logger.info(
                f"💾 [Token记录] {doc['provider']}/{doc['model_name']} "
                f"in={doc['input_tokens']} out={doc['output_tokens']} "
                f"cache_read={doc['cache_read_input_tokens']} cost={doc['cost']}"
            )
        except Exception as e:  # noqa: BLE001 - 落库失败不阻断分析
            logger.warning(f"⚠️ [Token记录] MongoDB 写入失败（已丢弃）: {e}")


# 全局单例
token_usage_recorder = TokenUsageRecorder()
