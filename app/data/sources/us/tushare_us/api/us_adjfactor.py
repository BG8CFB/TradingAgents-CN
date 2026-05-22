"""
Tushare US 美股复权因子 API
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


async def fetch_adj_factors(
    api,
    ts_code: str,
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """获取美股复权因子。

    Args:
        api: tushare pro_api 实例
        ts_code: 股票代码，如 "AAPL" 或 "AAPL.O"
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)

    Returns:
        复权因子 DataFrame，失败返回 None
    """
    if api is None:
        return None
    us_code = _to_us_ts_code(ts_code)
    try:
        df = await asyncio.to_thread(
            api.us_adjfactor,
            ts_code=us_code,
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
        )
        if df is not None and not df.empty:
            logger.info(f"Tushare US 复权因子: {us_code} {len(df)} 条")
        return df
    except Exception as e:
        logger.debug(f"Tushare US 获取复权因子失败 {ts_code}: {e}")
        return None
