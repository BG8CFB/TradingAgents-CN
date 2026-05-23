#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一股票数据服务 — 通过 DataInterface 访问，供路由层调用。"""

import logging
from typing import Dict, List, Optional

from app.data.core.interface import DataInterface

logger = logging.getLogger("webapi")


class UnifiedStockService:
    """统一股票数据服务（跨市场，通过 DataInterface 访问）。"""

    def __init__(self, db=None):
        # db 参数保留以兼容旧调用方，实际通过 DataInterface 访问
        pass

    def _di(self) -> DataInterface:
        return DataInterface.get_instance()

    async def get_stock_info(
        self, market: str, code: str, source: Optional[str] = None
    ) -> Optional[Dict]:
        result = await self._di().read(market, "basic_info", symbol=code)
        return result.get("data")

    async def get_stock_quote(self, market: str, code: str) -> Optional[Dict]:
        result = await self._di().read(market, "market_quotes", symbol=code)
        return result.get("data")

    async def search_stocks(self, market: str, query: str, limit: int = 20) -> List[Dict]:
        """搜索股票 — 通过 DataInterface 的底层仓储实现 regex 搜索。"""
        from app.data.core.reader import Reader
        reader = Reader()
        repo = reader._get_repo("basic_info")
        if not repo:
            return []

        from app.data.storage.mongo.client import get_motor_db
        from app.data.storage.mongo.collections import get_collection_name
        db = get_motor_db()
        coll = db[get_collection_name("basic_info", market)]

        filter_query = {
            "$or": [
                {"symbol": {"$regex": query, "$options": "i"}},
                {"name": {"$regex": query, "$options": "i"}},
                {"name_en": {"$regex": query, "$options": "i"}},
                {"full_symbol": {"$regex": query, "$options": "i"}},
            ]
        }
        cursor = coll.find(filter_query, {"_id": 0}).limit(limit)
        return await cursor.to_list(length=None)

    async def get_daily_quotes(
        self, market: str, code: str,
        start_date: Optional[str] = None, end_date: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        result = await self._di().read(market, "daily_quotes", symbol=code,
                                       start_date=start_date, end_date=end_date)
        data = result.get("data")
        if not data:
            return []
        if isinstance(data, list):
            return data[-limit:]
        return [data]

    async def get_cn_quote_with_basic_info(self, code6: str) -> Optional[Dict]:
        """获取 A 股实时行情（合并 market_quotes + basic_info）。"""
        di = self._di()

        q_result = await di.read("CN", "market_quotes", symbol=code6)
        q = q_result.get("data")

        b_result = await di.read("CN", "basic_info", symbol=code6)
        b = b_result.get("data")

        if not q and not b:
            return None

        close = (q or {}).get("close")
        pct = (q or {}).get("pct_chg")
        pre_close_saved = (q or {}).get("pre_close")
        prev_close = pre_close_saved
        if prev_close is None:
            try:
                if close is not None and pct is not None:
                    prev_close = round(float(close) / (1.0 + float(pct) / 100.0), 4)
            except Exception:
                prev_close = None

        turnover_rate = (q or {}).get("turnover_rate")
        if turnover_rate is None:
            turnover_rate = (b or {}).get("turnover_rate")

        amplitude = None
        try:
            high = (q or {}).get("high")
            low = (q or {}).get("low")
            if high is not None and low is not None and prev_close is not None and prev_close > 0:
                amplitude = round((float(high) - float(low)) / float(prev_close) * 100, 2)
        except Exception:
            pass

        return {
            "symbol": code6,
            "name": (b or {}).get("name"),
            "market": (b or {}).get("market"),
            "price": close,
            "change_percent": pct,
            "amount": (q or {}).get("amount"),
            "volume": (q or {}).get("volume"),
            "open": (q or {}).get("open"),
            "high": (q or {}).get("high"),
            "low": (q or {}).get("low"),
            "prev_close": prev_close,
            "turnover_rate": turnover_rate,
            "amplitude": amplitude,
            "trade_date": (q or {}).get("trade_date"),
            "updated_at": (q or {}).get("updated_at"),
            "data_source": (q or {}).get("data_source") or (b or {}).get("data_source"),
        }

    async def get_cn_fundamentals(
        self, code6: str, source: Optional[str] = None,
    ) -> Optional[Dict]:
        """获取 A 股基本面快照（basic_info + financial_data + daily_indicators）。"""
        di = self._di()

        b_result = await di.read("CN", "basic_info", symbol=code6)
        b = b_result.get("data")
        if not b:
            return None

        # 获取最新财务数据
        financial_data = None
        try:
            f_result = await di.read("CN", "financial_data", symbol=code6)
            f_data = f_result.get("data")
            if f_data and isinstance(f_data, list) and f_data:
                financial_data = f_data[0]
            elif f_data and isinstance(f_data, dict):
                financial_data = f_data
        except Exception as e:
            logger.warning(f"获取财务数据失败: {e}")

        # 获取实时指标
        realtime_metrics = {}
        try:
            ind_result = await di.read("CN", "daily_indicators", symbol=code6)
            ind_data = ind_result.get("data")
            if ind_data and isinstance(ind_data, list) and ind_data:
                latest = ind_data[0]
                realtime_metrics = {
                    "pe": latest.get("pe_ttm"),
                    "pb": latest.get("pb"),
                    "pe_ttm": latest.get("pe_ttm"),
                    "market_cap": latest.get("total_mv"),
                    "source": "daily_indicators",
                    "is_realtime": False,
                    "updated_at": latest.get("updated_at"),
                }
            elif ind_data and isinstance(ind_data, dict):
                realtime_metrics = {
                    "pe": ind_data.get("pe_ttm"),
                    "pb": ind_data.get("pb"),
                    "pe_ttm": ind_data.get("pe_ttm"),
                    "market_cap": ind_data.get("total_mv"),
                    "source": "daily_indicators",
                    "is_realtime": False,
                    "updated_at": ind_data.get("updated_at"),
                }
        except Exception as e:
            logger.warning(f"获取实时PE/PB失败: {e}")

        realtime_market_cap = realtime_metrics.get("market_cap")
        total_mv = realtime_market_cap if realtime_market_cap else b.get("total_mv")

        result_data = {
            "symbol": code6,
            "name": b.get("name"),
            "industry": b.get("industry"),
            "market": b.get("market"),
            "sector": b.get("market"),
            "pe": realtime_metrics.get("pe") or b.get("pe"),
            "pb": realtime_metrics.get("pb") or b.get("pb"),
            "pe_ttm": realtime_metrics.get("pe_ttm") or b.get("pe_ttm"),
            "pb_mrq": realtime_metrics.get("pb_mrq") or b.get("pb_mrq"),
            "ps": None,
            "ps_ttm": None,
            "pe_source": realtime_metrics.get("source", "unknown"),
            "pe_is_realtime": realtime_metrics.get("is_realtime", False),
            "pe_updated_at": realtime_metrics.get("updated_at"),
            "roe": None,
            "debt_ratio": None,
            "total_mv": total_mv,
            "circ_mv": b.get("circ_mv"),
            "mv_is_realtime": bool(realtime_market_cap),
            "turnover_rate": b.get("turnover_rate"),
            "volume_ratio": b.get("volume_ratio"),
            "updated_at": b.get("updated_at"),
            "data_source": b.get("data_source"),
        }

        if financial_data:
            if financial_data.get("financial_indicators"):
                indicators = financial_data["financial_indicators"]
                result_data["roe"] = indicators.get("roe")
                result_data["debt_ratio"] = indicators.get("debt_to_assets")
            if result_data["roe"] is None:
                result_data["roe"] = financial_data.get("roe")
            if result_data["debt_ratio"] is None:
                result_data["debt_ratio"] = financial_data.get("debt_to_assets")

            revenue_ttm = financial_data.get("revenue_ttm")
            revenue = financial_data.get("revenue")
            revenue_for_ps = revenue_ttm if revenue_ttm and revenue_ttm > 0 else revenue

            if revenue_for_ps and revenue_for_ps > 0 and total_mv and total_mv > 0:
                revenue_yi = revenue_for_ps / 100000000
                ps_calculated = total_mv / revenue_yi
                result_data["ps"] = round(ps_calculated, 2)
                result_data["ps_ttm"] = round(ps_calculated, 2) if revenue_ttm else None

        if result_data["roe"] is None:
            result_data["roe"] = b.get("roe")

        return result_data

    async def get_market_quotes_raw(self, code: str) -> Optional[Dict]:
        result = await self._di().read("CN", "market_quotes", symbol=code)
        return result.get("data")

    async def get_supported_markets(self) -> List[Dict]:
        """获取支持的市场列表。"""
        from app.engine.config.runtime_settings import get_timezone_name

        return [
            {"code": "CN", "name": "A股", "name_en": "China A-Share",
             "currency": "CNY", "timezone": get_timezone_name()},
            {"code": "HK", "name": "港股", "name_en": "Hong Kong Stock",
             "currency": "HKD", "timezone": "Asia/Hong_Kong"},
            {"code": "US", "name": "美股", "name_en": "US Stock",
             "currency": "USD", "timezone": "America/New_York"},
        ]
