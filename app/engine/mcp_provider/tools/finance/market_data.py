"""
Market Data Tools Logic — 基于新数据架构 DataInterface。
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta

from app.data.core.interface import DataInterface
from app.utils.stock_utils import StockUtils, StockMarket

logger = logging.getLogger(__name__)

_MARKET_MAP = {
    StockMarket.A_SHARE: "CN",
    StockMarket.HONG_KONG: "HK",
    StockMarket.US: "US",
}


async def get_stock_kline_logic(_reader_mod, code: str, period: str, limit: int) -> str:
    """获取 K 线数据。"""
    market_enum = StockUtils.identify_stock_market(code)
    market = _MARKET_MAP.get(market_enum, "CN")

    # 从代码中提取 symbol（去掉后缀）
    symbol = code.split(".")[0] if "." in code else code

    di = DataInterface.get_instance()

    try:
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=max(limit * 2, 60))).strftime("%Y-%m-%d")

        result = await di.read(market, "daily_quotes", symbol=symbol, start_date=start_date, end_date=end_date)
        data = result.get("data")

        if not data or not isinstance(data, list):
            return json.dumps({
                "status": "warning",
                "message": f"No data found for {code}."
            }, ensure_ascii=False)

        items = data[-limit:] if len(data) > limit else data
        result_data = {
            "code": code,
            "market": market_enum.value,
            "source": "data_platform",
            "count": len(items),
            "data": items
        }
        return json.dumps(result_data, ensure_ascii=False, default=str)

    except Exception as e:
        logger.error(f"Error in get_stock_kline_logic: {e}")
        return json.dumps({
            "status": "error",
            "message": str(e)
        }, ensure_ascii=False)
