"""
AKShare 指数基本信息 API — 通过 index_csindex_all（中证指数）获取。

作为 tushare index_basic 的备用源（全市场指数基本信息快照）。
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
_DOMAIN = "index_basic"

# akshare index_csindex_all 列名 -> index_basic 标准列名（按需存在则重命名）
_COLUMN_MAPPER = {
    "指数代码": "ts_code",
    "指数名称": "name",
    "指数英文名称": "name_en",
}


async def fetch_index_basic(
    market: str = None,
    category: str = None,
) -> pd.DataFrame:
    """获取指数基本信息（AKShare 回退源）。"""
    try:
        import akshare as ak

        from app.data.sources.cn.akshare.api.anti_scraping import wait_rate_limit

        def _fetch():
            wait_rate_limit()
            return ak.index_csindex_all()

        df = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "akshare", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        raise DataFormatError("akshare", _DOMAIN, f"{exc}")
    except Exception as exc:
        raise DataSourceUnavailableError("akshare", _DOMAIN, f"{exc}")

    if is_empty_result(df):
        raise DataNotFoundError("akshare", _DOMAIN, "无指数基本信息")

    df = df.rename(columns=_COLUMN_MAPPER)

    if "ts_code" in df.columns:
        df["ts_code"] = df["ts_code"].astype(str)
        df["symbol"] = df["ts_code"].str.split(".").str[0]

    df["market"] = "CN"
    df["data_source"] = "akshare"

    logger.info(f"AKShare 指数基本信息: {len(df)} 条")
    return df
