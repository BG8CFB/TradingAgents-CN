"""yfinance HK 港股财务数据 API — Ticker.financials 接口封装。"""
import asyncio
import logging
from typing import Optional

import pandas as pd

from app.data.sources.base.exceptions import (
    DataFormatError,
    DataNotFoundError,
    DataSourceUnavailableError,
)
from app.data.sources.base.mappers import is_empty_result, map_network_exception

logger = logging.getLogger(__name__)

_DOMAIN = "financial_data"


def _to_yfinance_symbol(symbol: str) -> str:
    """港股代码转 yfinance 格式: 00700 / 0700.HK → 0700.HK"""
    code = str(symbol).replace(".HK", "").lstrip("0").zfill(4)
    return f"{code}.HK"


async def fetch_financial_data(
    symbol: str,
    statement_type: str = "income",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Optional[pd.DataFrame]:
    """获取港股财务数据（利润表）。

    yfinance 的 ``Ticker.financials`` 返回年度利润表 DataFrame，索引为指标名，
    列为报告期日期。``start_date`` / ``end_date`` 用于在内存中过滤列（日期）。

    Parameters
    ----------
    symbol : str
        港股代码，支持 "00700" / "0700.HK" 等格式。
    statement_type : str
        报表类型；yfinance 目前仅暴露 income（忽略其他类型，仍返回 financials）。
    start_date, end_date : Optional[str]
        报告期范围（ISO YYYY-MM-DD），未提供则不过滤。

    Returns
    -------
    Optional[pd.DataFrame]
        原始 DataFrame，``df.attrs["symbol"]`` 携带标准化 symbol 便于下游 adapter 使用。
    """
    try:
        import yfinance as yf

        hk_symbol = _to_yfinance_symbol(symbol)

        def _fetch():
            ticker = yf.Ticker(hk_symbol)
            return ticker.financials

        df = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "yfinance_hk", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        raise DataFormatError("yfinance_hk", _DOMAIN, f"{symbol}: {exc}")
    except Exception as exc:
        raise DataSourceUnavailableError("yfinance_hk", _DOMAIN, f"{symbol}: {exc}")

    if is_empty_result(df):
        logger.warning(f"yfinance_hk 返回空财务数据: {symbol}")
        raise DataNotFoundError("yfinance_hk", _DOMAIN, f"{symbol} 无财务数据")

    if start_date and end_date:
        try:
            cols = pd.to_datetime(df.columns)
            mask = (cols >= pd.to_datetime(start_date)) & (
                cols <= pd.to_datetime(end_date)
            )
            df = df.loc[:, mask]
            if df.empty:
                logger.warning(
                    f"yfinance_hk 日期过滤后无财务数据: {symbol} "
                    f"{start_date}~{end_date}"
                )
                raise DataNotFoundError(
                    "yfinance_hk",
                    _DOMAIN,
                    f"{symbol} 日期范围 {start_date}~{end_date} 无财务数据",
                )
        except DataNotFoundError:
            raise
        except Exception as exc:
            raise DataFormatError("yfinance_hk", _DOMAIN, f"{symbol}: {exc}")

    df.attrs["symbol"] = str(symbol).replace(".HK", "").lstrip("0").zfill(5)
    logger.info(f"yfinance_hk 获取财务数据: {symbol} {len(df.columns)} 期")
    return df
