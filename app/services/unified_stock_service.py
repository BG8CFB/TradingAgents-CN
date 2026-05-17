#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一股票数据服务（跨市场，支持多数据源）

功能：
1. 跨市场数据访问（A股/港股/美股）
2. 多数据源优先级查询
3. 统一的查询接口

设计说明：
- 参考A股多数据源设计
- 同一股票可有多个数据源记录
- 通过 (code, source) 联合查询
- 数据源优先级从数据库配置读取
"""

import logging
from typing import Dict, List, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.data.schema.collections import get_collection_name

logger = logging.getLogger("webapi")


class UnifiedStockService:
    """统一股票数据服务（跨市场，支持多数据源）"""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

        # 集合映射统一收敛到 schema/collections，避免多处重复维护。
        self.collection_map = {
            "CN": {
                "basic_info": get_collection_name("CN", "basic_info"),
                "quotes": get_collection_name("CN", "market_quotes"),
                "daily": get_collection_name("CN", "daily_quotes"),
                "financial": get_collection_name("CN", "financial"),
                "news": get_collection_name("CN", "news"),
            },
            "HK": {
                "basic_info": get_collection_name("HK", "basic_info"),
                "quotes": get_collection_name("HK", "market_quotes"),
                "daily": get_collection_name("HK", "daily_quotes"),
                "financial": get_collection_name("HK", "financial"),
                "news": get_collection_name("HK", "news"),
            },
            "US": {
                "basic_info": get_collection_name("US", "basic_info"),
                "quotes": get_collection_name("US", "market_quotes"),
                "daily": get_collection_name("US", "daily_quotes"),
                "financial": get_collection_name("US", "financial"),
                "news": get_collection_name("US", "news"),
            },
        }

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
        self, 
        market: str, 
        code: str, 
        source: Optional[str] = None
    ) -> Optional[Dict]:
        """
        获取股票基础信息（支持多数据源）
        
        Args:
            market: 市场类型 (CN/HK/US)
            code: 股票代码
            source: 指定数据源（可选）
        
        Returns:
            股票基础信息字典
        """
        collection_name = self.collection_map[market]["basic_info"]
        collection = self.db[collection_name]
        
        if source:
            # 指定数据源
            query = {"symbol": code, "data_source": source}
            doc = await collection.find_one(query, {"_id": 0})
            if doc:
                logger.debug(f"✅ 使用指定数据源: {source}")
        else:
            # 🔥 按优先级查询（参考A股设计）
            source_priority = await self._get_source_priority(market)
            doc = None
            
            for src in source_priority:
                query = {"symbol": code, "data_source": src}
                doc = await collection.find_one(query, {"_id": 0})
                if doc:
                    logger.debug(f"✅ 使用数据源: {src} (优先级查询)")
                    break
            
            # 如果没有找到，尝试不指定数据源查询。
            if not doc:
                doc = await collection.find_one({"symbol": code}, {"_id": 0})
                if doc:
                    logger.debug("✅ 使用默认数据源")
        
        return self._normalize_doc(doc)

    async def _get_source_priority(self, market: str) -> List[str]:
        """
        从数据库获取数据源优先级
        
        Args:
            market: 市场类型 (CN/HK/US)
        
        Returns:
            数据源优先级列表
        """
        market_category_map = {
            "CN": "a_shares",
            "HK": "hk_stocks",
            "US": "us_stocks"
        }
        
        market_category_id = market_category_map.get(market)
        
        try:
            # 从 datasource_groupings 集合查询
            groupings = await self.db.datasource_groupings.find({
                "market_category_id": market_category_id,
                "enabled": True
            }).sort("priority", -1).to_list(length=None)
            
            if groupings:
                priority_list = [g["data_source_name"] for g in groupings]
                logger.debug(f"📊 {market} 数据源优先级（从数据库）: {priority_list}")
                return priority_list
        except Exception as e:
            logger.warning(f"⚠️ 从数据库读取数据源优先级失败: {e}")
        
        # 默认优先级
        default_priority = {
            "CN": ["tushare", "akshare", "baostock"],
            "HK": ["yfinance_hk", "akshare_hk"],
            "US": ["yfinance_us"]
        }
        priority_list = default_priority.get(market, [])
        logger.debug(f"📊 {market} 数据源优先级（默认）: {priority_list}")
        return priority_list

    async def get_stock_quote(self, market: str, code: str) -> Optional[Dict]:
        """
        获取实时行情
        
        Args:
            market: 市场类型 (CN/HK/US)
            code: 股票代码
        
        Returns:
            实时行情字典
        """
        collection_name = self.collection_map[market]["quotes"]
        collection = self.db[collection_name]
        doc = await collection.find_one({"symbol": code}, {"_id": 0})
        return self._normalize_doc(doc)

    async def search_stocks(
        self, 
        market: str, 
        query: str, 
        limit: int = 20
    ) -> List[Dict]:
        """
        搜索股票（去重，只返回每个股票的最优数据源）
        
        Args:
            market: 市场类型 (CN/HK/US)
            query: 搜索关键词
            limit: 返回数量限制
        
        Returns:
            股票列表
        """
        collection_name = self.collection_map[market]["basic_info"]
        collection = self.db[collection_name]

        # 支持代码和名称搜索
        filter_query = {
            "$or": [
                {"symbol": {"$regex": query, "$options": "i"}},
                {"name": {"$regex": query, "$options": "i"}},
                {"name_en": {"$regex": query, "$options": "i"}},
                {"full_symbol": {"$regex": query, "$options": "i"}},
            ]
        }

        # 查询所有匹配的记录
        cursor = collection.find(filter_query)
        all_results = await cursor.to_list(length=None)
        
        if not all_results:
            return []
        
        # 按 symbol 分组，每个 symbol 只保留优先级最高的数据源
        source_priority = await self._get_source_priority(market)
        unique_results = {}
        
        for doc in all_results:
            symbol = doc.get("symbol")
            source = doc.get("data_source")
            
            if not symbol:
                continue

            if symbol not in unique_results:
                unique_results[symbol] = doc
            else:
                # 比较优先级
                current_source = unique_results[symbol].get("data_source")
                try:
                    if source in source_priority and current_source in source_priority:
                        if source_priority.index(source) < source_priority.index(current_source):
                            unique_results[symbol] = doc
                except ValueError:
                    # 如果source不在优先级列表中，保持当前记录
                    pass
        
        # 返回前 limit 条
        result_list = [self._normalize_doc(doc) for doc in list(unique_results.values())[:limit]]
        logger.info(f"🔍 搜索 {market} 市场: '{query}' -> {len(result_list)} 条结果（已去重）")
        return result_list

    async def get_daily_quotes(
        self,
        market: str,
        code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        获取历史K线数据
        
        Args:
            market: 市场类型 (CN/HK/US)
            code: 股票代码
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            limit: 返回数量限制
        
        Returns:
            K线数据列表
        """
        collection_name = self.collection_map[market]["daily"]
        collection = self.db[collection_name]
        
        query = {"symbol": code}
        if start_date or end_date:
            query["trade_date"] = {}
            if start_date:
                query["trade_date"]["$gte"] = start_date
            if end_date:
                query["trade_date"]["$lte"] = end_date
        
        cursor = collection.find(query, {"_id": 0}).sort("trade_date", -1).limit(limit)
        docs = await cursor.to_list(length=limit)
        return [self._normalize_doc(doc) for doc in docs]

    async def get_cn_quote_with_basic_info(self, code6: str) -> Optional[Dict]:
        """
        获取 A 股实时行情（合并 market_quotes + stock_basic_info，按数据源优先级查询）。

        Args:
            code6: 6位股票代码

        Returns:
            合并后的行情 + 基础信息字典，或 None。
        """
        # 行情
        quotes_coll = self.db["market_quotes"]
        q = await quotes_coll.find_one({"symbol": code6}, {"_id": 0})

        # 基础信息 - 按数据源优先级查询
        enabled_sources = await self._get_source_priority("CN")
        if not enabled_sources:
            enabled_sources = ["tushare", "akshare", "baostock"]

        b = None
        basic_info_coll = self.db["stock_basic_info"]
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

        # 换手率：优先 market_quotes（实时），降级到 stock_basic_info（日度）
        turnover_rate = (q or {}).get("turnover_rate")
        turnover_rate_date = None
        if turnover_rate is None:
            turnover_rate = (b or {}).get("turnover_rate")
            turnover_rate_date = (b or {}).get("trade_date")
        else:
            turnover_rate_date = (q or {}).get("trade_date")

        # 振幅
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
        self,
        code6: str,
        source: Optional[str] = None,
    ) -> Optional[Dict]:
        """
        获取 A 股基本面快照（stock_basic_info + stock_financial_data，按数据源优先级查询）。

        Args:
            code6: 6位股票代码
            source: 指定数据源（可选）

        Returns:
            包含基础信息、估值指标、财务指标的字典，或 None。
        """
        basic_info_coll = self.db["stock_basic_info"]

        # 1. 获取基础信息
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

        # 2. 财务数据（按数据源优先级查询）
        financial_data = None
        try:
            enabled_sources = await self._get_source_priority("CN")
            if not enabled_sources:
                enabled_sources = ["tushare", "akshare", "baostock"]

            financial_coll = self.db["stock_financial_data"]
            for data_source in enabled_sources:
                financial_data = await financial_coll.find_one(
                    {"symbol": code6, "data_source": data_source},
                    {"_id": 0},
                    sort=[("report_period", -1)],
                )
                if financial_data:
                    break
        except Exception as e:
            logger.warning(f"⚠️ 获取财务数据失败: {e}")

        # 3. 实时 PE/PB
        realtime_metrics = {}
        try:
            from app.data.realtime_metrics import get_pe_pb_with_fallback
            import asyncio
            realtime_metrics = await asyncio.to_thread(
                get_pe_pb_with_fallback,
                code6,
                self.db.client,
            )
        except Exception as e:
            logger.warning(f"⚠️ 获取实时PE/PB失败: {e}")

        # 4. 构建返回数据
        realtime_market_cap = realtime_metrics.get("market_cap")
        total_mv = realtime_market_cap if realtime_market_cap else b.get("total_mv")

        data = {
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

        # 5. 从财务数据中提取 ROE、负债率、PS
        if financial_data:
            if financial_data.get("financial_indicators"):
                indicators = financial_data["financial_indicators"]
                data["roe"] = indicators.get("roe")
                data["debt_ratio"] = indicators.get("debt_to_assets")
            if data["roe"] is None:
                data["roe"] = financial_data.get("roe")
            if data["debt_ratio"] is None:
                data["debt_ratio"] = financial_data.get("debt_to_assets")

            revenue_ttm = financial_data.get("revenue_ttm")
            revenue = financial_data.get("revenue")
            revenue_for_ps = revenue_ttm if revenue_ttm and revenue_ttm > 0 else revenue

            if revenue_for_ps and revenue_for_ps > 0 and total_mv and total_mv > 0:
                revenue_yi = revenue_for_ps / 100000000
                ps_calculated = total_mv / revenue_yi
                data["ps"] = round(ps_calculated, 2)
                data["ps_ttm"] = round(ps_calculated, 2) if revenue_ttm else None

        if data["roe"] is None:
            data["roe"] = b.get("roe")

        return data

    async def get_market_quotes_raw(self, code: str) -> Optional[Dict]:
        """
        获取 market_quotes 原始记录（用于 K 线实时数据补充等场景）。

        Args:
            code: 股票代码

        Returns:
            market_quotes 文档字典，或 None。
        """
        quotes_coll = self.db["market_quotes"]
        doc = await quotes_coll.find_one({"symbol": code}, {"_id": 0})
        return self._normalize_doc(doc)

    async def get_supported_markets(self) -> List[Dict]:
        """
        获取支持的市场列表

        Returns:
            市场列表
        """
        from app.engine.config.runtime_settings import get_timezone_name

        return [
            {
                "code": "CN",
                "name": "A股",
                "name_en": "China A-Share",
                "currency": "CNY",
                "timezone": get_timezone_name()
            },
            {
                "code": "HK",
                "name": "港股",
                "name_en": "Hong Kong Stock",
                "currency": "HKD",
                "timezone": "Asia/Hong_Kong"
            },
            {
                "code": "US",
                "name": "美股",
                "name_en": "US Stock",
                "currency": "USD",
                "timezone": "America/New_York"
            }
        ]

