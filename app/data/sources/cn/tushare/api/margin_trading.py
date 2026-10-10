"""
Tushare 融资融券 API

接口: margin_detail (个股融资融券明细)
要求: >= 120 积分

调用模板收敛在 app/data/sources/tushare_common/caller.py。
"""
import logging
from typing import Optional

import pandas as pd

from app.data.sources.tushare_common.caller import call_tushare

from .connection import TushareConnection

logger = logging.getLogger(__name__)

_DOMAIN = "margin_trading"
_SOURCE = "tushare"


async def fetch_margin_detail(
    conn: TushareConnection,
    ts_code: Optional[str],
    start_date: str = None,
    end_date: str = None,
    limit: int = 60,
) -> Optional[pd.DataFrame]:
    """获取个股融资融券明细。

    ts_code 为空 = 批量模式（同步任务 `__all__` 路径专用）：按交易日一次拉全市场。
    逐 symbol 模式对全市场要 5,500+ 次调用，而两融**只有标的股**有数据 →
    大量空结果（修复前会打满熔断器造成覆盖率坍塌）；按交易日一次即可（单日约 4,400 行）。
    """
    if not ts_code:
        trade_date = (end_date or start_date or "").replace("-", "")
        if not trade_date:
            logger.warning("margin_trading 批量模式缺少 trade_date，返回空")
            return None
        return await call_tushare(
            conn,
            "margin_detail",
            _SOURCE,
            _DOMAIN,
            f"trade_date={trade_date}",
            trade_date=trade_date,
        )

    kwargs = {"ts_code": ts_code}
    if start_date:
        kwargs["start_date"] = str(start_date).replace("-", "")
    if end_date:
        kwargs["end_date"] = str(end_date).replace("-", "")
    if not start_date and not end_date:
        kwargs["limit"] = limit

    return await call_tushare(
        conn, "margin_detail", _SOURCE, _DOMAIN, f"ts_code={ts_code}", **kwargs
    )
