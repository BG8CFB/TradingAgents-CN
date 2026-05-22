"""
yfinance US 美股每日指标 API

yfinance 不直接提供 PE/PB 等每日指标数据，
此模块预留接口，暂返回 None。
"""
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


async def fetch_daily_indicators(symbol: str) -> Optional[pd.DataFrame]:
    """获取美股每日指标数据（PE/PB 等）。

    yfinance 不直接提供每日指标端点，暂返回 None。
    后续可通过 info 接口补充静态指标。

    Args:
        symbol: 股票代码（大写），如 "AAPL"

    Returns:
        始终返回 None（yfinance 不支持）
    """
    logger.debug(f"yfinance-US 每日指标暂不支持: {symbol}")
    return None
