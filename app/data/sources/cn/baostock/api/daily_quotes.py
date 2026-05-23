"""
BaoStock 日线行情 API
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

from .connection import baostock_session, bs

logger = logging.getLogger(__name__)


def _to_baostock_code(symbol: str) -> str:
    """将纯数字代码转为 baostock 格式: sh.600000 / sz.000001"""
    code = str(symbol).zfill(6)
    if code.startswith(("6", "9")):
        return f"sh.{code}"
    return f"sz.{code}"


async def fetch_daily_quotes(
    code: str, start_date: str, end_date: str
) -> Optional[pd.DataFrame]:
    """获取日线行情（前复权）"""
    try:
        bs_code = _to_baostock_code(code)
        start = start_date.replace("-", "")
        end = end_date.replace("-", "")

        async with baostock_session():
            def _fetch():
                rs = bs.query_history_k_data_plus(
                    bs_code,
                    "date,code,open,high,low,close,preclose,volume,amount,turn,pctChg",
                    start_date=start,
                    end_date=end,
                    frequency="d",
                    adjustflag="2",
                )
                rows = []
                while rs.error_code == "0" and rs.next():
                    rows.append(rs.get_row_data())
                if rows:
                    return pd.DataFrame(rows, columns=rs.fields)
                return None

            df = await asyncio.to_thread(_fetch)
            if df is not None and not df.empty:
                logger.info(f"BaoStock 行情: {code} {len(df)} 条")
            return df

    except Exception as e:
        logger.error(f"BaoStock 获取行情失败 {code}: {e}")
        return None


async def fetch_adj_factors(
    code: str, start_date: str, end_date: str
) -> Optional[pd.DataFrame]:
    """获取复权因子"""
    try:
        bs_code = _to_baostock_code(code)
        start = start_date.replace("-", "")
        end = end_date.replace("-", "")

        async with baostock_session():
            def _fetch():
                rs = bs.query_adjust_factor(
                    code=bs_code,
                    start_date=start,
                    end_date=end,
                )
                rows = []
                while rs.error_code == "0" and rs.next():
                    rows.append(rs.get_row_data())
                if rows:
                    return pd.DataFrame(rows, columns=rs.fields)
                return None

            df = await asyncio.to_thread(_fetch)
            if df is not None and not df.empty:
                logger.info(f"BaoStock 复权因子: {code} {len(df)} 条")
            return df

    except Exception as e:
        logger.error(f"BaoStock 获取复权因子失败 {code}: {e}")
        return None
