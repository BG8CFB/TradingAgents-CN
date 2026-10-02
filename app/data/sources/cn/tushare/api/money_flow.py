"""
Tushare 资金流向 API

接口: moneyflow (个股资金流向)
要求: >= 120 积分

调用模板收敛在 app/data/sources/tushare_common/caller.py。
"""
import logging
from typing import Optional

import pandas as pd

from app.data.sources.tushare_common.caller import call_tushare, call_tushare_paged

from .connection import TushareConnection

logger = logging.getLogger(__name__)

_DOMAIN = "money_flow"
_SOURCE = "tushare"


async def fetch_money_flow(
    conn: TushareConnection,
    ts_code: str,
    start_date: str = None,
    end_date: str = None,
    limit: int = 60,
) -> Optional[pd.DataFrame]:
    """获取个股资金流向"""
    kwargs = {"ts_code": ts_code}
    if start_date:
        kwargs["start_date"] = str(start_date).replace("-", "")
    if end_date:
        kwargs["end_date"] = str(end_date).replace("-", "")
    if not start_date and not end_date:
        kwargs["limit"] = limit

    return await call_tushare(
        conn, "moneyflow", _SOURCE, _DOMAIN, f"ts_code={ts_code}", **kwargs
    )


async def fetch_money_flow_by_date(
    conn: TushareConnection, trade_date: str
) -> Optional[pd.DataFrame]:
    """按交易日一次拉全市场资金流向（moneyflow 支持 trade_date 参数，分页）。

    逐 symbol 模式对全市场不可行（限流熔断）；单日全市场 ≈ 5000+ 行，
    需 offset/limit 翻页。列名与 adapt_money_flow 期望的原始口径一致。
    """
    date_str = str(trade_date).replace("-", "")
    return await call_tushare_paged(
        conn, "moneyflow", _SOURCE, _DOMAIN, f"trade_date={date_str}",
        trade_date=date_str,
    )
