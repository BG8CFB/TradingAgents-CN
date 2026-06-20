"""
BaoStock 财务数据 API（5 个子查询）
"""
import asyncio
import datetime
import logging
from typing import Any, Dict, Optional

import pandas as pd

from app.data.sources.base.exceptions import (
    DataFormatError,
    DataNotFoundError,
    DataSourceError,
    DataSourceUnavailableError,
    NetworkError,
)
from app.data.sources.base.mappers import map_network_exception
from .connection import baostock_session, bs
from .daily_quotes import _check_rs_error, _to_baostock_code

logger = logging.getLogger(__name__)

_DOMAIN = "financial"


async def fetch_financial_data(
    code: str, year: int = None, quarter: int = None
) -> Optional[Dict[str, Any]]:
    """获取多维度财务数据

    异常分类策略：
    - asyncio.TimeoutError / ConnectionError / TimeoutError → NetworkError
    - 单个子查询失败 → 记录并跳过（保持原有容错语义），但用分类异常类型记录
    - 所有子查询均无数据 → DataNotFoundError
    - DataFrame 组装异常 → DataFormatError
    - 其他 → DataSourceUnavailableError
    """
    bs_code = _to_baostock_code(code)
    hint = f"code={code}"

    queries = [
        ("profit", _query_profit),
        ("operation", _query_operation),
        ("growth", _query_growth),
        ("balance", _query_balance),
        ("cashflow", _query_cashflow),
    ]

    try:
        async with baostock_session():
            result: Dict[str, Any] = {"symbol": code, "data_source": "baostock"}

            for name, fn in queries:
                try:
                    df = await asyncio.to_thread(fn, bs_code, year, quarter)
                except (
                    asyncio.TimeoutError,
                    ConnectionError,
                    TimeoutError,
                ) as exc:
                    # 单个财务子查询的网络异常：保持容错，跳过该子域
                    mapped = map_network_exception(
                        exc, "baostock", f"{_DOMAIN}.{name}"
                    )
                    logger.warning(
                        f"BaoStock 财务 {name} 网络异常 {hint}: {mapped.message}"
                    )
                    continue
                except DataSourceError as exc:
                    # _run_query 抛出的分类异常（DataFormatError / DataSourceUnavailableError）
                    logger.warning(
                        f"BaoStock 财务 {name} 失败 {hint}: {exc.message}"
                    )
                    continue
                except Exception as exc:
                    logger.debug(
                        f"BaoStock 获取财务数据 {name} 失败 {hint}: {exc}"
                    )
                    continue

                if df is not None and not df.empty:
                    result[name] = (
                        df.iloc[0].to_dict()
                        if len(df) == 1
                        else df.to_dict("records")
                    )

        if len(result) <= 2:
            logger.warning(f"BaoStock {_DOMAIN} 返回空: {hint}")
            raise DataNotFoundError(
                "baostock",
                _DOMAIN,
                f"{hint} year={year} quarter={quarter} 无财务数据",
            )

        logger.info(
            f"BaoStock 财务: {code} 维度={sorted(k for k in result if k not in ('symbol', 'data_source'))}"
        )
        return result

    except (NetworkError, DataNotFoundError, DataSourceUnavailableError, DataFormatError):
        raise
    except Exception as exc:
        raise DataSourceUnavailableError(
            "baostock", _DOMAIN, f"{hint}: {exc}"
        ) from exc


def _query_profit(code, year, quarter):
    return _run_query(bs.query_profit_data, code, year, quarter)


def _query_operation(code, year, quarter):
    return _run_query(bs.query_operation_data, code, year, quarter)


def _query_growth(code, year, quarter):
    return _run_query(bs.query_growth_data, code, year, quarter)


def _query_balance(code, year, quarter):
    return _run_query(bs.query_balance_data, code, year, quarter)


def _query_cashflow(code, year, quarter):
    return _run_query(bs.query_cash_flow_data, code, year, quarter)


def _run_query(query_fn, code, year, quarter):
    """执行单个 BaoStock 财务查询。

    抛出分类异常：
    - DataSourceUnavailableError：rs.error_code != '0' 或网络/系统错误
    - DataFormatError：组装 DataFrame 时的 KeyError / ValueError / AttributeError
    返回 None 时由上层 fetch_financial_data 判定 DataNotFoundError。
    """
    if year is None:
        year = datetime.datetime.now().year
    if quarter is None:
        quarter = max(1, (datetime.datetime.now().month - 1) // 3)

    rs = query_fn(code=code, year=year, quarter=quarter)
    _check_rs_error(rs, "baostock", _DOMAIN, f"code={code} year={year} q{quarter}")

    try:
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return None
        return pd.DataFrame(rows, columns=rs.fields)
    except (KeyError, ValueError, AttributeError) as exc:
        raise DataFormatError(
            "baostock", _DOMAIN, f"code={code} year={year} q{quarter}: {exc}"
        ) from exc
