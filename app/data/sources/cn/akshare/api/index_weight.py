"""
AKShare 指数成分及权重 API — 通过 index_stock_cons_weight_csindex（中证指数）获取。

作为 tushare index_weight 的备用源：成分券代码 / 名称 / 权重。
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
_DOMAIN = "index_weight"

_COLUMN_MAPPER = {
    "日期": "trade_date",
    "指数代码": "index_code",
    "指数名称": "index_name",
    "成分券代码": "con_code",
    "成分券名称": "con_name",
    "权重": "weight",
}


def _norm_date(s: str) -> str:
    if not s:
        return None
    return str(s).replace("-", "")[:8]


async def fetch_index_weight(
    index_code: str,
    trade_date: str = None,
    start_date: str = None,
    end_date: str = None,
) -> pd.DataFrame:
    """获取指数成分及权重（AKShare 回退源）。"""
    code = str(index_code).split(".")[0] if index_code else ""
    if not code:
        raise DataNotFoundError("akshare", _DOMAIN, f"index_code={index_code} 无效")

    try:
        import akshare as ak

        from app.data.sources.cn.akshare.api.anti_scraping import wait_rate_limit

        def _fetch():
            wait_rate_limit()
            return ak.index_stock_cons_weight_csindex(symbol=code)

        df = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "akshare", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        raise DataFormatError("akshare", _DOMAIN, f"index_code={index_code}: {exc}")
    except Exception as exc:
        raise DataSourceUnavailableError("akshare", _DOMAIN, f"index_code={index_code}: {exc}")

    if is_empty_result(df):
        raise DataNotFoundError("akshare", _DOMAIN, f"index_code={index_code} 无成分权重")

    df = df.rename(columns=_COLUMN_MAPPER)

    # akshare 返回单日快照；按 trade_date 过滤（无则取最新一日）
    if "trade_date" in df.columns:
        df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.strftime("%Y%m%d")
        df = df.dropna(subset=["trade_date"])
        if trade_date:
            td = _norm_date(trade_date)
            sub = df[df["trade_date"] == td]
            df = sub if not sub.empty else df
        if start_date:
            df = df[df["trade_date"] >= _norm_date(start_date)]
        if end_date:
            df = df[df["trade_date"] <= _norm_date(end_date)]

    if df.empty:
        raise DataNotFoundError("akshare", _DOMAIN, f"index_code={index_code} 过滤后无数据")

    if "con_code" in df.columns:
        df["con_code"] = df["con_code"].astype(str).str.zfill(6)
    df["index_code"] = index_code
    df["ts_code"] = index_code
    df["symbol"] = code
    df["data_source"] = "akshare"

    logger.info(f"AKShare 指数成分权重: {index_code} {len(df)} 条")
    return df
