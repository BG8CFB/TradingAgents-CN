"""
Tushare US 美股财务指标 API
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _to_us_ts_code(symbol: str) -> str:
    """将普通 ticker 转换为 Tushare US ts_code 格式。

    AAPL → AAPL.O (NASDAQ 默认)
    """
    symbol = symbol.upper().strip()
    if "." in symbol:
        return symbol
    return f"{symbol}.O"


async def fetch_fina_indicator(
    api,
    ts_code: str,
) -> Optional[pd.DataFrame]:
    """获取美股财务指标数据。

    Args:
        api: tushare pro_api 实例
        ts_code: 股票代码，如 "AAPL" 或 "AAPL.O"

    Returns:
        财务指标 DataFrame，失败返回 None
    """
    if api is None:
        return None
    us_code = _to_us_ts_code(ts_code)
    try:
        df = await asyncio.to_thread(api.us_fina_indicator, ts_code=us_code)
        if df is not None and not df.empty:
            logger.info(f"Tushare US 财务指标: {us_code} {len(df)} 条")
        return df
    except Exception as e:
        logger.debug(f"Tushare US 获取财务指标失败 {ts_code}: {e}")
        return None
