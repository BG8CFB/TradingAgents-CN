"""跨市场域同步抽象基类 — 统一 CN/HK/US 三个市场共有的
"router 四件套 fallback + Repo upsert + sync_event + checkpoint" 流程。

历史背景：
    1. CN 域（``app/worker/cn/domain_sync/base_domain_sync.py``）使用 FallbackRouter
       + 单 symbol 同步（熔断/限流/重试/校验四件套齐备）。
    2. HK/US 域曾各自实现"priority 循环 + 裸 bulk_write"，无四件套保护，
       upsert filter 由调用方手写，绕过 Repo 主键定义 — 已收敛到本基类。

现状（2026-08 数据层标准化 Phase 3）：
    本基类的 ``sync()`` 通过 ``FallbackRouter.fetch_source()`` 复用与 CN 侧
    完全相同的熔断/限流/重试/校验语义；入库统一分发到对应 Repo
    （upsert 键来自 key_spec / index_definitions，单一事实源）。
"""

import logging
import time
from abc import ABC
from typing import Any, Callable, Dict, List, Optional

from app.core.database import get_mongo_db
from app.data.storage.mongo.collections import get_collection_name
from app.utils.timezone import now_utc

logger = logging.getLogger(__name__)

# 域 → Repo 模块/类名映射（懒加载，避免 import 环）
# 新增域同步时若表中无对应 Repo，sync() 会显式报错而非静默直写库
_REPO_TABLE: Dict[str, tuple] = {
    "basic_info": ("basic_info_repo", "BasicInfoRepo"),
    "trade_calendar": ("trade_calendar_repo", "TradeCalendarRepo"),
    "daily_quotes": ("daily_quotes_repo", "DailyQuotesRepo"),
    "daily_indicators": ("daily_indicators_repo", "DailyIndicatorsRepo"),
    "financial_data": ("financial_data_repo", "FinancialDataRepo"),
    "adj_factors": ("adj_factors_repo", "AdjFactorsRepo"),
    "corporate_actions": ("corporate_actions_repo", "CorporateActionsRepo"),
    "market_quotes": ("market_quotes_repo", "MarketQuotesRepo"),
    "news": ("news_repo", "NewsRepo"),
}


def _get_repo(domain: str) -> Any:
    """按域懒加载 Repo 实例（统一 upsert_many(records, market) 接口）。"""
    from importlib import import_module

    entry = _REPO_TABLE.get(domain)
    if not entry:
        raise ValueError(
            f"域 {domain} 无对应 Repo；请在 _REPO_TABLE 注册"
            f"（app/worker/base_market_sync.py）"
        )
    module = import_module(
        f"app.data.storage.mongo.repositories.{entry[0]}"
    )
    return getattr(module, entry[1])()


class BaseMarketDomainSync(ABC):
    """跨市场（CN/HK/US）域级同步基类。

    子类责任：
        - 声明 ``market``（"CN" / "HK" / "US"）和 ``domain``

    基类负责：
        - 通过 CapabilityRegistry + PriorityConfig 解析数据源优先级
        - 逐源走 ``FallbackRouter.fetch_source()``（熔断/限流/重试/校验四件套）
        - 入库分发到对应 Repo（upsert 键来自 key_spec 单一事实源）
        - sync_event 写入（成功/失败均记录）+ checkpoint
    """

    market: str = ""
    domain: str = ""
    description: str = ""

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
        provider_kwargs_fn: Optional[Callable[[], Dict]] = None,
    ) -> Dict[str, Any]:
        """执行单域同步（router 四件套 fallback + Repo 入库）。

        Args:
            provider_method: Provider 上的方法名（raw fetch 入口）
            provider_kwargs_fn: 可选函数，返回传递给 provider 方法的 kwargs

        Note:
            **失败也写 sync_event**（``event_type=SYNC_FAILED``）是设计意图 —
            保证 ``sync_events`` 集合记录每一次同步尝试，便于监控失败率。
            若曾依赖"无 sync_event 即失败"的旧逻辑（HK/US 历史 _common 实现），
            迁移后需相应调整监控告警阈值，避免 SYNC_FAILED 计数突增。
        """
        from app.data.processor.fallback_router import FallbackRouter

        start = time.time()
        router = FallbackRouter.get_instance()
        sources = await self.get_sources()
        kwargs = provider_kwargs_fn() if provider_kwargs_fn else {}

        repo = _get_repo(self.domain)
        fallback_chain: List[str] = []

        for source_name in sources:
            async def raw_fetch(provider, _kwargs=kwargs, _method=provider_method):
                return await getattr(provider, _method)(**_kwargs)

            status, records, _verrs = await router.fetch_source(
                self.market, self.domain, source_name, raw_fetch
            )
            if status == "failed":
                fallback_chain.append(source_name)
                continue
            if status == "skip":
                continue

            # success：Router 已完成标准化 + 校验（输出 db-ready dicts）
            count = await repo.upsert_many(records, self.market)
            elapsed = int((time.time() - start) * 1000)
            logger.info(
                f"{self.market} {self.domain} 同步完成: "
                f"{count} 条, 源={source_name}, 耗时={elapsed}ms"
            )

            await self._write_sync_event(
                success=True, source=source_name, record_count=count,
                duration_ms=elapsed,
            )
            await self._write_checkpoint(
                success=True, source=source_name, record_count=count,
                duration_ms=elapsed,
            )

            return {
                "domain": self.domain, "success": True, "source": source_name,
                "records": count, "duration_ms": elapsed,
            }

        elapsed = int((time.time() - start) * 1000)
        error = f"所有数据源失败: {', '.join(fallback_chain)}" if fallback_chain else "无可用数据源"
        await self._write_sync_event(
            success=False, source="", record_count=0,
            duration_ms=elapsed, error=error,
        )
        await self._write_checkpoint(
            success=False, source="", record_count=0,
            duration_ms=elapsed,
        )
        return {
            "domain": self.domain, "success": False,
            "error": error, "duration_ms": elapsed,
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
