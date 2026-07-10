"""
AKShare 公告 API — 通过 stock_notice_report（东方财富沪深京 A 股公告）获取。

作为 tushare announcement 的备用源。akshare 按单日查询，本函数以 end_date（或
start_date）作为查询日期，返回该日全部公告。
"""
import asyncio
import logging
from datetime import date

import pandas as pd

from app.data.sources.base.exceptions import (
    DataFormatError,
    DataNotFoundError,
    DataSourceUnavailableError,
)
from app.data.sources.base.mappers import is_empty_result, map_network_exception

logger = logging.getLogger(__name__)
_DOMAIN = "announcement"

_COLUMN_MAPPER = {
    "代码": "ts_code",
    "名称": "name",
    "公告标题": "title",
    "公告类型": "ann_type",
    "公告日期": "ann_date",
    "网址": "url",
}


def _norm_date(s: str) -> str:
    if not s:
        return None
    return str(s).replace("-", "")[:8]


async def fetch_announcement(
    start_date: str = None,
    end_date: str = None,
) -> pd.DataFrame:
    """获取公告（AKShare 回退源）。"""
    qdate = _norm_date(end_date) or _norm_date(start_date)
    if not qdate:
        qdate = date.today().strftime("%Y%m%d")

    try:
        import akshare as ak

        from app.data.sources.cn.akshare.api.anti_scraping import wait_rate_limit

        def _fetch():
            wait_rate_limit()
            return ak.stock_notice_report(symbol="全部", date=qdate)

        df = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "akshare", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        raise DataFormatError("akshare", _DOMAIN, f"date={qdate}: {exc}")
    except Exception as exc:
        raise DataSourceUnavailableError("akshare", _DOMAIN, f"date={qdate}: {exc}")

    if is_empty_result(df):
        raise DataNotFoundError("akshare", _DOMAIN, f"date={qdate} 无公告")

    df = df.rename(columns=_COLUMN_MAPPER)

    if "ann_date" in df.columns:
        df["ann_date"] = pd.to_datetime(df["ann_date"], errors="coerce").dt.strftime("%Y%m%d")

    if "ts_code" in df.columns:
        df["ts_code"] = df["ts_code"].astype(str).str.zfill(6)
        df["symbol"] = df["ts_code"]
    df["data_source"] = "akshare"

    logger.info(f"AKShare 公告: {qdate} {len(df)} 条")
    return df
