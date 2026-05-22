"""
News Data Tools Logic — 基于新数据架构 DataInterface。
"""

import json
import logging

from app.data.core.interface import DataInterface
from app.utils.stock_utils import StockUtils, StockMarket

logger = logging.getLogger(__name__)

_MARKET_MAP = {
    StockMarket.A_SHARE: "CN",
    StockMarket.HONG_KONG: "HK",
    StockMarket.US: "US",
}


async def get_finance_news_logic(_reader_mod, code: str, days: int, limit: int) -> str:
    """获取财经新闻。"""
    market_enum = StockUtils.identify_stock_market(code)
    market = _MARKET_MAP.get(market_enum, "CN")

    symbol = code.split(".")[0] if "." in code else code

    di = DataInterface.get_instance()

    try:
        result = await di.read(market, symbol, "news")
        data = result.get("data")

        if not data or not isinstance(data, list) or not data:
            return json.dumps({
                "status": "warning",
                "message": f"No news found for {code} in last {days} days."
            }, ensure_ascii=False)

        items = data[:limit] if len(data) > limit else data

        return json.dumps({
            "code": code,
            "source": "data_platform",
            "count": len(items),
            "news": items
        }, ensure_ascii=False, default=str)

    except Exception as e:
        logger.error(f"Error in get_finance_news_logic: {e}")
        return json.dumps({
            "status": "error",
            "message": str(e)
        }, ensure_ascii=False)
