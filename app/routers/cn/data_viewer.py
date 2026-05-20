"""
股票数据查看 API
"""

from typing import Optional

from fastapi import APIRouter, Query

from app.core.response import ok, fail

router = APIRouter(prefix="/api/cn/data", tags=["CN Data Viewer"])


@router.get("/stock/{symbol}")
async def get_stock_data(
    symbol: str,
    domain: Optional[str] = Query(None, description="数据域，为空返回全部"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """查看单股多域数据"""
    try:
        from app.core.database import get_database
        from app.data.schema.collections import get_collection_name

        db = await get_database()

        domains = [domain] if domain else [
            "basic_info", "daily_quotes", "daily_indicators",
            "adj_factors", "financial", "news",
        ]

        result = {}
        for d in domains:
            try:
                collection = db[get_collection_name("CN", d)]
                query = {"symbol": symbol}
                if start_date and "trade_date" in (f for f in ["trade_date"]):
                    query.setdefault("trade_date", {})
                    query["trade_date"]["$gte"] = start_date
                if end_date:
                    query.setdefault("trade_date", {})
                    query["trade_date"]["$lte"] = end_date

                total = await collection.count_documents(query)
                if d == "basic_info":
                    items = await collection.find(query).to_list(length=1)
                else:
                    cursor = collection.find(query).sort(
                        "trade_date" if d != "news" else "updated_at", -1,
                    ).skip((page - 1) * page_size).limit(page_size)
                    items = await cursor.to_list(length=page_size)

                result[d] = {
                    "total": total,
                    "items": items,
                }
            except Exception as e:
                result[d] = {"total": 0, "items": [], "error": str(e)}

        return ok(data=result)

    except Exception as e:
        return fail(message=f"查询失败: {e}", code=500)
