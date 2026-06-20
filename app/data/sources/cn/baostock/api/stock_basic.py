"""
BaoStock 股票基础信息 API
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

from app.data.sources.base.exceptions import (
    DataFormatError,
    DataNotFoundError,
    DataSourceUnavailableError,
    NetworkError,
)
from app.data.sources.base.mappers import is_empty_result, map_network_exception
from .connection import baostock_session, bs
from .daily_quotes import _check_rs_error

logger = logging.getLogger(__name__)

_DOMAIN = "stock_basic"


async def fetch_stock_list() -> Optional[pd.DataFrame]:
    """获取 A 股股票列表

    异常分类：
    - asyncio.TimeoutError / ConnectionError / TimeoutError → NetworkError
    - rs.error_code != '0' → DataSourceUnavailableError
    - 空结果 → DataNotFoundError
    - DataFrame 组装异常 → DataFormatError
    - 其他 → DataSourceUnavailableError
    """

    def _fetch():
        rs = bs.query_stock_basic()
        _check_rs_error(rs, "baostock", _DOMAIN, "stock_list")
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=rs.fields)
        return df[df["type"] == "1"]

    try:
        async with baostock_session():
            try:
                df = await asyncio.to_thread(_fetch)
            except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
                raise map_network_exception(exc, "baostock", _DOMAIN)
            except (KeyError, ValueError, AttributeError) as exc:
                raise DataFormatError("baostock", _DOMAIN, str(exc))

        if is_empty_result(df):
            logger.warning(f"BaoStock {_DOMAIN} 返回空: 股票列表无数据")
            raise DataNotFoundError(
                "baostock", _DOMAIN, "query_stock_basic 返回空"
            )

        # 去掉 sh./sz. 前缀
        if "code" in df.columns:
            df["code"] = df["code"].str.replace(r"^(sh|sz)\.", "", regex=True)
        logger.info(f"BaoStock 股票列表: {len(df)} 只")
        return df

    except (
        NetworkError,
        DataNotFoundError,
        DataSourceUnavailableError,
        DataFormatError,
    ):
        raise
    except Exception as exc:
        raise DataSourceUnavailableError(
            "baostock", _DOMAIN, str(exc)
        ) from exc
