"""
AKShare 业绩预告 API — 通过 stock_yjyg_em（东方财富）获取。

作为 tushare forecast 的备用源。akshare 按报告期日期查询，返回该报告期全部股票的
业绩预告；若提供 ts_code 则按股票代码过滤。
"""
import asyncio
import logging

import pandas as pd

from app.data.sources.base.exceptions import (
    DataFormatError,
    DataNotFoundError,
    DataSourceUnavailableError,
)
from app.data.sources.base.mappers import is_empty_result, map_network_exception

logger = logging.getLogger(__name__)
_DOMAIN = "forecast"

_COLUMN_MAPPER = {
    "股票代码": "ts_code",
    "股票简称": "name",
    "公告日期": "ann_date",
    "报告日期": "end_date",
    "预测指标": "forecast_type",
    "业绩变动": "change",
    "业绩变动原因": "change_reason",
    "预告类型": "type",
    "上年同期值": "pre_value",
    "业绩变动幅度": "pct_chg",
    "预测数值": "forecast_value",
}


def _norm_date(s: str) -> str:
    if not s:
        return None
    return str(s).replace("-", "")[:8]


async def fetch_forecast(
    ts_code: str = None,
    start_date: str = None,
    end_date: str = None,
) -> pd.DataFrame:
    """获取业绩预告（AKShare 回退源）。"""
    qdate = _norm_date(end_date) or _norm_date(start_date)
    if not qdate:
        raise DataNotFoundError("akshare", _DOMAIN, "forecast 需报告期日期")

    try:
        import akshare as ak

        from app.data.sources.cn.akshare.api.anti_scraping import wait_rate_limit

        def _fetch():
            wait_rate_limit()
            return ak.stock_yjyg_em(date=qdate)

        df = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "akshare", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        raise DataFormatError("akshare", _DOMAIN, f"date={qdate}: {exc}")
    except Exception as exc:
        raise DataSourceUnavailableError("akshare", _DOMAIN, f"date={qdate}: {exc}")

    if is_empty_result(df):
        raise DataNotFoundError("akshare", _DOMAIN, f"date={qdate} 无业绩预告")

    df = df.rename(columns=_COLUMN_MAPPER)

    if ts_code:
        target = str(ts_code).zfill(6)
        sub = df[df["ts_code"].astype(str).str.zfill(6) == target]
        df = sub if not sub.empty else df

    if "ann_date" in df.columns:
        df["ann_date"] = pd.to_datetime(df["ann_date"], errors="coerce").dt.strftime("%Y%m%d")
    if "end_date" in df.columns:
        df["end_date"] = pd.to_datetime(df["end_date"], errors="coerce").dt.strftime("%Y%m%d")

    if "ts_code" in df.columns:
        df["ts_code"] = df["ts_code"].astype(str).str.zfill(6)
        df["symbol"] = df["ts_code"]
    df["data_source"] = "akshare"

    logger.info(f"AKShare 业绩预告: {qdate} {len(df)} 条")
    return df
