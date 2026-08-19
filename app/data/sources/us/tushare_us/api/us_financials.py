"""
Tushare US 美股财务数据 API — 多表联合（利润表/资产负债表/现金流量表/财务指标）。

调用模板收敛在 app/data/sources/tushare_common/caller.py。

异常语义：NetworkError / RateLimitedError / TokenInvalidError /
InsufficientCreditsError / DataNotFoundError / DataSourceUnavailableError
由 call_tushare 统一抛出（内部经 map_tushare_code 错误码分类）。
"""
import logging
from typing import Optional

import pandas as pd

from app.data.sources.tushare_common.caller import call_tushare

logger = logging.getLogger(__name__)

_DOMAIN = "financial_data"
_SOURCE = "tushare_us"

# 报表类型 → Tushare US 接口
_API_METHOD_MAP = {
    "income": "us_income",
    "balance": "us_balancesheet",
    "cashflow": "us_cashflow",
    "indicator": "us_fina_indicator",
}


def _compact_date(value: Optional[str]) -> Optional[str]:
    """ISO YYYY-MM-DD → Tushare YYYYMMDD；空值返回 None。"""
    if not value:
        return None
    cleaned = str(value).strip().replace("-", "")
    return cleaned or None


async def fetch_financial_data(
    api,
    ts_code: str,
    statement_type: str = "income",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    period: Optional[str] = None,
) -> Optional[pd.DataFrame]:
    """获取美股财务报表数据。

    根据 statement_type 路由到对应的 Tushare US 接口：
    income / balance / cashflow / indicator。

    start_date, end_date : Optional[str]
        ISO 格式日期（YYYY-MM-DD），按公告日 ``ann_date`` 过滤（闭区间）。
    period : Optional[str]
        报告期末月（YYYYMMDD），如 "20231231"。
    """
    method_name = _API_METHOD_MAP.get(statement_type, "us_income")

    params = {"ts_code": ts_code}
    start_compact = _compact_date(start_date)
    end_compact = _compact_date(end_date)
    if start_compact:
        params["start_date"] = start_compact
    if end_compact:
        params["end_date"] = end_compact
    if period:
        params["period"] = _compact_date(period)

    return await call_tushare(
        api,
        method_name,
        _SOURCE,
        _DOMAIN,
        f"{ts_code} ({statement_type})",
        **params,
    )
