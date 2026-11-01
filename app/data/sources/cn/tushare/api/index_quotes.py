"""Tushare 指数日线 API（index_daily，基准宇宙 per-symbol 拉取）。"""

import logging
from typing import Optional

import pandas as pd

from app.data.sources.base.exceptions import DataNotFoundError
from app.data.sources.base.mappers import is_empty_result
from app.data.sources.tushare_common.caller import call_tushare

from .connection import TushareConnection

logger = logging.getLogger(__name__)

_SOURCE = "tushare"
_DOMAIN = "index_quotes"

# index_daily 输出字段：ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,volume,amount
_INDEX_DAILY_FIELDS = (
    "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,volume,amount"
)


async def fetch_index_quotes(
    conn: TushareConnection,
    ts_code: str,
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """获取指数日线（tushare index_daily；ts_code 如 000300.SH，带交易所后缀）。"""
    if not conn.is_available():
        return None

    start_str = str(start_date).replace("-", "")
    end_str = str(end_date).replace("-", "")

    df = await call_tushare(
        conn,
        "index_daily",
        _SOURCE,
        _DOMAIN,
        ts_code=ts_code,
        start_date=start_str,
        end_date=end_str,
        fields=_INDEX_DAILY_FIELDS,
    )

    if is_empty_result(df):
        logger.warning(f"Tushare 指数返回空: {ts_code} {start_str}-{end_str}")
        raise DataNotFoundError(_SOURCE, _DOMAIN, f"ts_code={ts_code} {start_str}-{end_str} 无数据")

    logger.info(f"Tushare 获取指数日线: {ts_code} {len(df)} 条")
    return df
