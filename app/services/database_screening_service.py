"""
基于MongoDB的股票筛选服务（内部实现，请勿直接调用）

四阶段跨集合查询架构：
  阶段1: stock_daily_indicators — 筛选 pe/pb/total_mv/turnover_rate 等指标字段
  阶段2: stock_basic_info       — 获取 name/industry/exchange 等基本信息
  阶段3: market_quotes          — 获取 close/pct_chg/amount 等实时行情
  阶段4: stock_financial_data   — 获取 roe 等财务指标（按 report_period 最新季度）

对外接口请使用 app.services.enhanced_screening_service.EnhancedScreeningService
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.core.database import get_mongo_db
from app.data.storage.mongo.collections import get_collection_name

logger = logging.getLogger(__name__)

# ── 字段分类 ──

# stock_basic_info 集合中的字段（基本信息 + 字符串匹配）
_BASIC_INFO_FIELDS = {
    "symbol", "code", "name", "industry", "area", "market", "list_date",
}

# stock_daily_indicators 集合中的字段（每日指标，按 symbol + trade_date 存储）
_INDICATOR_FIELDS = {
    "total_mv", "circ_mv", "market_cap",
    "pe", "pb", "pe_ttm", "pb_mrq",
    "turnover_rate", "volume_ratio",
    "roe",
}

# market_quotes 集合中的字段（实时/准实时行情）
_QUOTE_FIELDS = {
    "pct_chg", "amount", "close", "volume",
}

# 前端字段名 → indicators 集合字段名映射（处理别名）
_INDICATOR_FIELD_MAP = {
    "total_mv": "total_mv",
    "circ_mv": "circ_mv",
    "market_cap": "total_mv",
    "pe": "pe_ttm",          # 前端 pe → 数据库 pe_ttm
    "pb": "pb",
    "pe_ttm": "pe_ttm",
    "pb_mrq": "pb_mrq",
    "turnover_rate": "turnover_rate",
    "volume_ratio": "volume_ratio",
    "roe": "roe",
}


class DatabaseScreeningService:
    """基于数据库的股票筛选服务（三阶段跨集合查询）"""

    # 合并所有支持的字段（供 can_handle_conditions 检查）
    _ALL_SUPPORTED_FIELDS = _BASIC_INFO_FIELDS | _INDICATOR_FIELDS | _QUOTE_FIELDS

    # 支持的操作符 → MongoDB 操作符
    _OPERATORS = {
        ">": "$gt",
        "<": "$lt",
        ">=": "$gte",
        "<=": "$lte",
        "==": "$eq",
        "!=": "$ne",
        "in": "$in",
        "not_in": "$nin",
        "contains": "$regex",
    }

    async def _resolve_preferred_source(self) -> str:
        from app.data.core.registry.priority import PriorityConfig
        pc = PriorityConfig()
        enabled_sources = await pc.get_priority("CN", "basic_info")
        return enabled_sources[0] if enabled_sources else "tushare"

    async def can_handle_conditions(self, conditions: List[Dict[str, Any]]) -> bool:
        for condition in conditions:
            field = condition.get("field") if isinstance(condition, dict) else condition.field
            operator = condition.get("operator") if isinstance(condition, dict) else condition.operator
            if field not in self._ALL_SUPPORTED_FIELDS:
                logger.debug(f"字段 {field} 不支持数据库筛选")
                return False
            if operator not in self._OPERATORS and operator != "between":
                logger.debug(f"操作符 {operator} 不支持数据库筛选")
                return False
        return True

    async def screen_stocks(
        self,
        conditions: List[Dict[str, Any]],
        limit: int = 50,
        offset: int = 0,
        order_by: Optional[List[Dict[str, str]]] = None,
        source: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        三阶段跨集合筛选。

        阶段1: daily_indicators — 聚合筛选，取每只股票最新一行，过滤指标条件
        阶段2: basic_info       — 按 symbol 列表批量获取基本信息
        阶段3: market_quotes    — 按 symbol 列表批量获取实时行情
        """
        try:
            db = get_mongo_db()
            if not source:
                source = await self._resolve_preferred_source()
            logger.info(f"[database_screening] 使用数据源: {source}")

            # 按集合拆分条件
            basic_conds, indicator_conds, quote_conds = self._classify_conditions(conditions)
            basic_coll = db[get_collection_name("basic_info", "CN")]
            indicator_coll = db[get_collection_name("daily_indicators", "CN")]

            # ── 阶段1: 按条件类型获取 symbol 列表，最后求交集 ──
            matched_symbols: Optional[List[str]] = None

            # 1a: indicator 条件过滤
            if indicator_conds:
                indicator_symbols = await self._query_indicators(
                    indicator_coll, indicator_conds, source
                )
                matched_symbols = indicator_symbols
                logger.info(f"[阶段1a] indicators 匹配 {len(indicator_symbols)} 只股票")

            # 1b: basic_info 字符串条件过滤
            if basic_conds:
                basic_symbols = await self._query_basic_info(basic_coll, basic_conds, source)
                logger.info(f"[阶段1b] basic_info 匹配 {len(basic_symbols)} 只股票")
                if matched_symbols is not None:
                    # 取交集
                    basic_set = set(basic_symbols)
                    matched_symbols = [s for s in matched_symbols if s in basic_set]
                else:
                    matched_symbols = basic_symbols

            # 如果没有任何匹配，直接返回空
            if matched_symbols is not None and len(matched_symbols) == 0:
                logger.info("[database_screening] 无匹配股票，返回空")
                return [], 0

            # ── 阶段2: basic_info 批量获取基本信息 ──
            basic_map = await self._fetch_basic_info(basic_coll, matched_symbols, source)
            logger.info(f"[阶段2] basic_info 获取 {len(basic_map)} 条记录")

            # 阶段2完成后确定最终 symbol 列表（无条件时用 basic_map 的 keys）
            final_symbols = matched_symbols if matched_symbols is not None else list(basic_map.keys())

            # ── 阶段3: market_quotes 获取行情 ──
            quotes_coll = db[get_collection_name("market_quotes", "CN")]
            quotes_map = await self._fetch_quotes(quotes_coll, final_symbols, quote_conds)
            logger.info(f"[阶段3] market_quotes 获取 {len(quotes_map)} 条记录")

            # ── 阶段3.5: daily_indicators 获取最新指标 ──
            indicators_map = await self._fetch_latest_indicators(indicator_coll, final_symbols, source)
            logger.info(f"[阶段3.5] daily_indicators 获取 {len(indicators_map)} 条记录")

            # ── 阶段4: financial_data 获取 ROE 等财务指标 ──
            financial_coll = db[get_collection_name("financial_data", "CN")]
            roe_map = await self._fetch_latest_roe(financial_coll, final_symbols, source)
            logger.info(f"[阶段4] financial_data ROE 获取 {len(roe_map)} 条记录")

            # ── 合并结果 ──
            results = self._merge_results(
                final_symbols, basic_map, indicators_map, quotes_map, source, roe_map
            )

            # ── 排序 ──
            results = self._sort_results(results, order_by)

            # ── 分页 ──
            total_count = len(results)
            page_items = results[offset: offset + limit]

            logger.info(
                f"[database_screening] 完成: total={total_count}, "
                f"返回={len(page_items)}, 数据源={source}"
            )
            return page_items, total_count

        except Exception as e:
            logger.error(f"[database_screening] 筛选失败: {e}", exc_info=True)
            raise RuntimeError(f"数据库筛选失败: {str(e)}") from e

    # ── 条件分类 ──

    def _classify_conditions(
        self, conditions: List[Dict[str, Any]]
    ) -> Tuple[List[Dict], List[Dict], List[Dict]]:
        """将条件按目标集合分为三类。"""
        basic_conds, indicator_conds, quote_conds = [], [], []
        for cond in conditions:
            field = cond.get("field") if isinstance(cond, dict) else cond.field
            if field in _BASIC_INFO_FIELDS:
                basic_conds.append(cond)
            elif field in _INDICATOR_FIELDS:
                indicator_conds.append(cond)
            elif field in _QUOTE_FIELDS:
                quote_conds.append(cond)
            else:
                logger.warning(f"未知字段 {field}，归入 indicator 条件")
                indicator_conds.append(cond)
        return basic_conds, indicator_conds, quote_conds

    # ── 阶段1: indicators 聚合查询 ──

    async def _query_indicators(
        self, coll, conditions: List[Dict], source: str
    ) -> Optional[List[str]]:
        """
        从 daily_indicators 聚合查询，取每只股票最新一行的数据，
        然后应用指标筛选条件，返回匹配的 symbol 列表。

        无指标条件时返回 None（表示不过滤）。
        """
        if not conditions:
            return None

        # 构建 $match 阶段：在 $group 之后应用筛选
        match_doc = self._build_indicator_match(conditions)

        pipeline = [
            {"$match": {"data_source": source}},
            {"$sort": {"symbol": 1, "trade_date": -1}},
            {"$group": {
                "_id": "$symbol",
                "symbol": {"$first": "$symbol"},
                "trade_date": {"$first": "$trade_date"},
                "pe_ttm": {"$first": "$pe_ttm"},
                "pb": {"$first": "$pb"},
                "total_mv": {"$first": "$total_mv"},
                "circ_mv": {"$first": "$circ_mv"},
                "turnover_rate": {"$first": "$turnover_rate"},
                "volume_ratio": {"$first": "$volume_ratio"},
                "roe": {"$first": "$roe"},
            }},
            {"$match": match_doc},
            {"$project": {"symbol": 1, "_id": 0}},
        ]

        symbols = []
        async for doc in coll.aggregate(pipeline):
            s = doc.get("symbol")
            if s:
                symbols.append(s)
        return symbols

    def _build_indicator_match(self, conditions: List[Dict]) -> Dict[str, Any]:
        """将筛选条件转换为 indicators 聚合后的 $match 文档。

        注意: total_mv 在数据库中以元为单位存储，而经过 router 转换后的条件值
        单位为亿元，因此需要对 total_mv 条件的值乘以 1e8 转换为元。
        """
        match: Dict[str, Any] = {}
        for cond in conditions:
            field = cond.get("field") if isinstance(cond, dict) else cond.field
            operator = cond.get("operator") if isinstance(cond, dict) else cond.operator
            value = cond.get("value") if isinstance(cond, dict) else cond.value

            db_field = _INDICATOR_FIELD_MAP.get(field, field)

            # total_mv 单位转换：router 传入的是亿元，数据库存储为元
            if db_field == "total_mv" and value is not None:
                if isinstance(value, list):
                    value = [v * 1e8 if isinstance(v, (int, float)) else v for v in value]
                elif isinstance(value, (int, float)):
                    value = value * 1e8

            self._apply_condition(match, db_field, operator, value)
        return match

    # ── 阶段1.5: basic_info 字符串条件过滤 ──

    async def _query_basic_info(
        self, coll, conditions: List[Dict], source: str
    ) -> Optional[List[str]]:
        """按 basic_info 字段过滤 symbol 列表。"""
        if not conditions:
            return None

        query: Dict[str, Any] = {"data_source": source}
        for cond in conditions:
            field = cond.get("field") if isinstance(cond, dict) else cond.field
            operator = cond.get("operator") if isinstance(cond, dict) else cond.operator
            value = cond.get("value") if isinstance(cond, dict) else cond.value

            # code → symbol 映射
            db_field = "symbol" if field == "code" else field
            self._apply_condition(query, db_field, operator, value)

        symbols = []
        cursor = coll.find(query, {"symbol": 1, "_id": 0})
        async for doc in cursor:
            s = doc.get("symbol")
            if s:
                symbols.append(s)
        return symbols

    # ── 阶段2: 批量获取 basic_info ──

    async def _fetch_basic_info(
        self, coll, symbols: Optional[List[str]], source: str
    ) -> Dict[str, Dict]:
        """批量获取基本信息，返回 {symbol: doc}。"""
        query: Dict[str, Any] = {"data_source": source}
        if symbols is not None:
            query["symbol"] = {"$in": symbols}

        result_map: Dict[str, Dict] = {}
        cursor = coll.find(query, {"_id": 0})
        async for doc in cursor:
            s = doc.get("symbol")
            if s:
                result_map[s] = doc
        return result_map

    # ── 阶段3: 获取行情数据 ──

    async def _fetch_quotes(
        self, coll, symbols: Optional[List[str]],
        quote_conditions: List[Dict],
    ) -> Dict[str, Dict]:
        """获取行情数据，返回 {symbol: {close, pct_chg, amount, volume}}。"""
        if symbols is None:
            return {}

        query: Dict[str, Any] = {"symbol": {"$in": symbols}}
        cursor = coll.find(query, {"_id": 0})
        quotes_map: Dict[str, Dict] = {}
        async for doc in cursor:
            s = doc.get("symbol")
            if s:
                quotes_map[s] = {
                    "close": doc.get("close") or doc.get("last_price"),
                    "pct_chg": doc.get("pct_chg"),
                    "amount": doc.get("amount"),
                    "volume": doc.get("volume") or doc.get("last_volume"),
                }

        # 如果有行情筛选条件，过滤不满足的
        if quote_conditions:
            filtered: Dict[str, Dict] = {}
            for sym, qd in quotes_map.items():
                if self._check_quote_conditions(qd, quote_conditions):
                    filtered[sym] = qd
            return filtered

        return quotes_map

    def _check_quote_conditions(
        self, quote_data: Dict, conditions: List[Dict]
    ) -> bool:
        for cond in conditions:
            field = cond.get("field") if isinstance(cond, dict) else cond.field
            operator = cond.get("operator") if isinstance(cond, dict) else cond.operator
            value = cond.get("value") if isinstance(cond, dict) else cond.value
            fv = quote_data.get(field)
            if fv is None:
                return False
            if not self._compare(fv, operator, value):
                return False
        return True

    # ── 阶段3.5: 获取最新指标数据 ──

    async def _fetch_latest_indicators(
        self, coll, symbols: Optional[List[str]], source: str
    ) -> Dict[str, Dict]:
        """获取每只股票最新一天的指标数据，返回 {symbol: {total_mv, pe_ttm, pb, ...}}。"""
        if symbols is not None and not symbols:
            return {}

        match_stage: Dict[str, Any] = {"data_source": source}
        if symbols is not None:
            match_stage["symbol"] = {"$in": symbols}

        pipeline = [
            {"$match": match_stage},
            {"$sort": {"trade_date": -1}},
            {"$group": {
                "_id": "$symbol",
                "total_mv": {"$first": "$total_mv"},
                "circ_mv": {"$first": "$circ_mv"},
                "pe_ttm": {"$first": "$pe_ttm"},
                "pb": {"$first": "$pb"},
                "turnover_rate": {"$first": "$turnover_rate"},
                "volume_ratio": {"$first": "$volume_ratio"},
                "roe": {"$first": "$roe"},
            }},
        ]

        result_map: Dict[str, Dict] = {}
        async for doc in coll.aggregate(pipeline):
            s = doc.get("_id")
            if s:
                result_map[s] = {
                    "total_mv": doc.get("total_mv"),
                    "circ_mv": doc.get("circ_mv"),
                    "pe_ttm": doc.get("pe_ttm"),
                    "pb": doc.get("pb"),
                    "turnover_rate": doc.get("turnover_rate"),
                    "volume_ratio": doc.get("volume_ratio"),
                    "roe": doc.get("roe"),
                }
        return result_map

    # ── 阶段4: 获取最新 ROE ──

    async def _fetch_latest_roe(
        self, coll, symbols: Optional[List[str]], source: str
    ) -> Dict[str, float]:
        """从 stock_financial_data 获取每只股票最新季度的 ROE，返回 {symbol: roe}。"""
        if symbols is not None and not symbols:
            return {}

        match_stage: Dict[str, Any] = {
            "roe": {"$exists": True, "$ne": None},
        }
        if symbols is not None:
            match_stage["symbol"] = {"$in": symbols}
        if source:
            match_stage["data_source"] = source

        pipeline = [
            {"$match": match_stage},
            {"$sort": {"report_period": -1}},
            {"$group": {
                "_id": "$symbol",
                "roe": {"$first": "$roe"},
            }},
        ]

        result_map: Dict[str, float] = {}
        async for doc in coll.aggregate(pipeline):
            s = doc.get("_id")
            if s:
                result_map[s] = doc.get("roe")
        return result_map

    # ── 结果合并 ──

    def _merge_results(
        self,
        symbols: Optional[List[str]],
        basic_map: Dict[str, Dict],
        indicators_map: Dict[str, Dict],
        quotes_map: Dict[str, Dict],
        source: str,
        roe_map: Optional[Dict[str, float]] = None,
    ) -> List[Dict[str, Any]]:
        """合并四阶段数据为统一格式。"""
        results: List[Dict[str, Any]] = []

        symbol_list = symbols if symbols is not None else list(basic_map.keys())

        for sym in symbol_list:
            bi = basic_map.get(sym, {})
            ind = indicators_map.get(sym, {})
            q = quotes_map.get(sym, {})

            # total_mv 单位转换：数据库存储为元，前端期望亿元
            raw_total_mv = ind.get("total_mv")
            raw_circ_mv = ind.get("circ_mv")
            total_mv_yi = round(raw_total_mv / 1e8, 2) if isinstance(raw_total_mv, (int, float)) else None
            circ_mv_yi = round(raw_circ_mv / 1e8, 2) if isinstance(raw_circ_mv, (int, float)) else None

            # ROE: 优先从 financial_data 获取，回退到 daily_indicators
            roe_value = None
            if roe_map:
                roe_value = roe_map.get(sym)
            if roe_value is None:
                roe_value = ind.get("roe")

            results.append({
                "symbol": sym,
                "name": bi.get("name"),
                "industry": bi.get("industry"),
                "area": bi.get("area"),
                "market": "A股",
                "board": bi.get("market"),
                "exchange": bi.get("exchange"),
                "list_date": bi.get("list_date"),

                "total_mv": total_mv_yi,
                "circ_mv": circ_mv_yi,
                "pe": ind.get("pe_ttm"),
                "pb": ind.get("pb"),
                "pe_ttm": ind.get("pe_ttm"),
                "pb_mrq": None,
                "roe": roe_value,
                "turnover_rate": ind.get("turnover_rate"),
                "volume_ratio": ind.get("volume_ratio"),

                "close": q.get("close"),
                "pct_chg": q.get("pct_chg"),
                "amount": q.get("amount"),
                "volume": q.get("volume"),

                "ma20": None,
                "rsi14": None,
                "kdj_k": None,
                "kdj_d": None,
                "kdj_j": None,
                "dif": None,
                "dea": None,
                "macd_hist": None,

                "data_source": source,
                "updated_at": bi.get("updated_at"),
            })

        return results

    # ── 排序 ──

    def _sort_results(
        self, results: List[Dict[str, Any]], order_by: Optional[List[Dict[str, str]]]
    ) -> List[Dict[str, Any]]:
        if not order_by:
            return results

        for order in reversed(order_by):
            field = order.get("field", "")
            direction = order.get("direction", "desc").lower()

            db_field = _INDICATOR_FIELD_MAP.get(field, field)
            # None 始终排最后：用 (is_none, signed_value) 保证
            # 升序: key=(is_none, value) -> None排后, 有值按升序
            # 降序: key=(is_none, -value) -> None排后, 有值按降序
            if direction == "desc":
                results.sort(
                    key=lambda x, _f=db_field: (
                        x.get(_f) is None,
                        -(x.get(_f) or 0),
                    ),
                )
            else:
                results.sort(
                    key=lambda x, _f=db_field: (
                        x.get(_f) is None,
                        x.get(_f) if x.get(_f) is not None else 0,
                    ),
                )
        return results

    # ── 统计 & 枚举 ──

    async def get_field_statistics(self, field: str) -> Dict[str, Any]:
        """获取字段统计信息。"""
        try:
            db = get_mongo_db()

            if field in _INDICATOR_FIELDS:
                db_field = _INDICATOR_FIELD_MAP.get(field, field)
                coll = db[get_collection_name("daily_indicators", "CN")]
                pipeline = [
                    {"$match": {db_field: {"$exists": True, "$ne": None}}},
                    {"$sort": {"trade_date": -1}},
                    {"$group": {
                        "_id": "$symbol",
                        db_field: {"$first": f"${db_field}"},
                    }},
                    {"$group": {
                        "_id": None,
                        "min": {"$min": f"${db_field}"},
                        "max": {"$max": f"${db_field}"},
                        "avg": {"$avg": f"${db_field}"},
                        "count": {"$sum": 1},
                    }},
                ]
            elif field in _BASIC_INFO_FIELDS:
                coll = db[get_collection_name("basic_info", "CN")]
                db_field = field if field != "code" else "symbol"
                pipeline = [
                    {"$match": {db_field: {"$exists": True, "$ne": None}}},
                    {"$group": {
                        "_id": None,
                        "min": {"$min": f"${db_field}"},
                        "max": {"$max": f"${db_field}"},
                        "avg": {"$avg": f"${db_field}"},
                        "count": {"$sum": 1},
                    }},
                ]
            else:
                return {}

            result = await coll.aggregate(pipeline).to_list(length=1)
            if result:
                stats = result[0]
                avg_value = stats.get("avg")
                return {
                    "field": field,
                    "min": stats.get("min"),
                    "max": stats.get("max"),
                    "avg": round(avg_value, 2) if isinstance(avg_value, (int, float)) else None,
                    "count": stats.get("count", 0),
                }
            return {"field": field, "count": 0}

        except Exception as e:
            logger.error(f"获取字段统计失败: {e}")
            return {"field": field, "error": str(e)}

    async def get_available_values(self, field: str, limit: int = 100) -> List[str]:
        """获取字段的可选值列表。"""
        try:
            if field in _BASIC_INFO_FIELDS:
                db = get_mongo_db()
                coll = db[get_collection_name("basic_info", "CN")]
                db_field = field if field != "code" else "symbol"
                values = await coll.distinct(db_field)
                values = [v for v in values if v is not None]
                values.sort()
                return values[:limit]
            return []
        except Exception as e:
            logger.error(f"获取字段可选值失败: {e}")
            return []

    # ── 通用条件构建 ──

    def _apply_condition(
        self, query: Dict[str, Any], db_field: str, operator: str, value: Any
    ) -> None:
        """将单个条件应用到 query 字典。"""
        if operator == "between":
            if isinstance(value, list) and len(value) == 2:
                if db_field in query:
                    query[db_field].update({"$gte": value[0], "$lte": value[1]})
                else:
                    query[db_field] = {"$gte": value[0], "$lte": value[1]}
        elif operator == "contains":
            if db_field in query:
                query[db_field].update({"$regex": str(value), "$options": "i"})
            else:
                query[db_field] = {"$regex": str(value), "$options": "i"}
        elif operator in self._OPERATORS:
            mongo_op = self._OPERATORS[operator]
            if db_field in query:
                query[db_field][mongo_op] = value
            else:
                query[db_field] = {mongo_op: value}

    @staticmethod
    def _compare(field_value: Any, operator: str, value: Any) -> bool:
        """比较单个值是否满足条件。"""
        try:
            if operator == "between" and isinstance(value, list) and len(value) == 2:
                return value[0] <= field_value <= value[1]
            elif operator == ">":
                return field_value > value
            elif operator == "<":
                return field_value < value
            elif operator == ">=":
                return field_value >= value
            elif operator == "<=":
                return field_value <= value
            elif operator == "==":
                return field_value == value
            elif operator == "!=":
                return field_value != value
            elif operator == "in":
                return isinstance(value, list) and field_value in value
            elif operator == "not_in":
                return isinstance(value, list) and field_value not in value
        except (TypeError, ValueError):
            return False
        return True


# 全局服务实例
_database_screening_service: Optional[DatabaseScreeningService] = None


def get_database_screening_service() -> DatabaseScreeningService:
    global _database_screening_service
    if _database_screening_service is None:
        _database_screening_service = DatabaseScreeningService()
    return _database_screening_service
