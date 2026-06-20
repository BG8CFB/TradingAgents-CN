"""
增强的股票筛选服务
结合数据库优化和传统筛选方式，提供高效的股票筛选功能
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from app.models.screening import ScreeningCondition, BASIC_FIELDS_INFO
from app.services.database_screening_service import get_database_screening_service
from app.services.screening_service import ScreeningService, ScreeningParams

logger = logging.getLogger(__name__)

from app.services.enhanced_screening.utils import (  # noqa: E402 (intentional late import)
    analyze_conditions as _analyze_conditions_util,
    convert_conditions_to_traditional_format as _convert_to_traditional_util,
)
from app.core.database import get_mongo_db  # noqa: E402 (intentional late import)


class EnhancedScreeningService:
    """增强的股票筛选服务"""

    def __init__(self):
        self.db_service = get_database_screening_service()
        self.traditional_service = ScreeningService()

        # 支持数据库优化的字段
        self.db_supported_fields = set(BASIC_FIELDS_INFO.keys())

    async def screen_stocks(
        self,
        conditions: List[ScreeningCondition],
        market: str = "CN",
        date: Optional[str] = None,
        adj: str = "qfq",
        limit: int = 50,
        offset: int = 0,
        order_by: Optional[List[Dict[str, str]]] = None,
        use_database_optimization: bool = True
    ) -> Dict[str, Any]:
        """
        智能股票筛选

        Args:
            conditions: 筛选条件列表
            market: 市场
            date: 交易日期
            adj: 复权方式
            limit: 返回数量限制
            offset: 偏移量
            order_by: 排序条件
            use_database_optimization: 是否使用数据库优化

        Returns:
            Dict: 筛选结果
        """
        start_time = time.time()

        try:
            # 分析筛选条件
            analysis = self._analyze_conditions(conditions)

            # 决定使用哪种筛选方式
            if (use_database_optimization and
                analysis["can_use_database"] and
                not analysis["needs_technical_indicators"]):

                # 使用数据库优化筛选
                result = await self._screen_with_database(
                    conditions, limit, offset, order_by
                )
                optimization_used = "database"
                source = "mongodb"

            else:
                # 使用传统筛选方式
                result = await self._screen_with_traditional_method(
                    conditions, market, date, adj, limit, offset, order_by
                )
                optimization_used = "traditional"
                source = "api"

            # 提取 items/total
            items = result[0] if isinstance(result, tuple) else result.get("items", [])
            total = result[1] if isinstance(result, tuple) else result.get("total", 0)

            # 若使用数据库优化路径，则从数据库行情表进行富集（避免请求时外部调用）
            if source == "mongodb" and items:
                try:
                    db = get_mongo_db()
                    from app.data.storage.mongo.collections import get_collection_name
                    coll = db[get_collection_name("market_quotes", "CN")]
                    codes = [str(it.get("symbol")).zfill(6) for it in items if it.get("symbol")]
                    if codes:
                        cursor = coll.find(
                            {"symbol": {"$in": codes}},
                            projection={"_id": 0, "symbol": 1, "close": 1, "pct_chg": 1, "amount": 1},
                        )
                        quotes_list = await cursor.to_list(length=len(codes))
                        quotes_map = {}
                        for d in quotes_list:
                            k = str(d.get("symbol")).zfill(6)
                            quotes_map[k] = d
                        for it in items:
                            key = str(it.get("symbol")).zfill(6)
                            q = quotes_map.get(key)
                            if not q:
                                continue
                            if q.get("close") is not None:
                                it["close"] = q.get("close")
                            if q.get("pct_chg") is not None:
                                it["pct_chg"] = q.get("pct_chg")
                            if q.get("amount") is not None:
                                it["amount"] = q.get("amount")
                except Exception as enrich_err:
                    logger.warning(f"实时行情富集失败（已忽略）: {enrich_err}")

                # 回退：从 daily_quotes 补齐 pct_chg / close / amount
                missing_pct = [it for it in items if it.get("pct_chg") is None]
                if missing_pct:
                    try:
                        dq_coll = db[get_collection_name("daily_quotes", "CN")]
                        missing_codes = [str(it.get("symbol")).zfill(6) for it in missing_pct if it.get("symbol")]
                        if missing_codes:
                            pipeline = [
                                {"$match": {"symbol": {"$in": missing_codes}}},
                                {"$sort": {"trade_date": -1}},
                                {"$group": {
                                    "_id": "$symbol",
                                    "pct_chg": {"$first": "$pct_chg"},
                                    "close": {"$first": "$close"},
                                    "amount": {"$first": "$amount"},
                                }},
                            ]
                            dq_map = {}
                            async for doc in dq_coll.aggregate(pipeline):
                                k = str(doc.get("_id")).zfill(6)
                                dq_map[k] = doc
                            enriched = 0
                            for it in missing_pct:
                                key = str(it.get("symbol")).zfill(6)
                                dq = dq_map.get(key)
                                if not dq:
                                    continue
                                if it.get("pct_chg") is None and dq.get("pct_chg") is not None:
                                    it["pct_chg"] = dq["pct_chg"]
                                if it.get("close") is None and dq.get("close") is not None:
                                    it["close"] = dq["close"]
                                if it.get("amount") is None and dq.get("amount") is not None:
                                    it["amount"] = dq["amount"]
                                enriched += 1
                            logger.info(f"[screening] daily_quotes 回退补齐: {enriched}/{len(missing_pct)} 条")
                    except Exception as dq_err:
                        logger.warning(f"daily_quotes 回退补齐失败（已忽略）: {dq_err}")

            # 计算耗时
            took_ms = int((time.time() - start_time) * 1000)

            # 返回结果
            return {
                "total": total,
                "items": items,
                "took_ms": took_ms,
                "optimization_used": optimization_used,
                "source": source,
                "analysis": analysis
            }

        except Exception as e:
            logger.error(f"❌ 股票筛选失败: {e}")
            took_ms = int((time.time() - start_time) * 1000)

            return {
                "total": 0,
                "items": [],
                "took_ms": took_ms,
                "optimization_used": "none",
                "source": "error",
                "error": str(e)
            }

    def _analyze_conditions(self, conditions: List[ScreeningCondition]) -> Dict[str, Any]:
        """Delegate condition analysis to utils."""
        analysis = _analyze_conditions_util(conditions)
        logger.info(f"📊 筛选条件分析: {analysis}")
        return analysis

    async def _screen_with_database(
        self,
        conditions: List[ScreeningCondition],
        limit: int,
        offset: int,
        order_by: Optional[List[Dict[str, str]]]
    ) -> Tuple[List[Dict[str, Any]], int]:
        """使用数据库优化筛选"""
        logger.info("🚀 使用数据库优化筛选")

        return await self.db_service.screen_stocks(
            conditions=conditions,
            limit=limit,
            offset=offset,
            order_by=order_by
        )

    async def _screen_with_traditional_method(
        self,
        conditions: List[ScreeningCondition],
        market: str,
        date: Optional[str],
        adj: str,
        limit: int,
        offset: int,
        order_by: Optional[List[Dict[str, str]]]
    ) -> Dict[str, Any]:
        """使用传统筛选方法"""
        logger.info("🔄 使用传统筛选方法")

        # 转换条件格式为传统服务支持的格式
        traditional_conditions = self._convert_conditions_to_traditional_format(conditions)

        # 创建筛选参数
        params = ScreeningParams(
            market=market,
            date=date,
            adj=adj,
            limit=limit,
            offset=offset,
            order_by=order_by
        )

        # 执行传统筛选（在线程池中运行，避免同步 I/O 阻塞事件循环）
        result = await asyncio.to_thread(self.traditional_service.run, traditional_conditions, params)

        return result

    def _convert_conditions_to_traditional_format(
        self,
        conditions: List[ScreeningCondition]
    ) -> Dict[str, Any]:
        """Delegate condition conversion to utils."""
        return _convert_to_traditional_util(conditions)

    async def get_industries(self) -> Dict[str, Any]:
        """
        获取数据库中所有可用的行业列表

        按数据源优先级逐一尝试：从优先级最高的源聚合行业数据，
        若该源无有效行业（全空或结果为空），自动回退到下一个源。
        过滤掉 None / 空字符串 / NaN 等无效行业值。
        """
        try:
            from app.data.core.registry.priority import PriorityConfig

            db = get_mongo_db()
            from app.data.storage.mongo.collections import get_collection_name
            collection = db[get_collection_name("basic_info", "CN")]

            pc = PriorityConfig()
            enabled_sources = await pc.get_priority("CN", "basic_info")
            logger.info(f"[get_industries] 数据源优先级: {enabled_sources}")

            # 通用聚合管道：按源查询，过滤无效行业值
            def _build_pipeline(source: str) -> list:
                return [
                    {"$match": {
                        "data_source": source,
                        "industry": {"$nin": [None, "", float("nan")]},
                    }},
                    {"$group": {"_id": "$industry", "count": {"$sum": 1}}},
                    {"$sort": {"count": -1}},
                    {"$project": {"industry": "$_id", "count": 1, "_id": 0}},
                ]

            def _safe_str(raw) -> str:
                if raw is None:
                    return ""
                if isinstance(raw, float):
                    if raw != raw or raw in (float("inf"), float("-inf")):
                        return ""
                return str(raw).strip()

            def _safe_int(raw) -> int:
                try:
                    if isinstance(raw, float):
                        if raw != raw or raw in (float("inf"), float("-inf")):
                            return 0
                    return int(raw)
                except Exception as e:
                    logger.debug(f"转换筛选值失败: {e}")
                    return 0

            # 按优先级逐一尝试各数据源
            used_source = None
            for src in enabled_sources:
                pipeline = _build_pipeline(src)
                industries = []
                async for doc in collection.aggregate(pipeline):
                    name = _safe_str(doc.get("industry"))
                    if not name:
                        continue
                    industries.append({
                        "value": name,
                        "label": name,
                        "count": _safe_int(doc.get("count", 0)),
                    })
                if industries:
                    used_source = src
                    logger.info(f"[get_industries] 从数据源 {src} 返回 {len(industries)} 个行业")
                    return {
                        "industries": industries,
                        "total": len(industries),
                        "source": used_source,
                    }
                logger.info(f"[get_industries] 数据源 {src} 无有效行业数据，尝试下一个")

            # 所有数据源均无行业数据
            logger.warning("[get_industries] 所有数据源均无有效行业数据")
            return {"industries": [], "total": 0, "source": "none"}

        except Exception as e:
            logger.error(f"[get_industries] 获取行业列表失败: {e}", exc_info=True)
            raise


# 全局服务实例
_enhanced_screening_service: Optional[EnhancedScreeningService] = None


def get_enhanced_screening_service() -> EnhancedScreeningService:
    """获取增强筛选服务实例"""
    global _enhanced_screening_service
    if _enhanced_screening_service is None:
        _enhanced_screening_service = EnhancedScreeningService()
    return _enhanced_screening_service
