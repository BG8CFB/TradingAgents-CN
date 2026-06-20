"""AKShare 资金流向 API"""
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

_DOMAIN = "money_flow"


async def fetch_money_flow_by_symbol(
    symbol: str,
) -> pd.DataFrame:
    """获取个股资金流向。

    Args:
        symbol: 6位股票代码（不带后缀）

    Raises:
        NetworkError: 网络/超时异常（可重试）
        DataFormatError: AKShare 返回结构异常（不可重试）
        DataNotFoundError: 返回空数据（不可重试）
        DataSourceUnavailableError: 其他未知异常
    """
    try:
        import akshare as ak

        def _fetch():
            from app.data.sources.cn.akshare.api.anti_scraping import wait_rate_limit
            wait_rate_limit()
            return ak.stock_individual_fund_flow(stock=symbol, market="sh" if symbol.startswith("6") else "sz")

        df = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        # 网络异常：可重试
        raise map_network_exception(exc, "akshare", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        # 数据格式异常：AKShare 返回结构不符合预期，不可重试
        raise DataFormatError("akshare", _DOMAIN, f"symbol={symbol}: {exc}")
    except Exception as exc:
        # 其他未知异常
        raise DataSourceUnavailableError("akshare", _DOMAIN, f"symbol={symbol}: {exc}")

    # 空结果：业务正确但无数据，不可重试
    if is_empty_result(df):
        logger.warning(f"AKShare 资金流向返回空: symbol={symbol}")
        raise DataNotFoundError("akshare", _DOMAIN, f"symbol={symbol} 无资金流向数据")

    logger.info(f"AKShare 资金流向: {symbol} {len(df)} 条")
    return df
