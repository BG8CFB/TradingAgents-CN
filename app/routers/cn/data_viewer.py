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
        from app.data.core.interface import DataInterface

        di = DataInterface.get_instance()

        domains = [domain] if domain else [
            "basic_info", "daily_quotes", "daily_indicators",
            "adj_factors", "financial", "news",
        ]

        result = {}
        for d in domains:
            try:
                read_result = await di.read("CN", symbol, d,
                                            start_date=start_date, end_date=end_date)
                data = read_result.get("data", [])
                if isinstance(data, list):
                    total = len(data)
                    start = (page - 1) * page_size
                    items = data[start:start + page_size]
                else:
                    total = 1
                    items = [data] if data else []

                result[d] = {
                    "total": total,
                    "items": items,
                }
            except Exception as e:
                result[d] = {"total": 0, "items": [], "error": str(e)}

        return ok(data=result)

    except Exception as e:
        return fail(message=f"查询失败: {e}", code=500)
