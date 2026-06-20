"""
分析报告服务层
从 app/routers/reports.py 中提取所有 MongoDB 操作，提供统一的数据访问接口
"""

import asyncio
import logging
import re
from collections import OrderedDict
from threading import Lock
from typing import Any, Dict, List, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.database import get_mongo_db, get_mongo_db_sync
from app.utils.timezone import now_utc, to_config_tz

logger = logging.getLogger("webapi")


# ---------------------------------------------------------------------------
# 股票名称缓存（模块级，与原 reports.py 一致）
# ---------------------------------------------------------------------------

_STOCK_NAME_CACHE_MAX_SIZE = 512
_stock_name_cache: "OrderedDict[str, str]" = OrderedDict()
_stock_name_cache_lock = Lock()


def _get_cached_stock_name(stock_code: str) -> Optional[str]:
    """读取缓存并刷新最近使用顺序。"""
    with _stock_name_cache_lock:
        cached_name = _stock_name_cache.get(stock_code)
        if cached_name is None:
            return None
        _stock_name_cache.move_to_end(stock_code)
        return cached_name


def _cache_stock_name(stock_code: str, stock_name: str) -> str:
    """写入缓存并在超过容量时淘汰最旧项。"""
    with _stock_name_cache_lock:
        _stock_name_cache[stock_code] = stock_name
        _stock_name_cache.move_to_end(stock_code)
        if len(_stock_name_cache) > _STOCK_NAME_CACHE_MAX_SIZE:
            _stock_name_cache.popitem(last=False)
    return stock_name


def _get_stock_name_sync(stock_code: str) -> str:
    """
    同步获取股票名称
    优先级：缓存 -> MongoDB（按数据源优先级） -> 默认返回股票代码
    """
    cached_name = _get_cached_stock_name(stock_code)
    if cached_name is not None:
        return cached_name

    try:
        from app.data.core.registry.priority import PriorityConfig

        db = get_mongo_db_sync()
        # 确认返回的是同步 PyMongo 数据库
        if db is None:
            return _cache_stock_name(stock_code, stock_code)

        code6 = str(stock_code).zfill(6)

        enabled_sources = PriorityConfig().get_default_sources("CN", "basic_info")

        stock_info = None
        for data_source in enabled_sources:
            result = db.stock_basic_info.find_one(
                {"symbol": code6, "data_source": data_source}
            )
            # 检查 result 不是 Motor coroutine
            if result is not None and not hasattr(result, '__await__'):
                stock_info = result
                logger.debug(f"使用数据源 {data_source} 获取股票名称 {code6}")
                break

        if not stock_info:
            result = db.stock_basic_info.find_one(
                {"symbol": code6}
            )
            if result is not None and not hasattr(result, '__await__'):
                stock_info = result

        if stock_info and stock_info.get("name"):
            return _cache_stock_name(stock_code, stock_info["name"])

        return _cache_stock_name(stock_code, stock_code)

    except Exception as e:
        logger.warning(f"获取股票名称失败 {stock_code}: {e}")
        return stock_code


async def _get_stock_name_async(stock_code: str) -> str:
    """在线程中执行同步股票名称查询，避免阻塞事件循环。"""
    return await asyncio.to_thread(_get_stock_name_sync, stock_code)


# ---------------------------------------------------------------------------
# 辅助：构建报告查询条件（支持 _id / analysis_id / task_id）
# ---------------------------------------------------------------------------

def _build_report_query(report_id: str) -> Dict[str, Any]:
    """构建支持多种 ID 格式的查询条件。"""
    ors: List[Dict[str, Any]] = [
        {"analysis_id": report_id},
        {"task_id": report_id},
    ]
    try:
        ors.append({"_id": ObjectId(report_id)})
    except Exception as e:
        logger.debug(f"ObjectId转换失败: {e}")
        pass
    return {"$or": ors}


# ---------------------------------------------------------------------------
# 辅助：从 state 中动态提取报告模块
# ---------------------------------------------------------------------------

