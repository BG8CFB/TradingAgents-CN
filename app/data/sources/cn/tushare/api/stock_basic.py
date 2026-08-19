"""
Tushare 股票基础信息 API

调用模板收敛在 app/data/sources/tushare_common/caller.py。
"""
import logging
from typing import Any, Dict, Optional

import pandas as pd

from app.data.sources.tushare_common.caller import call_tushare

from .connection import TushareConnection

logger = logging.getLogger(__name__)

_DOMAIN = "stock_basic"
_SOURCE = "tushare"

_STOCK_BASIC_FIELDS = (
    "ts_code,symbol,name,area,industry,market,exchange,list_date,is_hs"
)


async def fetch_stock_list(conn: TushareConnection, market: str = None) -> Optional[pd.DataFrame]:
    """获取 A 股股票列表"""
    params: Dict[str, Any] = {"list_status": "L", "fields": _STOCK_BASIC_FIELDS}
    if market == "CN":
        params["exchange"] = "SSE,SZSE"

    return await call_tushare(conn, "stock_basic", _SOURCE, _DOMAIN, **params)


async def fetch_stock_basic_info(
    conn: TushareConnection, ts_code: str
) -> Optional[pd.DataFrame]:
    """获取单只股票基础信息"""
    # 港股基础信息已独立为 tushare_hk 源（独立 Token/积分），CN 源不再处理 .HK 代码
    return await call_tushare(
        conn,
        "stock_basic",
        _SOURCE,
        _DOMAIN,
        f"ts_code={ts_code}",
        ts_code=ts_code,
        fields=_STOCK_BASIC_FIELDS + ",act_name,act_ent_type",
    )
