"""
数据质量检查 API — 真实扫库统计
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query

from app.core.response import ok, fail

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cn/data", tags=["CN Data Quality"])


@router.get("/quality/overview")
async def get_quality_overview():
    """数据质量总览 — 各域记录数、完整率、最新日期"""
    try:
        from app.core.database import get_database
        from app.data.schema.collections import get_collection_name

        db = await get_database()

        overview = {}
        domains = ["daily_quotes", "daily_indicators", "adj_factors", "financial", "basic_info", "news"]

        for domain in domains:
            try:
                collection = db[get_collection_name("CN", domain)]
                total = await collection.count_documents({})
                missing_symbol = await collection.count_documents({"symbol": {"$exists": False}})

                # 查询最新数据日期
                latest_doc = await collection.find_one(
                    {"trade_date": {"$exists": True}},
                    sort=[("trade_date", -1)],
                )
                latest_date = latest_doc.get("trade_date") if latest_doc else None

                overview[domain] = {
                    "total_records": total,
                    "missing_symbol": missing_symbol,
                    "completeness": round((total - missing_symbol) / total, 3) if total > 0 else 1.0,
                    "latest_date": latest_date,
                }
            except Exception as e:
                overview[domain] = {"error": str(e)}

        return ok(data=overview)

    except Exception as e:
        return fail(message=f"查询失败: {e}", code=500)


@router.post("/quality/check")
async def trigger_quality_check(
    domain: Optional[str] = Query(None, description="指定域，为空检查全部"),
):
    """触发数据质量检查 — 真实扫库统计"""
    try:
        from app.core.database import get_database
        from app.data.schema.collections import get_collection_name

        db = await get_database()
        results = {}
        domains = [domain] if domain else ["daily_quotes", "daily_indicators", "financial", "basic_info"]

        for d in domains:
            try:
                collection = db[get_collection_name("CN", d)]
                stats = await _check_domain_quality(db, collection, d)
                results[d] = stats
            except Exception as e:
                results[d] = {"error": str(e)}

        return ok(data={"check_id": "inline", "results": results})

    except Exception as e:
        return fail(message=f"检查失败: {e}", code=500)


async def _check_domain_quality(db, collection, domain: str) -> dict:
    """对指定域执行真实质量检查"""

    total = await collection.count_documents({})
    stats = {
        "total_records": total,
        "issues": [],
    }

    if total == 0:
        stats["status"] = "empty"
        return stats

    # 1. 必填字段缺失检查
    required_fields_map = {
        "daily_quotes": ["symbol", "trade_date", "close"],
        "daily_indicators": ["symbol", "trade_date"],
        "financial": ["symbol", "report_period"],
        "basic_info": ["symbol"],
    }
    required = required_fields_map.get(domain, ["symbol"])

    for field in required:
        missing_count = await collection.count_documents({
            "$or": [
                {field: {"$exists": False}},
                {field: None},
                {field: ""},
            ],
        })
        if missing_count > 0:
            stats["issues"].append({
                "type": "missing_field",
                "field": field,
                "count": missing_count,
                "percentage": round(missing_count / total * 100, 2),
            })

    # 2. 行情日期连续性检查（仅时序数据域）
    if domain in ("daily_quotes", "daily_indicators", "adj_factors"):
        coverage = await _check_date_continuity(db, collection, domain)
        stats["date_continuity"] = coverage

    # 3. 行情覆盖率检查（daily_quotes 对比 basic_info 活跃股票数）
    if domain == "daily_quotes":
        coverage = await _check_stock_coverage(db, collection)
        stats["stock_coverage"] = coverage

    # 4. 异常值检测（日线行情涨跌幅边界）
    if domain == "daily_quotes":
        anomaly = await _check_price_anomaly(collection)
        if anomaly:
            stats["price_anomaly"] = anomaly

    stats["status"] = "ok" if not stats["issues"] else "warning"
    return stats


async def _check_date_continuity(db, collection, domain: str) -> dict:
    """检查行情日期连续性"""
    # 查最近 30 天的交易日覆盖
    from app.data.schema.collections import get_collection_name

    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    pipeline = [
        {"$match": {"trade_date": {"$gte": thirty_days_ago}}},
        {"$group": {"_id": "$trade_date", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]

    try:
        cursor = collection.aggregate(pipeline)
        date_counts = await cursor.to_list(length=None)
        trading_days_covered = len(date_counts)

        # 查交易日历获取应有交易日数
        try:
            cal_collection = db[get_collection_name("CN", "trade_calendar")]
            expected_days = await cal_collection.count_documents({
                "is_open": 1,
                "cal_date": {"$gte": thirty_days_ago},
            })
        except Exception:
            expected_days = None

        return {
            "trading_days_covered": trading_days_covered,
            "expected_trading_days": expected_days,
            "coverage_rate": round(trading_days_covered / expected_days, 3) if expected_days else None,
            "period": "last_30_days",
        }
    except Exception as e:
        return {"error": str(e)}


async def _check_stock_coverage(db, collection) -> dict:
    """检查行情对活跃股票的覆盖率"""
    from app.data.schema.collections import get_collection_name

    try:
        # 活跃股票数
        bi_collection = db[get_collection_name("CN", "basic_info")]
        active_stocks = await bi_collection.count_documents({"list_status": "L"})

        if active_stocks == 0:
            return {"error": "无活跃股票数据"}

        # 最新日期有行情的股票数
        latest = await collection.find_one(sort=[("trade_date", -1)])
        if not latest:
            return {"error": "无行情数据"}

        latest_date = latest.get("trade_date", "")
        covered = await collection.count_documents({"trade_date": latest_date})

        return {
            "active_stocks": active_stocks,
            "covered_stocks": covered,
            "coverage_rate": round(covered / active_stocks, 3),
            "latest_date": latest_date,
        }
    except Exception as e:
        return {"error": str(e)}


async def _check_price_anomaly(collection) -> dict:
    """检查涨跌幅异常值（A 股通常 ±20% 限制）"""
    try:
        anomaly_count = await collection.count_documents({
            "$or": [
                {"pct_chg": {"$gt": 20}},
                {"pct_chg": {"$lt": -20}},
            ],
        })

        if anomaly_count > 0:
            return {
                "count": anomaly_count,
                "description": "涨跌幅超出 ±20% 的记录（可能为 ST 股或新股上市）",
            }
        return {}
    except Exception:
        return {}