# 已知的非 *_report 后缀的报告字段名
_KNOWN_REPORT_KEYS = {
    "bull_researcher", "bear_researcher", "research_team_decision",
    "trader_investment_plan",
    "risky_analyst", "safe_analyst", "neutral_analyst", "risk_management_decision", "risk_manager_decision",
}


def _extract_reports_from_state(state: Dict[str, Any]) -> Dict[str, str]:
    """动态发现 state 中所有报告字段并提取内容。"""
    reports: Dict[str, str] = {}
    if not isinstance(state, dict):
        return reports

    for key in state.keys():
        if key.endswith("_report") or key in _KNOWN_REPORT_KEYS:
            content = state[key]
            if content:
                if isinstance(content, str):
                    reports[key] = content
                elif hasattr(content, "content") and isinstance(content.content, str):
                    reports[key] = content.content
                else:
                    try:
                        reports[key] = str(content)
                    except Exception as e:
                        logger.debug(f"读取报告内容失败: {e}")
                        pass
    return reports


# ---------------------------------------------------------------------------
# 辅助：提取结构化摘要中的置信度、风险等级、投资建议
# ---------------------------------------------------------------------------

_RISK_LEVEL_MAP = {"High": "高", "Medium": "中等", "Low": "低"}


def _extract_structured_fields(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    从文档中提取结构化总结相关的字段，优先使用 structured_summary 中的值。
    返回包含 confidence_score / risk_level / recommendation / summary 的字典。
    """
    structured_summary = doc.get("structured_summary") or {}

    confidence_score = doc.get("confidence_score", 0.0)
    risk_level = doc.get("risk_level", "中等")
    recommendation = doc.get("recommendation", "")
    summary = doc.get("summary", "")

    if structured_summary:
        if structured_summary.get("model_confidence"):
            confidence_score = structured_summary.get("model_confidence", 0) / 100.0
        if structured_summary.get("risk_assessment", {}).get("level"):
            risk_level = _RISK_LEVEL_MAP.get(
                structured_summary.get("risk_assessment", {}).get("level", "Medium"),
                "中等"
            )
        if structured_summary.get("investment_recommendation"):
            recommendation = structured_summary.get("investment_recommendation", "")
        if structured_summary.get("analysis_summary") and not summary:
            summary = structured_summary.get("analysis_summary", "")

    return {
        "confidence_score": confidence_score,
        "risk_level": risk_level,
        "recommendation": recommendation,
        "summary": summary,
        "structured_summary": structured_summary,
    }


# ---------------------------------------------------------------------------
# 辅助：推断市场类型
# ---------------------------------------------------------------------------

def _infer_market_type(stock_code: str) -> str:
    """根据股票代码推断市场类型。"""
    try:
        from app.utils.stock_utils import StockUtils
        market_info = StockUtils.get_market_info(stock_code)
        market_type_map = {
            "china_a": "A股",
            "hong_kong": "港股",
            "us": "美股",
            "unknown": "A股"
        }
        return market_type_map.get(market_info.get("market", "unknown"), "A股")
    except Exception as e:
        logger.debug(f"获取市场类型失败: {e}")
        return "A股"


# ===================================================================
# ReportsService
# ===================================================================

class ReportsService:
    """
    分析报告服务
    封装所有与 analysis_reports / analysis_tasks / stock_basic_info 集合的数据库操作。
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------

    async def list_reports(
        self,
        filters: Optional[Dict[str, Any]] = None,
        page: int = 1,
        page_size: int = 20,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        分页获取分析报告列表。

        Args:
            filters: 可选的筛选条件字典，支持以下键：
                - search_keyword: 搜索关键词（匹配 stock_symbol / analysis_id / summary）
                - market_filter: 市场类型筛选（A股 / 港股 / 美股）
                - start_date: 开始日期
                - end_date: 结束日期
                - stock_code: 股票代码精确筛选
            page: 页码（从 1 开始）
            page_size: 每页数量
            user_id: 可选的用户 ID 筛选

        Returns:
            {"reports": [...], "total": int, "page": int, "page_size": int}
        """
        query = self._build_list_query(filters or {}, user_id)

        total = await self.db.analysis_reports.count_documents(query)

        skip = (page - 1) * page_size
        cursor = (
            self.db.analysis_reports
            .find(query)
            .sort("created_at", -1)
            .skip(skip)
            .limit(page_size)
        )

        reports = []
        async for doc in cursor:
            report = await self._format_report_list_item(doc)
            reports.append(report)

        return {
            "reports": reports,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get_report(self, report_id: str) -> Optional[Dict[str, Any]]:
        """
        获取单个报告详情。

        支持通过 ObjectId / analysis_id / task_id 查找。
        若 analysis_reports 中未找到，则尝试从 analysis_tasks 中还原。

        Returns:
            格式化后的报告字典，或 None
        """
        query = _build_report_query(report_id)
        doc = await self.db.analysis_reports.find_one(query)

        if doc:
            return await self._format_report_detail_from_reports_collection(doc)

        # 兜底：从 analysis_tasks 中还原
        return await self._restore_report_from_tasks(report_id)

    async def get_report_by_task_id(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        通过 task_id 查找报告。
        先在 analysis_reports 中查找，若找不到则在 analysis_tasks 中查找。

        Returns:
            格式化后的报告字典，或 None
        """
        # 先在 reports 集合中按 task_id 查找
        doc = await self.db.analysis_reports.find_one({"task_id": task_id})
        if doc:
            return await self._format_report_detail_from_reports_collection(doc)

        # 兜底：从 tasks 集合中查找
        return await self._restore_report_from_tasks(task_id)

    async def delete_report(
        self,
        report_id: str,
        user_id: Optional[str] = None,
    ) -> bool:
        """
        删除报告。
        若提供 user_id，可做所有权校验（当前实现为可选）。

        Returns:
            是否删除成功
        """
        query = _build_report_query(report_id)
        result = await self.db.analysis_reports.delete_one(query)
        return result.deleted_count > 0

    async def get_report_stats(self) -> Dict[str, Any]:
        """
        获取报告统计信息。
        使用聚合管道统计各市场类型的报告数量和总数。

        Returns:
            {"total": int, "by_market": {市场类型: 数量}, ...}
        """
        # 按市场类型分组统计
        pipeline = [
            {
                "$group": {
                    "_id": "$market_type",
                    "count": {"$sum": 1},
                }
            }
        ]

        by_market: Dict[str, int] = {}
        total = 0
        async for group_doc in self.db.analysis_reports.aggregate(pipeline):
            market = group_doc["_id"] or "未知"
            count = group_doc["count"]
            by_market[market] = count
            total += count

        # 补充未分类（没有 market_type 字段）的数量
        no_market_count = await self.db.analysis_reports.count_documents(
            {"market_type": {"$exists": False}}
        )
        if no_market_count > 0 and "未知" not in by_market:
            by_market["未知"] = no_market_count

        # 最近报告数量（最近 7 天 / 30 天）
        now = now_utc()
        from datetime import timedelta
        seven_days_ago = now - timedelta(days=7)
        thirty_days_ago = now - timedelta(days=30)

        last_7_days = await self.db.analysis_reports.count_documents(
            {"created_at": {"$gte": seven_days_ago}}
        )
        last_30_days = await self.db.analysis_reports.count_documents(
            {"created_at": {"$gte": thirty_days_ago}}
        )

        return {
            "total": total,
            "by_market": by_market,
            "last_7_days": last_7_days,
            "last_30_days": last_30_days,
        }

    async def download_report(self, report_id: str) -> Optional[Dict[str, Any]]:
        """
        获取报告完整数据用于下载。

        Returns:
            原始报告文档字典（ObjectId 已转为字符串），或 None
        """
        query = _build_report_query(report_id)
        doc = await self.db.analysis_reports.find_one(query)

        if not doc:
            return None

        # 序列化 ObjectId
        if "_id" in doc:
            doc["_id"] = str(doc["_id"])

        return doc

    # ------------------------------------------------------------------
    # 私有方法：查询构建
    # ------------------------------------------------------------------

    def _build_list_query(
        self,
        filters: Dict[str, Any],
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """根据筛选条件构建 MongoDB 查询。"""
        query: Dict[str, Any] = {}

        if user_id:
            query["user_id"] = user_id

        search_keyword = filters.get("search_keyword")
        if search_keyword:
            escaped = re.escape(search_keyword)
            query["$or"] = [
                {"stock_symbol": {"$regex": escaped, "$options": "i"}},
                {"analysis_id": {"$regex": escaped, "$options": "i"}},
                {"summary": {"$regex": escaped, "$options": "i"}},
            ]

        market_filter = filters.get("market_filter")
        if market_filter:
            query["market_type"] = market_filter

        stock_code = filters.get("stock_code")
        if stock_code:
            query["stock_symbol"] = stock_code

        start_date = filters.get("start_date")
        end_date = filters.get("end_date")
        if start_date or end_date:
            date_query: Dict[str, str] = {}
            if start_date:
                date_query["$gte"] = start_date
            if end_date:
                date_query["$lte"] = end_date
            query["analysis_date"] = date_query

        return query

    # ------------------------------------------------------------------
    # 私有方法：格式化报告
    # ------------------------------------------------------------------

    async def _format_report_list_item(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """将数据库文档格式化为列表项。"""
        stock_code = doc.get("stock_symbol", "")

        stock_name = doc.get("stock_name")
        if not stock_name:
            stock_name = await _get_stock_name_async(stock_code)

        market_type = doc.get("market_type")
        if not market_type:
            market_type = _infer_market_type(stock_code)

        created_at = doc.get("created_at", now_utc())
        created_at_tz = to_config_tz(created_at)

        return {
            "id": str(doc["_id"]),
            "analysis_id": doc.get("analysis_id", ""),
            "title": f"{stock_name}({stock_code}) 分析报告",
            "stock_code": stock_code,
            "stock_name": stock_name,
            "market_type": market_type,
            "model_info": doc.get("model_info", "Unknown"),
            "type": "single",
            "format": "markdown",
            "status": doc.get("status", "completed"),
            "created_at": created_at_tz.isoformat() if created_at_tz else str(created_at),
            "analysis_date": doc.get("analysis_date", ""),
            "analysts": doc.get("analysts", []),
            "summary": doc.get("summary", ""),
            "file_size": len(str(doc.get("reports", {}))),
            "source": doc.get("source", "unknown"),
            "task_id": doc.get("task_id", ""),
        }

    async def _format_report_detail_from_reports_collection(
        self,
        doc: Dict[str, Any],
    ) -> Dict[str, Any]:
        """将 analysis_reports 中的文档格式化为详情。"""
        stock_symbol = doc.get("stock_symbol", "")
        stock_name = doc.get("stock_name")
        if not stock_name:
            stock_name = await _get_stock_name_async(stock_symbol)

        created_at = doc.get("created_at", now_utc())
        updated_at = doc.get("updated_at", now_utc())
        created_at_tz = to_config_tz(created_at)
        updated_at_tz = to_config_tz(updated_at)

        # 尝试修复空报告：从 analysis_tasks 中的 state 恢复
        reports = doc.get("reports", {})
        if not reports and doc.get("task_id"):
            reports = await self._recover_reports_from_task_state(doc["task_id"])

        # 提取结构化字段
        extracted = _extract_structured_fields(doc)

        return {
            "id": str(doc["_id"]),
            "analysis_id": doc.get("analysis_id", ""),
            "stock_symbol": stock_symbol,
            "stock_name": stock_name,
            "model_info": doc.get("model_info", "Unknown"),
            "analysis_date": doc.get("analysis_date", ""),
            "status": doc.get("status", "completed"),
            "created_at": created_at_tz.isoformat() if created_at_tz else str(created_at),
            "updated_at": updated_at_tz.isoformat() if updated_at_tz else str(updated_at),
            "analysts": doc.get("analysts", []),
            "summary": extracted["summary"],
            "reports": reports,
            "source": doc.get("source", "unknown"),
            "task_id": doc.get("task_id", ""),
            "recommendation": extracted["recommendation"],
            "confidence_score": extracted["confidence_score"],
            "risk_level": extracted["risk_level"],
            "key_points": doc.get("key_points", []),
            "execution_time": doc.get("execution_time", 0),
            "tokens_used": doc.get("tokens_used", 0),
            "structured_summary": extracted["structured_summary"],
            "decision": doc.get("decision", {}),
        }

    async def _restore_report_from_tasks(
        self,
        report_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        从 analysis_tasks 集合中还原报告详情（兜底逻辑）。
        当 analysis_reports 中没有找到时使用。
        """
        tasks_doc = await self.db.analysis_tasks.find_one(
            {"$or": [{"task_id": report_id}, {"result.analysis_id": report_id}]},
            {"result": 1, "task_id": 1, "stock_code": 1, "created_at": 1, "completed_at": 1}
        )

        if not tasks_doc or not tasks_doc.get("result"):
            return None

        r = tasks_doc["result"] or {}
        created_at = tasks_doc.get("created_at")
        updated_at = tasks_doc.get("completed_at") or created_at

        # 尝试从 state 中恢复 reports
        reports = r.get("reports", {})
        if not reports and "state" in r:
            state = r["state"]
            reports = _extract_reports_from_state(state)
            if reports:
                logger.info(f"从 state 中恢复了 {len(reports)} 个报告模块")

        # 时区转换
        created_at_tz = to_config_tz(created_at)
        updated_at_tz = to_config_tz(updated_at)

        def _to_iso(x: Any) -> str:
            if hasattr(x, "isoformat"):
                return x.isoformat()
            return x or ""

        stock_symbol = r.get("stock_symbol", r.get("stock_code", tasks_doc.get("stock_code", "")))
        stock_name = r.get("stock_name")
        if not stock_name:
            stock_name = await _get_stock_name_async(stock_symbol)

        # 提取结构化字段
        extracted = _extract_structured_fields(r)

        return {
            "id": tasks_doc.get("task_id", report_id),
            "analysis_id": r.get("analysis_id", ""),
            "stock_symbol": stock_symbol,
            "stock_name": stock_name,
            "model_info": r.get("model_info", "Unknown"),
            "analysis_date": r.get("analysis_date", ""),
            "status": r.get("status", "completed"),
            "created_at": _to_iso(created_at_tz),
            "updated_at": _to_iso(updated_at_tz),
            "analysts": r.get("analysts", []),
            "summary": r.get("summary", "") or extracted.get("summary", ""),
            "reports": reports,
            "source": "analysis_tasks",
            "task_id": tasks_doc.get("task_id", report_id),
            "recommendation": extracted["recommendation"],
            "confidence_score": extracted["confidence_score"],
            "risk_level": extracted["risk_level"],
            "key_points": r.get("key_points", []),
            "execution_time": r.get("execution_time", 0),
            "tokens_used": r.get("tokens_used", 0),
            "structured_summary": extracted["structured_summary"],
            "decision": r.get("decision", {}),
        }

    async def _recover_reports_from_task_state(
        self,
        task_id: str,
    ) -> Dict[str, str]:
        """
        尝试从 analysis_tasks 中查找 task_id 对应的 state，恢复报告模块。
        当 analysis_reports 中报告内容为空时使用。
        """
        try:
            task_doc = await self.db.analysis_tasks.find_one(
                {"task_id": task_id},
                {"result.state": 1}
            )
            if not task_doc or not task_doc.get("result"):
                return {}

            state = task_doc["result"].get("state")
            if not isinstance(state, dict):
                return {}

            reports = _extract_reports_from_state(state)
            if reports:
                logger.info(f"从任务 state 中恢复了 {len(reports)} 个报告模块")
            return reports

        except Exception as e:
            logger.warning(f"尝试恢复报告失败: {e}")
            return {}


# ===================================================================
# 全局服务实例与工厂函数
# ===================================================================

_service: Optional[ReportsService] = None


def get_reports_service() -> ReportsService:
    """获取报告服务单例实例。"""
    global _service
    if _service is None:
        db = get_mongo_db()
        _service = ReportsService(db)
    return _service
