"""
Finnhub US 美股盘前盘后行情 API

免费层不支持盘前盘后行情端点，此模块预留接口，暂返回 None。
"""
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


async def fetch_pre_post_market(
    symbol: str,
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """获取美股盘前盘后行情。

    免费层不支持盘前盘后行情端点，暂返回 None。

    Args:
        symbol: 股票代码（大写），如 "AAPL"
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)

    Returns:
        始终返回 None（免费层不支持）
    """
    logger.debug(f"Finnhub-US 盘前盘后行情暂不支持（免费层）: {symbol}")
    return None
