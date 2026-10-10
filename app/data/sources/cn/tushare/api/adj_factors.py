"""
Tushare 复权因子 API

调用模板收敛在 app/data/sources/tushare_common/caller.py。
"""
import logging
from typing import Optional

import pandas as pd

from app.data.sources.tushare_common.caller import call_tushare

from .connection import TushareConnection

logger = logging.getLogger(__name__)

_DOMAIN = "adj_factors"
_SOURCE = "tushare"


async def fetch_adj_factors(
    conn: TushareConnection,
    ts_code: Optional[str],
    start_date: str = None,
    end_date: str = None,
) -> Optional[pd.DataFrame]:
    """获取复权因子。

    ts_code 为空 = 批量模式（同步任务 `__all__` 路径专用）：按交易日一次拉全市场。
    逐 symbol 模式对全市场 ~5,500 只要 5,500 次调用（200/min 下 ≈28 分钟且极易触发限速）；
    `adj_factor` 支持 trade_date，**一次调用**即可拿当天全市场（实测单日约 5,500 行）。
    """
    if not ts_code:
        trade_date = (end_date or start_date or "").replace("-", "")
        if not trade_date:
            logger.warning("adj_factors 批量模式缺少 trade_date，返回空")
            return None
        return await call_tushare(
            conn,
            "adj_factor",
            _SOURCE,
            _DOMAIN,
            f"trade_date={trade_date}",
            trade_date=trade_date,
        )

    params: dict = {"ts_code": ts_code}
    if start_date:
        params["start_date"] = start_date.replace("-", "")
    if end_date:
        params["end_date"] = end_date.replace("-", "")

    return await call_tushare(
        conn, "adj_factor", _SOURCE, _DOMAIN, f"ts_code={ts_code}", **params
    )
