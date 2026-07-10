"""
AKShare 业绩快报 API — 通过 stock_yjkb_em（东方财富）获取。

作为 tushare express 的备用源。akshare 按报告期日期查询，返回该报告期全部股票的
业绩快报；若提供 ts_code 则按股票代码过滤。
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
_DOMAIN = "express"

_COLUMN_MAPPER = {
    "股票代码": "ts_code",
    "股票简称": "name",
    "公告日期": "ann_date",
    "每股收益": "eps",
    "营业收入-营业收入": "revenue",
    "营业收入-去年同期": "revenue_pre",
    "净利润-净利润": "net_profit",
    "净利润-去年同期": "net_profit_pre",
    "每股净资产": "bps",
    "净资产收益率": "roe",
    "所处行业": "industry",
}


def _norm_date(s: str) -> str:
    if not s:
        return None
    return str(s).replace("-", "")[:8]


async def fetch_express(
    ts_code: str = None,
    start_date: str = None,
    end_date: str = None,
) -> pd.DataFrame:
    """获取业绩快报（AKShare 回退源）。"""
    qdate = _norm_date(end_date) or _norm_date(start_date)
    if not qdate:
        raise DataNotFoundError("akshare", _DOMAIN, "express 需报告期日期")

    try:
        import akshare as ak

        from app.data.sources.cn.akshare.api.anti_scraping import wait_rate_limit

        def _fetch():
            wait_rate_limit()
            return ak.stock_yjkb_em(date=qdate)

        df = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "akshare", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        raise DataFormatError("akshare", _DOMAIN, f"date={qdate}: {exc}")
    except Exception as exc:
        raise DataSourceUnavailableError("akshare", _DOMAIN, f"date={qdate}: {exc}")

    if is_empty_result(df):
        raise DataNotFoundError("akshare", _DOMAIN, f"date={qdate} 无业绩快报")

    df = df.rename(columns=_COLUMN_MAPPER)

    if ts_code:
        target = str(ts_code).zfill(6)
        sub = df[df["ts_code"].astype(str).str.zfill(6) == target]
        df = sub if not sub.empty else df

    if "ann_date" in df.columns:
        df["ann_date"] = pd.to_datetime(df["ann_date"], errors="coerce").dt.strftime("%Y%m%d")

    if "ts_code" in df.columns:
        df["ts_code"] = df["ts_code"].astype(str).str.zfill(6)
        df["symbol"] = df["ts_code"]
    df["data_source"] = "akshare"

    logger.info(f"AKShare 业绩快报: {qdate} {len(df)} 条")
    return df
