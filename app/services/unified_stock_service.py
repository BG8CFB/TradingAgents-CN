#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一股票数据服务（跨市场，支持多数据源）

功能：
1. 跨市场数据访问（A股/港股/美股）
2. 多数据源优先级查询
3. 统一的查询接口
"""

import logging
from typing import Dict, List, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.data.storage.mongo.collections import get_collection_name

logger = logging.getLogger("webapi")


class UnifiedStockService:
    """统一股票数据服务（跨市场，支持多数据源）"""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    def _get_coll(self, domain: str, market: str):
        """获取指定域和市场的 MongoDB 集合。"""
        return self.db[get_collection_name(domain, market)]

    @staticmethod
    def _normalize_doc(doc: Optional[Dict]) -> Optional[Dict]:
        """为仍消费旧字段的调用方补齐兼容别名。"""
        if not doc:
            return doc

        normalized = dict(doc)
        symbol = normalized.get("symbol") or normalized.get("code")
        data_source = normalized.get("data_source") or normalized.get("source")

        if symbol and "symbol" not in normalized:
            normalized["symbol"] = symbol
        if symbol and "code" not in normalized:
            normalized["code"] = symbol
        if data_source and "data_source" not in normalized:
            normalized["data_source"] = data_source
        if data_source and "source" not in normalized:
            normalized["source"] = data_source

        return normalized

    async def get_stock_info(
        self, market: str, code: str, source: Optional[str] = None
    ) -> Optional[Dict]:
        """获取股票基础信息（支持多数据源，按优先级查询）。"""
        coll = self._get_coll("basic_info", market)

        if source:
            doc = await coll.find_one({"symbol": code, "data_source": source}, {"_id": 0})
        else:
            source_priority = await self._get_source_priority(market)
            doc = None
            for src in source_priority:
                doc = await coll.find_one({"symbol": code, "data_source": src}, {"_id": 0})
                if doc:
                    break
            if not doc:
                doc = await coll.find_one({"symbol": code}, {"_id": 0})

        return self._normalize_doc(doc)

    async def _get_source_priority(self, market: str) -> List[str]:
        """从数据库获取数据源优先级。"""
        market_category_map = {
            "CN": "a_shares",
            "HK": "hk_stocks",
            "US": "us_stocks",
        }
        market_category_id = market_category_map.get(market)

        try:
            groupings = await self.db.datasource_groupings.find({
                "market_category_id": market_category_id,
                "enabled": True,
            }).sort("priority", -1).to_list(length=None)

            if groupings:
                return [g["data_source_name"] for g in groupings]
        except Exception as e:
            logger.warning(f"从数据库读取数据源优先级失败: {e}")

        default_priority = {
            "CN": ["tushare", "akshare", "baostock"],
            "HK": ["yfinance_hk", "akshare_hk"],
            "US": ["yfinance"],
        }
        return default_priority.get(market, [])

    async def get_stock_quote(self, market: str, code: str) -> Optional[Dict]:
        """获取实时行情。"""
        coll = self._get_coll("market_quotes", market)
        doc = await coll.find_one({"symbol": code}, {"_id": 0})
        return self._normalize_doc(doc)

    async def search_stocks(self, market: str, query: str, limit: int = 20) -> List[Dict]:
        """搜索股票（去重，只返回每个股票的最优数据源）。"""
        coll = self._get_coll("basic_info", market)

        filter_query = {
            "$or": [
                {"symbol": {"$regex": query, "$options": "i"}},
                {"name": {"$regex": query, "$options": "i"}},
                {"name_en": {"$regex": query, "$options": "i"}},
                {"full_symbol": {"$regex": query, "$options": "i"}},
            ]
        }

        cursor = coll.find(filter_query)
        all_results = await cursor.to_list(length=None)

        if not all_results:
            return []

        source_priority = await self._get_source_priority(market)
        unique_results: Dict[str, Dict] = {}

        for doc in all_results:
            symbol = doc.get("symbol")
            source = doc.get("data_source")
            if not symbol:
                continue

            if symbol not in unique_results:
                unique_results[symbol] = doc
            else:
                current_source = unique_results[symbol].get("data_source")
                try:
                    if source in source_priority and current_source in source_priority:
                        if source_priority.index(source) < source_priority.index(current_source):
                            unique_results[symbol] = doc
                except ValueError:
                    pass

        return [self._normalize_doc(doc) for doc in list(unique_results.values())[:limit]]

    async def get_daily_quotes(
        self, market: str, code: str,
        start_date: Optional[str] = None, end_date: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """获取历史K线数据。"""
        coll = self._get_coll("daily_quotes", market)

        query: Dict = {"symbol": code}
        if start_date or end_date:
            query["trade_date"] = {}
            if start_date:
                query["trade_date"]["$gte"] = start_date
            if end_date:
                query["trade_date"]["$lte"] = end_date

        cursor = coll.find(query, {"_id": 0}).sort("trade_date", -1).limit(limit)
        docs = await cursor.to_list(length=limit)
        return [self._normalize_doc(doc) for doc in docs]

    async def get_cn_quote_with_basic_info(self, code6: str) -> Optional[Dict]:
        """获取 A 股实时行情（合并 market_quotes + stock_basic_info，按数据源优先级查询）。"""
        quotes_coll = self._get_coll("market_quotes", "CN")
        q = await quotes_coll.find_one({"symbol": code6}, {"_id": 0})

        enabled_sources = await self._get_source_priority("CN")
        if not enabled_sources:
            enabled_sources = ["tushare", "akshare", "baostock"]

        basic_info_coll = self._get_coll("basic_info", "CN")
        b = None
        for src in enabled_sources:
            b = await basic_info_coll.find_one({"symbol": code6, "data_source": src}, {"_id": 0})
            if b:
                break
        if not b:
            b = await basic_info_coll.find_one({"symbol": code6}, {"_id": 0})

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
        turnover_rate_date = None
        if turnover_rate is None:
            turnover_rate = (b or {}).get("turnover_rate")
            turnover_rate_date = (b or {}).get("trade_date")
        else:
            turnover_rate_date = (q or {}).get("trade_date")

        amplitude = None
        amplitude_date = None
        try:
            high = (q or {}).get("high")
            low = (q or {}).get("low")
            if high is not None and low is not None and prev_close is not None and prev_close > 0:
                amplitude = round((float(high) - float(low)) / float(prev_close) * 100, 2)
                amplitude_date = (q or {}).get("trade_date")
        except Exception:
            amplitude = None

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
            "turnover_rate_date": turnover_rate_date,
            "amplitude_date": amplitude_date,
            "trade_date": (q or {}).get("trade_date"),
            "updated_at": (q or {}).get("updated_at"),
            "data_source": (q or {}).get("data_source") or (b or {}).get("data_source"),
        }

    async def get_cn_fundamentals(
        self, code6: str, source: Optional[str] = None,
    ) -> Optional[Dict]:
        """获取 A 股基本面快照（stock_basic_info + stock_financial_data，按数据源优先级查询）。"""
        basic_info_coll = self._get_coll("basic_info", "CN")

        if source:
            b = await basic_info_coll.find_one({"symbol": code6, "data_source": source}, {"_id": 0})
            if not b:
                return None
        else:
            source_priority = ["tushare", "multi_source", "akshare", "baostock"]
            b = None
            for src in source_priority:
                b = await basic_info_coll.find_one({"symbol": code6, "data_source": src}, {"_id": 0})
                if b:
                    break
            if not b:
                b = await basic_info_coll.find_one({"symbol": code6}, {"_id": 0})
            if not b:
                return None

        financial_data = None
        try:
            enabled_sources = await self._get_source_priority("CN")
            if not enabled_sources:
                enabled_sources = ["tushare", "akshare", "baostock"]

            financial_coll = self._get_coll("financial_data", "CN")
            for data_source in enabled_sources:
                financial_data = await financial_coll.find_one(
                    {"symbol": code6, "data_source": data_source},
                    {"_id": 0},
                    sort=[("report_period", -1)],
                )
                if financial_data:
                    break
        except Exception as e:
            logger.warning(f"获取财务数据失败: {e}")

        realtime_metrics = {}
        try:
            from app.data.core.interface import DataInterface
            di = DataInterface.get_instance()
            result = await di.read("CN", code6, "daily_indicators")
            data = result.get("data")
            if data:
                latest = data[0] if isinstance(data, list) else data
                realtime_metrics = {
                    "pe": latest.get("pe_ttm"),
                    "pb": latest.get("pb"),
                    "pe_ttm": latest.get("pe_ttm"),
                    "market_cap": latest.get("total_mv"),
                    "source": "daily_indicators",
                    "is_realtime": False,
                    "updated_at": latest.get("updated_at"),
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
        """获取 market_quotes 原始记录（用于 K 线实时数据补充等场景）。"""
        # 默认查 CN 市场（向后兼容）
        coll = self._get_coll("market_quotes", "CN")
        doc = await coll.find_one({"symbol": code}, {"_id": 0})
        return self._normalize_doc(doc)

    async def get_supported_markets(self) -> List[Dict]:
        """获取支持的市场列表。"""
        from app.engine.config.runtime_settings import get_timezone_name

        return [
            {
                "code": "CN",
                "name": "A股",
                "name_en": "China A-Share",
                "currency": "CNY",
                "timezone": get_timezone_name(),
            },
            {
                "code": "HK",
                "name": "港股",
                "name_en": "Hong Kong Stock",
                "currency": "HKD",
                "timezone": "Asia/Hong_Kong",
            },
            {
                "code": "US",
                "name": "美股",
                "name_en": "US Stock",
                "currency": "USD",
                "timezone": "America/New_York",
            },
        ]
