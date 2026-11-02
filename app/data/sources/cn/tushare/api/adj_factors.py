"""
Tushare 复权因子 API

调用模板收敛在 app/data/sources/tushare_common/caller.py。
"""
import logging
from typing import Optional

import pandas as pd

from app.data.sources.tushare_common.caller import call_tushare, call_tushare_paged

from .connection import TushareConnection

logger = logging.getLogger(__name__)

_DOMAIN = "adj_factors"
_SOURCE = "tushare"


async def fetch_adj_factors(
    conn: TushareConnection,
    ts_code: str,
    start_date: str = None,
    end_date: str = None,
) -> Optional[pd.DataFrame]:
    """获取复权因子"""
    params: dict = {"ts_code": ts_code}
    if start_date:
        params["start_date"] = start_date.replace("-", "")
    if end_date:
        params["end_date"] = end_date.replace("-", "")

    return await call_tushare(
        conn, "adj_factor", _SOURCE, _DOMAIN, f"ts_code={ts_code}", **params
    )


async def fetch_adj_factors_by_date(
    conn: TushareConnection, trade_date: str
) -> Optional[pd.DataFrame]:
    """按交易日一次拉全市场复权因子（官方 adj_factor 支持 trade_date 不带 ts_code）。

    单日全市场 ≈ 5000+ 行，需 offset/limit 翻页；列名（ts_code/trade_date/
    adj_factor）与逐 symbol 模式一致，走同一 normalizer 入库。
    """
    date_str = str(trade_date).replace("-", "")
    return await call_tushare_paged(
        conn, "adj_factor", _SOURCE, _DOMAIN, f"trade_date={date_str}",
        trade_date=date_str,
    )
