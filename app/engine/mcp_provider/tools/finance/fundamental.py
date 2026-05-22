"""
Fundamental Data Tools Logic — 基于新数据架构 DataInterface。
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


async def get_company_metrics_logic(_reader_mod, code: str, date: str) -> str:
    """获取公司基本面指标。"""
    market_enum = StockUtils.identify_stock_market(code)
    market = _MARKET_MAP.get(market_enum, "CN")

    symbol = code.split(".")[0] if "." in code else code

    di = DataInterface.get_instance()

    try:
        result = await di.read(market, symbol, "daily_indicators", start_date=date, end_date=date)
        data = result.get("data")

        if not data or not isinstance(data, list) or not data:
            return json.dumps({
                "status": "warning",
                "message": f"No fundamental data found for date {date}."
            }, ensure_ascii=False)

        record = data[0] if isinstance(data[0], dict) else data[0].to_dict() if hasattr(data[0], 'to_dict') else {}

        return json.dumps({
            "code": code,
            "date": date,
            "source": "data_platform",
            "metrics": record
        }, ensure_ascii=False, default=str)

    except Exception as e:
        logger.error(f"Error in get_company_metrics_logic: {e}")
        return json.dumps({
            "status": "error",
            "message": str(e)
        }, ensure_ascii=False)
