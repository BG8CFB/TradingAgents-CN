"""
跨市场同步服务基类

HK/US SyncService 的公共逻辑抽象，消除代码重复。
子类仅需覆盖 market 配置和 _get_stock_list() 即可。
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.data.core.interface import DataInterface
from app.data.storage.mongo.collections import get_collection_name
from app.utils.timezone import now_config_tz, format_date_short, now_utc

logger = logging.getLogger(__name__)


class BaseSyncService:
    """跨市场同步服务基类，子类须设置 market / market_name 并覆盖 _get_stock_list()"""

    market: str = ""
    market_name: str = ""

    def __init__(self, batch_size: int, rate_limit_delay: float):
        self._di: Optional[DataInterface] = None
        self.batch_size = batch_size
        self.rate_limit_delay = rate_limit_delay

    async def initialize(self):
        self._di = DataInterface.get_instance()

    def _get_data_interface(self) -> DataInterface:
        if self._di is None:
            self._di = DataInterface.get_instance()
        return self._di

    async def _get_stock_list(self) -> List[str]:
        """子类必须覆盖此方法，返回当前市场的股票代码列表"""
        raise NotImplementedError

    async def _ensure_initialized(self):
        if self._di is None:
            await self.initialize()

    def _make_stats(self, **extra_fields) -> Dict[str, Any]:
        stats = {
            "total_processed": 0,
            "success_count": 0,
            "error_count": 0,
            "start_time": now_utc(),
            "end_time": None,
            "duration": 0,
            "errors": [],
        }
        stats.update(extra_fields)
        return stats

    def _complete_stats(self, stats: Dict[str, Any]) -> Dict[str, Any]:
        stats["end_time"] = now_utc()
        start_time = stats.get("start_time")
        if start_time:
            stats["duration"] = (stats["end_time"] - start_time).total_seconds()
        return stats

    # ── 同步方法 ──────────────────────────────────────────────────────

    async def sync_stock_basic_info(self, force_update: bool = False) -> Dict[str, Any]:
        """同步基础信息 — 通过 DataInterface 刷新每只股票"""
        await self._ensure_initialized()
        stats = self._make_stats(task="sync_stock_basic_info")
        di = self._get_data_interface()

        symbols = await self._get_stock_list()
        stats["total_processed"] = len(symbols)
        logger.info(f"开始同步{self.market_name}基础信息: {len(symbols)} 只股票")

        for idx, symbol in enumerate(symbols, 1):
            if not force_update:
                try:
                    result = await di.read(self.market, "basic_info", symbol=symbol)
                    data = result.get("data")
                    freshness = result.get("freshness")
                    if data and freshness == "fresh":
                        stats["success_count"] += 1
                        continue
                except Exception:
                    pass

            try:
                refresh_result = await di.refresh(
                    self.market, symbol, domains=["basic_info"],
                    force=force_update, timeout=30,
                )
                domain_result = refresh_result.domains.get("basic_info")
                if domain_result and domain_result.status in ("refreshed", "fresh"):
                    stats["success_count"] += 1
                else:
                    stats["error_count"] += 1
            except Exception as e:
                logger.debug(f"{self.market_name} {symbol} 同步基础信息失败: {e}")
                stats["error_count"] += 1

            if idx % self.batch_size == 0:
                logger.info(f"{self.market_name}基础信息同步进度: {idx}/{len(symbols)}")
                await asyncio.sleep(self.rate_limit_delay)

        return self._complete_stats(stats)

    async def sync_daily_quotes(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        incremental: bool = True,
    ) -> Dict[str, Any]:
        """同步日线行情 — 通过 DataInterface 刷新每只股票"""
        await self._ensure_initialized()
        stats = self._make_stats(task="sync_daily_quotes")
        di = self._get_data_interface()

        symbols = await self._get_stock_list()
        stats["total_processed"] = len(symbols)

        if not end_date:
            end_date = format_date_short(now_config_tz())
        if not start_date:
            start_date = format_date_short(now_config_tz() - timedelta(days=30))

        logger.info(f"开始同步{self.market_name}日线: {len(symbols)} 只, {start_date} ~ {end_date}")

        for idx, symbol in enumerate(symbols, 1):
            actual_start = start_date
            if incremental:
                try:
                    result = await di.read(self.market, "daily_quotes", symbol=symbol)
                    data = result.get("data")
                    if data and isinstance(data, list) and data:
                        latest_date = data[0].get("trade_date")
                        for record in data:
                            td = record.get("trade_date")
                            if td and (not latest_date or td > latest_date):
                                latest_date = td
                        if latest_date:
                            try:
                                last_dt = datetime.strptime(latest_date, "%Y-%m-%d")
                                actual_start = (last_dt + timedelta(days=1)).strftime("%Y-%m-%d")
                            except ValueError:
                                pass
                except Exception:
                    pass

            if incremental and actual_start > end_date:
                stats["success_count"] += 1
            else:
                try:
                    refresh_result = await di.refresh(
                        self.market, symbol, domains=["daily_quotes"],
                        force=True, timeout=30,
                    )
                    domain_result = refresh_result.domains.get("daily_quotes")
                    if domain_result and domain_result.status in ("refreshed", "fresh"):
                        stats["success_count"] += 1
                    else:
                        stats["error_count"] += 1
                except Exception as e:
                    logger.debug(f"{self.market_name} {symbol} 同步行情失败: {e}")
                    stats["error_count"] += 1

            if idx % self.batch_size == 0:
                logger.info(f"{self.market_name}日线同步进度: {idx}/{len(symbols)}")
                await asyncio.sleep(self.rate_limit_delay)

        return self._complete_stats(stats)

    async def run_status_check(self) -> Dict[str, Any]:
        """数据源状态检查"""
        await self._ensure_initialized()
        di = self._get_data_interface()

        basic_coll = get_collection_name("basic_info", self.market)
        daily_coll = get_collection_name("daily_quotes", self.market)

        basic_count = 0
        daily_count = 0
        latest_basic = None
        latest_daily = None

        try:
            from app.core.database import get_mongo_db
            db = get_mongo_db()
            basic_count = await db[basic_coll].count_documents({})
            daily_count = await db[daily_coll].count_documents({})

            doc = await db[basic_coll].find_one({}, sort=[("updated_at", -1)])
            if doc:
                latest_basic = doc.get("updated_at")
            doc = await db[daily_coll].find_one({}, sort=[("trade_date", -1)])
            if doc:
                latest_daily = doc.get("trade_date")
        except Exception as e:
            logger.warning(f"{self.market_name}状态检查查询数据库失败: {e}")

        available_sources = []
        try:
            health_list = await di.get_source_health(self.market)
            available_sources = [h.get("source", "") for h in health_list if h.get("healthy")]
        except Exception as e:
            logger.warning(f"获取{self.market_name}数据源健康状态失败: {e}")

        return {
            "market": self.market,
            "basic_info_count": basic_count,
            "daily_quotes_count": daily_count,
            "latest_basic_info_update": str(latest_basic) if latest_basic else None,
            "latest_trade_date": latest_daily,
            "available_sources": available_sources,
        }
