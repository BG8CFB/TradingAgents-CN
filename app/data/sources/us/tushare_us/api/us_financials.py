"""
Tushare US 美股财务数据 API — 多表联合（利润表/资产负债表/现金流量表/财务指标）。
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

from app.data.sources.base.exceptions import DataNotFoundError, DataSourceUnavailableError
from app.data.sources.base.mappers import (
    is_empty_result,
    map_network_exception,
    map_tushare_code,
)

logger = logging.getLogger(__name__)

_DOMAIN = "financial_data"


def _compact_date(value: Optional[str]) -> Optional[str]:
    """ISO YYYY-MM-DD → Tushare YYYYMMDD；空值返回 None。"""
    if not value:
        return None
    cleaned = str(value).strip().replace("-", "")
    if not cleaned:
        return None
    return cleaned


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
    - income     → api.us_income()
    - balance    → api.us_balancesheet()
    - cashflow   → api.us_cashflow()
    - indicator  → api.us_fina_indicator()

    Parameters
    ----------
    api : tushare.pro_api
        已初始化的 Tushare pro_api 实例。
    ts_code : str
        Tushare 格式美股代码，如 "AAPL.O"。
    statement_type : str
        报表类型: income / balance / cashflow / indicator。
    start_date, end_date : Optional[str]
        ISO 格式日期（YYYY-MM-DD）。按 Tushare 的公告日 ``ann_date`` 过滤
        （"在该区间内披露的报表"语义最稳定）。两端皆闭区间；未提供则不传。
    period : Optional[str]
        报告期末月（YYYYMMDD），如 "20231231"。用于精确指定单期报表。

    Returns
    -------
    Optional[pd.DataFrame]
        原始 DataFrame，字段因报表类型不同而异。
    """
    if api is None:
        return None
    api_method_map = {
        "income": "us_income",
        "balance": "us_balancesheet",
        "cashflow": "us_cashflow",
        "indicator": "us_fina_indicator",
    }
    method_name = api_method_map.get(statement_type, "us_income")
    method = getattr(api, method_name, None)
    if method is None:
        logger.error(f"Tushare US 不支持的财务接口: {method_name}")
        return None

    params = {"ts_code": ts_code}
    start_compact = _compact_date(start_date)
    end_compact = _compact_date(end_date)
    if start_compact:
        params["start_date"] = start_compact
    if end_compact:
        params["end_date"] = end_compact
    if period:
        params["period"] = _compact_date(period)

    try:
        df = await asyncio.to_thread(lambda: method(**params))
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "tushare_us", _DOMAIN)
    except Exception as exc:
        error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
        mapped = map_tushare_code(error_code, "tushare_us", _DOMAIN, str(exc))
        if mapped is not None:
            raise mapped
        raise DataSourceUnavailableError(
            "tushare_us", _DOMAIN, f"ts_code={ts_code} ({statement_type}): {exc}"
        )

    if is_empty_result(df):
        logger.warning(f"Tushare US 财务数据返回空数据: {ts_code} ({statement_type})")
        raise DataNotFoundError(
            "tushare_us", _DOMAIN, f"{ts_code} ({statement_type}) 无数据"
        )

    logger.info(f"Tushare US 财务数据({statement_type}): {ts_code} {len(df)} 条")
    return df
