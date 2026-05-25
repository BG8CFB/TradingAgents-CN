"""完整性检查器 — 检查日线数据连续性和日度完整性。"""

import logging
from datetime import date, timedelta
from typing import Dict, List, Optional

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name

logger = logging.getLogger(__name__)


class CompletenessChecker:
    """数据完整性检查。"""

    async def check_daily_completeness(
        self, market: str, check_date: Optional[str] = None
    ) -> Dict[str, List[Dict]]:
        """检查指定日期各域数据完整性。

        Returns:
            {domain: [缺失记录]}，缺失记录含 symbol 和缺失日期。
        """
        if check_date is None:
            check_date = date.today().isoformat()

        db = get_motor_db()
        results = {}

        # 检查日线行情
        quotes_coll = get_collection_name("daily_quotes", market)
        basic_coll = get_collection_name("basic_info", market)

        # 获取活跃股票
        basic_cursor = db[basic_coll].find(
            {"list_status": {"$in": ["L", "LIST"]}},
            {"symbol": 1, "_id": 0}
        )
        active_stocks = await basic_cursor.to_list(length=None)

        # 批量查询当日有行情的股票，然后在内存中做差集
        existing_symbols = await db[quotes_coll].distinct("symbol", {"trade_date": check_date})
        active_symbols = {s["symbol"] for s in active_stocks}
        missing_quotes = [
            {"symbol": s, "missing_date": check_date}
            for s in active_symbols - set(existing_symbols)
        ]

        if missing_quotes:
            results["daily_quotes"] = missing_quotes

        return results

    async def check_continuity(
        self, market: str, symbol: str, domain: str = "daily_quotes",
        start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> List[str]:
        """检查指定股票在日期范围内的数据连续性。

        Returns:
            缺失日期列表。
        """
        db = get_motor_db()
        coll_name = get_collection_name(domain, market)

        if not end_date:
            end_date = date.today().isoformat()
        if not start_date:
            start_date = (date.today() - timedelta(days=30)).isoformat()

        # 获取交易日历
        cal_coll = get_collection_name("trade_calendar", market)
        cal_docs = await db[cal_coll].find(
            {
                "market": market,
                "cal_date": {"$gte": start_date, "$lte": end_date},
                "is_open": True,
            },
            {"cal_date": 1, "_id": 0}
        ).to_list(length=None)
        trading_days = {d["cal_date"] for d in cal_docs}

        if not trading_days:
            return []

        # 获取已有数据日期
        data_docs = await db[coll_name].find(
            {"symbol": symbol, "trade_date": {"$gte": start_date, "$lte": end_date}},
            {"trade_date": 1, "_id": 0}
        ).to_list(length=None)
        existing_dates = {d["trade_date"] for d in data_docs}

        missing = sorted(trading_days - existing_dates)
        return missing

    async def check_and_report(self, market: str) -> Dict:
        """执行完整性检查并记录事件。"""
        from app.data.storage.mongo.repositories.metadata_repo import MetadataRepo

        meta = MetadataRepo()
        completeness = await self.check_daily_completeness(market)

        total_missing = sum(len(v) for v in completeness.values())

        await meta.insert_event({
            "event_type": "COMPLETENESS_CHECK",
            "market": market,
            "missing_count": total_missing,
            "details": {k: len(v) for k, v in completeness.items()},
        })

        if total_missing > 0:
            logger.warning(f"数据完整性检查: {market} 缺失 {total_missing} 条记录")

        return {"total_missing": total_missing, "details": completeness}
