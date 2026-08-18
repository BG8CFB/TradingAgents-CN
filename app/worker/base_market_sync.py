"""跨市场域同步抽象基类 — 统一 CN/HK/US 三个市场共有的"priority fallback + bulk upsert + sync_event + checkpoint"流程。

历史背景：
    1. CN 域（``app/worker/cn/domain_sync/base_domain_sync.py``）使用 FallbackRouter
       + 单 symbol 同步，复杂度高（依赖 router.fetch 内部的熔断/重试）。
    2. HK/US 域（``app/worker/hk/domain_sync/_common.py`` 和
       ``app/worker/us/domain_sync/_common.py``）使用简单 priority 循环 + bulk_write
       upsert，逻辑相同但代码各自实现一遍。

本抽象类针对 (2) 提供统一基类，子类只需声明 market + provider/adapter 工厂即可。
CN 域的 FallbackRouter 路径不强制收敛，保持现有 BaseDomainSync 不变。
"""

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

from pymongo import UpdateOne

from app.core.database import get_mongo_db
from app.data.storage.mongo.collections import get_collection_name
from app.utils.timezone import now_utc

logger = logging.getLogger(__name__)


class BaseMarketDomainSync(ABC):
    """跨市场（CN/HK/US）域级同步基类。

    子类责任：
        - 声明 ``market``（"CN" / "HK" / "US"）和 ``domain``
        - 实现 ``get_provider(source_name)`` 和 ``get_adapter(source_name)`` 工厂

    基类负责：
        - 通过 CapabilityRegistry + PriorityConfig 解析数据源优先级
        - 优先级 fallback：第一个成功源返回后停止
        - bulk_write upsert（filter_fields 由调用方传入）
        - sync_event 写入（成功/失败均记录）
    """

    market: str = ""
    domain: str = ""
    description: str = ""

    @abstractmethod
    def get_provider(self, source_name: str) -> Any:
        """根据 source_name 返回对应 Provider 实例（不存在则返回 None）。"""

    @abstractmethod
    def get_adapter(self, source_name: str) -> Any:
        """根据 source_name 返回对应 Adapter 实例（不存在则返回 None）。"""

    def get_default_filter_fields(self) -> List[str]:
        """默认 upsert filter 字段（子类可覆盖）。"""
        return ["symbol"]

    async def get_sources(self) -> List[str]:
        """通过 CapabilityRegistry + PriorityConfig 解析优先级。"""
        from app.data.core.registry.capability import CapabilityRegistry
        from app.data.core.registry.priority import PriorityConfig

        registry = CapabilityRegistry()
        priority = PriorityConfig()
        return registry.get_ordered_sources(
            self.market, self.domain,
            user_priority=await priority.get_priority(self.market, self.domain),
        )

    async def sync(
        self,
        provider_method: str,
        adapter_method: str,
        provider_kwargs_fn: Optional[Callable[[], Dict]] = None,
        filter_fields: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """执行单域同步（按优先级 fallback）。

        Args:
            provider_method: Provider 上的方法名
            adapter_method: Adapter 上的方法名
            provider_kwargs_fn: 可选函数，返回传递给 provider 方法的 kwargs
            filter_fields: MongoDB upsert filter 字段；为空则用 get_default_filter_fields()

        Note:
            **失败也写 sync_event**（``event_type=SYNC_FAILED``）是设计意图 —
            保证 ``sync_events`` 集合记录每一次同步尝试，便于监控失败率。
            若曾依赖"无 sync_event 即失败"的旧逻辑（HK/US 历史 _common 实现），
            迁移后需相应调整监控告警阈值，避免 SYNC_FAILED 计数突增。
        """
        start = time.time()
        sources = await self.get_sources()
        fields = filter_fields or self.get_default_filter_fields()

        for source_name in sources:
            provider = self.get_provider(source_name)
            adapter = self.get_adapter(source_name)
            if not provider or not adapter:
                continue

            try:
                kwargs = provider_kwargs_fn() if provider_kwargs_fn else {}
                raw = await getattr(provider, provider_method)(**kwargs)
                if raw is None:
                    continue
                if hasattr(raw, "empty") and raw.empty:
                    continue

                records = getattr(adapter, adapter_method)(raw)
                if not records:
                    continue

                docs = [r.to_db_doc() for r in records]
                db = get_mongo_db()
                collection = db[get_collection_name(self.domain, self.market)]

                ops = []
                for d in docs:
                    filt = {f: d[f] for f in fields if f in d and d[f] is not None}
                    if filt:
                        ops.append(UpdateOne(filt, {"$set": d}, upsert=True))

                if ops:
                    await collection.bulk_write(ops, ordered=False)

                elapsed = int((time.time() - start) * 1000)
                logger.info(
                    f"{self.market} {self.domain} 同步完成: "
                    f"{len(ops)} 条, 源={source_name}, 耗时={elapsed}ms"
                )

                await self._write_sync_event(
                    success=True, source=source_name, record_count=len(ops),
                    duration_ms=elapsed,
                )
                await self._write_checkpoint(
                    success=True, source=source_name, record_count=len(ops),
                    duration_ms=elapsed,
                )

                return {
                    "domain": self.domain, "success": True, "source": source_name,
                    "records": len(ops), "duration_ms": elapsed,
                }
            except Exception as e:
                logger.warning(
                    f"{self.market} {self.domain} 源 {source_name} 失败: {e}"
                )
                continue

        elapsed = int((time.time() - start) * 1000)
        await self._write_sync_event(
            success=False, source="", record_count=0,
            duration_ms=elapsed, error="所有数据源失败",
        )
        await self._write_checkpoint(
            success=False, source="", record_count=0,
            duration_ms=elapsed,
        )
        return {
            "domain": self.domain, "success": False,
            "error": "所有数据源失败", "duration_ms": elapsed,
        }

    async def _write_sync_event(
        self, *, success: bool, source: str, record_count: int,
        duration_ms: int, error: Optional[str] = None,
    ) -> None:
        """写入 sync_events 集合（失败不阻断主流程）。"""
        try:
            db = get_mongo_db()
            collection_name = get_collection_name("sync_events", self.market)
            collection = db[collection_name]
            event = {
                "event_type": "SYNC_SUCCESS" if success else "SYNC_FAILED",
                "domain": self.domain,
                "source": source,
                "market": self.market,
                "symbol": None,
                "record_count": record_count,
                "duration_ms": duration_ms,
                "error_message": error,
                "data_source": "base_market_sync",
                "updated_at": now_utc().isoformat(),
            }
            await collection.insert_one(event)
        except Exception as e:
            logger.debug(f"写入 sync_event 失败: {e}")

    async def _write_checkpoint(
        self, *, success: bool, source: str, record_count: int,
        duration_ms: int,
    ) -> None:
        """写入 sync_checkpoints 集合（失败不阻断主流程）。

        成功和失败均写 checkpoint，让 Dashboard 能反映最新同步状态。
        """
        try:
            from app.data.storage.mongo.repositories.metadata_repo import MetadataRepo

            await MetadataRepo().update_checkpoint(
                market=self.market,
                domain=self.domain,
                source=source,
                last_sync_date=now_utc().date().isoformat(),
                record_count=record_count,
                status="success" if success else "failed",
                duration_ms=duration_ms,
                scope="market",
                trigger="scheduled",
            )
        except Exception as e:
            logger.debug(f"写入 checkpoint 失败: {e}")
