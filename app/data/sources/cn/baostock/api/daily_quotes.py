"""
BaoStock 日线行情 API
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

logger = logging.getLogger(__name__)

_DOMAIN_DAILY = "daily_quotes"
_DOMAIN_ADJ = "adj_factors"


def _to_baostock_code(symbol: str) -> str:
    """将纯数字代码转为 baostock 格式: sh.600000 / sz.000001"""
    code = str(symbol).zfill(6)
    if code.startswith(("6", "9")):
        return f"sh.{code}"
    return f"sz.{code}"


def _check_rs_error(rs, source: str, domain: str, hint: str) -> None:
    """检查 BaoStock ResultSet 错误码，非 0 抛 DataSourceUnavailableError。

    BaoStock 的 rs.error_code 是字符串 '0' 表示成功，其他数字（6xxxx 系列多为
    网络/系统错误）按系统错误处理。
    """
    if rs is None:
        raise DataSourceUnavailableError(source, domain, f"{hint}: no response")
    err_code = getattr(rs, "error_code", "0")
    if err_code != "0":
        err_msg = getattr(rs, "error_msg", "") or ""
        raise DataSourceUnavailableError(
            source,
            domain,
            f"{hint}: error_code={err_code} {err_msg}".rstrip(),
        )


async def fetch_daily_quotes(
    code: str, start_date: str, end_date: str
) -> Optional[pd.DataFrame]:
    """获取日线行情（前复权）

    异常分类：
    - asyncio.TimeoutError / ConnectionError / TimeoutError → NetworkError
    - rs.error_code != '0' → DataSourceUnavailableError
    - 空结果 → DataNotFoundError
    - DataFrame 组装异常 → DataFormatError
    - 其他 → DataSourceUnavailableError
    """
    bs_code = _to_baostock_code(code)
    start = start_date.replace("-", "")
    end = end_date.replace("-", "")
    hint = f"code={code}"

    def _fetch():
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,code,open,high,low,close,preclose,volume,amount,turn,pctChg",
            start_date=start,
            end_date=end,
            frequency="d",
            adjustflag="2",
        )
        _check_rs_error(rs, "baostock", _DOMAIN_DAILY, hint)
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return None
        return pd.DataFrame(rows, columns=rs.fields)

    try:
        async with baostock_session():
            try:
                df = await asyncio.to_thread(_fetch)
            except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
                raise map_network_exception(exc, "baostock", _DOMAIN_DAILY)
            except (KeyError, ValueError, AttributeError) as exc:
                raise DataFormatError("baostock", _DOMAIN_DAILY, f"{hint}: {exc}")

        if is_empty_result(df):
            logger.warning(f"BaoStock {_DOMAIN_DAILY} 返回空: {hint}")
            raise DataNotFoundError("baostock", _DOMAIN_DAILY, f"{hint} 无数据")

        logger.info(f"BaoStock 行情: {code} {len(df)} 条")
        return df

    except (
        NetworkError,
        DataNotFoundError,
        DataSourceUnavailableError,
        DataFormatError,
    ):
        # 已分类的异常向上抛出，不再吞掉
        raise
    except Exception as exc:
        raise DataSourceUnavailableError(
            "baostock", _DOMAIN_DAILY, f"{hint}: {exc}"
        ) from exc


async def fetch_adj_factors(
    code: str, start_date: str, end_date: str
) -> Optional[pd.DataFrame]:
    """获取复权因子

    异常分类同 fetch_daily_quotes。
    """
    bs_code = _to_baostock_code(code)
    start = start_date.replace("-", "")
    end = end_date.replace("-", "")
    hint = f"code={code}"

    def _fetch():
        rs = bs.query_adjust_factor(
            code=bs_code,
            start_date=start,
            end_date=end,
        )
        _check_rs_error(rs, "baostock", _DOMAIN_ADJ, hint)
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return None
        return pd.DataFrame(rows, columns=rs.fields)

    try:
        async with baostock_session():
            try:
                df = await asyncio.to_thread(_fetch)
            except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
                raise map_network_exception(exc, "baostock", _DOMAIN_ADJ)
            except (KeyError, ValueError, AttributeError) as exc:
                raise DataFormatError("baostock", _DOMAIN_ADJ, f"{hint}: {exc}")

        if is_empty_result(df):
            logger.warning(f"BaoStock {_DOMAIN_ADJ} 返回空: {hint}")
            raise DataNotFoundError("baostock", _DOMAIN_ADJ, f"{hint} 无数据")

        logger.info(f"BaoStock 复权因子: {code} {len(df)} 条")
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
            "baostock", _DOMAIN_ADJ, f"{hint}: {exc}"
        ) from exc
