"""
A 股同步编排器

负责按依赖链调度各域同步任务：
  trade_calendar → basic_info → daily_quotes → daily_indicators
                                       ↓             ↓
                                   adj_factors    financial
                                       ↓
                               aggregation（周线/月线）

非交易日自动跳过。
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.data.processor.fallback_router import FallbackRouter
from app.utils.time_utils import now_utc

from .domain_sync import (
    BaseDomainSync,
    BasicInfoSync,
    TradeCalendarSync,
    DailyQuotesSync,
    DailyIndicatorsSync,
    AdjFactorsSync,
    FinancialDataSync,
    NewsSync,
    AggregationSync,
)
from .domain_sync.base_domain_sync import DomainSyncResult

logger = logging.getLogger(__name__)

# 依赖链定义：每个域的前置依赖
_DEPENDENCIES: Dict[str, List[str]] = {
    "trade_calendar": [],
    "basic_info": [],
    "daily_quotes": ["basic_info"],
    "daily_indicators": ["daily_quotes"],
    "adj_factors": ["daily_quotes"],
    "financial": ["daily_quotes"],
    "news": ["basic_info"],
    "aggregation_weekly": ["daily_quotes"],
    "aggregation_monthly": ["daily_quotes"],
}

# 可并行的域组
_PARALLEL_GROUPS = [
    ["trade_calendar", "basic_info"],     # 第一批：无依赖
    ["daily_quotes"],                      # 第二批：依赖 basic_info
    ["daily_indicators", "adj_factors", "financial", "news"],  # 第三批：依赖日线或基础信息
    ["aggregation_weekly", "aggregation_monthly"],      # 第四批：聚合
]


@dataclass
class OrchestratorResult:
    """编排器执行结果"""
    success: bool = False
    domains: Dict[str, DomainSyncResult] = field(default_factory=dict)
    duration_ms: int = 0
    skipped: bool = False
    skip_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "duration_ms": self.duration_ms,
            "domains": {d: r.to_dict() for d, r in self.domains.items()},
        }


class CNSyncOrchestrator:
    """
    A 股同步编排器

    使用方式：
        orchestrator = CNSyncOrchestrator()
        result = await orchestrator.run(symbol="000001")
        result = await orchestrator.run_full()  # 全量同步
    """

    def __init__(self, router: Optional[FallbackRouter] = None):
        self._router = router or FallbackRouter()
        self._domain_syncs: Dict[str, BaseDomainSync] = {
            "trade_calendar": TradeCalendarSync(router=self._router),
            "basic_info": BasicInfoSync(router=self._router),
            "daily_quotes": DailyQuotesSync(router=self._router),
            "daily_indicators": DailyIndicatorsSync(router=self._router),
            "adj_factors": AdjFactorsSync(router=self._router),
            "financial": FinancialDataSync(router=self._router),
            "news": NewsSync(router=self._router),
        }
        self._aggregation_sync = AggregationSync(router=self._router)
        self._inter_stock_delay: float = 0.1  # 批量时间股票间隔（秒）

    async def is_trading_day(self) -> bool:
        """判断今天是否为交易日"""
        try:
            from app.core.database import get_database
            from app.data.schema.collections import get_collection_name

            db = await get_database()
            collection = db[get_collection_name("CN", "trade_calendar")]
            today = now_utc().strftime("%Y%m%d")

            doc = await collection.find_one({"cal_date": today, "is_open": 1})
            return doc is not None
        except Exception:
            # 查询失败默认为交易日（不阻断同步）
            logger.warning("无法查询交易日历，默认为交易日")
            return True

    async def run(
        self,
        symbol: str,
        domains: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        skip_trading_day_check: bool = False,
        providers: Optional[Dict[str, Any]] = None,
    ) -> OrchestratorResult:
        """
        执行指定股票的域同步。

        Args:
            symbol: 股票代码
            domains: 要同步的域列表，None 表示全部
            start_date: 数据起始日期
            end_date: 数据结束日期
            skip_trading_day_check: 是否跳过交易日检查
            providers: Provider 实例字典
        """
        start_time = time.monotonic()

        # 交易日检查
        if not skip_trading_day_check and not await self.is_trading_day():
            logger.info("今日非交易日，跳过同步")
            return OrchestratorResult(
                skipped=True, skip_reason="非交易日",
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )

        if domains is None:
            domains = list(self._domain_syncs.keys())

        providers = providers or {}
        result = OrchestratorResult()
        failed_domains: set = set()

        for group in _PARALLEL_GROUPS:
            # 过滤出当前批次需要执行的域
            tasks = []
            task_domains = []

            for domain in group:
                if domain.startswith("aggregation_"):
                    continue  # 聚合单独处理
                if domain not in domains:
                    continue
                # 检查依赖是否满足
                deps = _DEPENDENCIES.get(domain, [])
                if any(d in failed_domains for d in deps):
                    logger.warning("域 %s 的依赖 %s 失败，跳过", domain, deps)
                    continue

                sync = self._domain_syncs.get(domain)
                if sync:
                    tasks.append(sync.sync(
                        symbol=symbol,
                        start_date=start_date,
                        end_date=end_date,
                        providers=providers,
                    ))
                    task_domains.append(domain)

            if not tasks:
                continue

            # 并行执行当前批次
            domain_results = await asyncio.gather(*tasks, return_exceptions=True)

            for domain, dr in zip(task_domains, domain_results):
                if isinstance(dr, Exception):
                    result.domains[domain] = DomainSyncResult(
                        domain=domain, success=False, error=str(dr),
                    )
                    failed_domains.add(domain)
                else:
                    result.domains[domain] = dr
                    if not dr.success:
                        failed_domains.add(domain)

        # 聚合同步（如果日线成功且请求了聚合）
        if "daily_quotes" in result.domains and result.domains["daily_quotes"].success:
            for period in ["weekly", "monthly"]:
                agg_domain = f"aggregation_{period}"
                if domains is None or agg_domain in domains:
                    try:
                        agg_result = await self._aggregation_sync.sync(
                            symbol=symbol,
                            start_date=start_date,
                            end_date=end_date,
                            period=period,
                        )
                        result.domains[agg_domain] = agg_result
                    except Exception as e:
                        result.domains[agg_domain] = DomainSyncResult(
                            domain=agg_domain, success=False, error=str(e),
                        )

        result.duration_ms = int((time.monotonic() - start_time) * 1000)
        result.success = all(dr.success for dr in result.domains.values())

        return result

    async def run_full(
        self,
        symbols: Optional[List[str]] = None,
        domains: Optional[List[str]] = None,
        batch_size: int = 200,
        job_id: Optional[str] = None,
    ) -> Dict[str, OrchestratorResult]:
        """
        批量全量同步。

        Args:
            symbols: 股票列表，None 表示全市场
            domains: 域列表
            batch_size: 每批股票数量
            job_id: 可选任务 ID，用于进度追踪
        """
        if symbols is None:
            symbols = await self._get_all_symbols()

        results: Dict[str, OrchestratorResult] = {}
        total = len(symbols)

        # 先同步全局数据（交易日历 + 基础信息）
        calendar_result = await self._domain_syncs["trade_calendar"].sync(
            providers={},
        )
        basic_result = await self._domain_syncs["basic_info"].sync(
            providers={},
        )

        # 批量同步单股数据
        processed = 0
        for i in range(0, total, batch_size):
            batch = symbols[i:i + batch_size]
            logger.info("批量同步 %d/%d: %s", i + len(batch), total,
                        f"{batch[0]}-{batch[-1]}" if len(batch) > 1 else batch[0])

            for symbol in batch:
                result = await self.run(
                    symbol=symbol, domains=domains,
                    skip_trading_day_check=True,
                )
                results[symbol] = result
                processed += 1

                # 限流
                if self._inter_stock_delay > 0:
                    await asyncio.sleep(self._inter_stock_delay)

            # 进度追踪
            if job_id:
                await self._update_job_progress(job_id, processed, total)

        return results

    async def _get_all_symbols(self) -> List[str]:
        """获取全市场股票代码"""
        try:
            from app.core.database import get_database
            from app.data.schema.collections import get_collection_name

            db = await get_database()
            collection = db[get_collection_name("CN", "basic_info")]
            cursor = collection.find({}, {"symbol": 1}).sort("symbol", 1)
            docs = await cursor.to_list(length=None)
            return [doc["symbol"] for doc in docs if "symbol" in doc]
        except Exception as e:
            logger.error("获取股票列表失败: %s", e)
            return []

    async def sync_realtime(self, providers: Optional[Dict[str, Any]] = None) -> DomainSyncResult:
        """同步实时行情（全市场批量，非按股）"""
        start_time = time.monotonic()
        providers = providers or {}

        try:
            fetch_result = await self._router.fetch(
                "market_quotes", providers=providers,
            )
            latency = int((time.monotonic() - start_time) * 1000)

            if fetch_result.success and fetch_result.data is not None:
                # 写入 market_quotes 集合
                try:
                    from app.core.database import get_database
                    db = await get_database()
                    collection = db[get_collection_name("CN", "market_quotes")]

                    import pandas as pd
                    if isinstance(fetch_result.data, pd.DataFrame):
                        records = fetch_result.data.to_dict("records") if not fetch_result.data.empty else []
                    elif isinstance(fetch_result.data, list):
                        records = fetch_result.data
                    else:
                        records = [fetch_result.data]

                    if records:
                        from pymongo import UpdateOne
                        now_iso = now_utc().isoformat()
                        ops = []
                        for rec in records:
                            filter_doc = {"symbol": rec.get("symbol")}
                            if "trade_date" in rec:
                                filter_doc["trade_date"] = rec["trade_date"]
                            rec["data_source"] = fetch_result.source
                            rec["updated_at"] = now_iso
                            ops.append(UpdateOne(filter_doc, {"$set": rec}, upsert=True))
                        if ops:
                            wr = await collection.bulk_write(ops, ordered=False)
                            return DomainSyncResult(
                                domain="market_quotes", success=True,
                                source=fetch_result.source, records_synced=wr.upserted_count + wr.modified_count,
                                latency_ms=latency,
                            )
                except Exception as e:
                    logger.error("实时行情写入失败: %s", e)

                return DomainSyncResult(
                    domain="market_quotes", success=True,
                    source=fetch_result.source, latency_ms=latency,
                )
            else:
                return DomainSyncResult(
                    domain="market_quotes", success=False,
                    source=fetch_result.source, error=fetch_result.error or "数据获取失败",
                    latency_ms=latency,
                )
        except Exception as e:
            return DomainSyncResult(
                domain="market_quotes", success=False, error=str(e),
                latency_ms=int((time.monotonic() - start_time) * 1000),
            )

    async def run_news_sync(
        self,
        symbols: Optional[List[str]] = None,
        favorites_only: bool = False,
    ) -> OrchestratorResult:
        """新闻同步"""
        start_time = time.monotonic()

        if favorites_only and symbols is None:
            symbols = await self._get_favorite_symbols()

        if not symbols:
            return OrchestratorResult(
                skipped=True, skip_reason="无股票需同步新闻",
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )

        news_sync = self._domain_syncs.get("news")
        if not news_sync:
            return OrchestratorResult(
                success=False,
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )

        all_results: Dict[str, DomainSyncResult] = {}
        for symbol in symbols[:50]:  # 限制范围
            r = await news_sync.sync(symbol=symbol)
            all_results[f"news:{symbol}"] = r
            if self._inter_stock_delay > 0:
                await asyncio.sleep(self._inter_stock_delay)

        duration = int((time.monotonic() - start_time) * 1000)
        return OrchestratorResult(
            success=all(r.success for r in all_results.values()),
            domains=all_results,
            duration_ms=duration,
        )

    async def _get_favorite_symbols(self) -> List[str]:
        """获取自选股列表"""
        try:
            from app.core.database import get_database
            db = await get_database()
            cursor = db["favorites"].find({}, {"symbol": 1})
            docs = await cursor.to_list(length=None)
            return [doc["symbol"] for doc in docs if "symbol" in doc]
        except Exception:
            return []

    async def _update_job_progress(self, job_id: str, processed: int, total: int) -> None:
        """更新任务进度"""
        try:
            from app.services.scheduler_service import update_job_progress
            await update_job_progress(job_id, processed, total)
        except Exception:
            pass


# ── 单例 ──

_instance: Optional[CNSyncOrchestrator] = None


def get_cn_sync_orchestrator() -> CNSyncOrchestrator:
    """获取全局 A 股同步编排器单例"""
    global _instance
    if _instance is None:
        _instance = CNSyncOrchestrator()
    return _instance
