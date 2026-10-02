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

    logger.debug(f"AKShare 资金流向: {symbol} {len(df)} 条")
    return df


async def fetch_money_flow_rank(trade_date: str) -> pd.DataFrame:
    """全市场资金流排名（东财 ak.stock_individual_fund_flow_rank）。

    该接口只提供「今日」快照且不含日期列，历史日期不可查：调用方传入
    trade_date，非当日直接抛 DataNotFoundError（批量同步按日循环时跳过）；
    当日则把日期注入为「日期」列以满足 adapt_money_flow 的 trade_date 契约。
    单位与逐股接口一致（元），adapter 直接映射。
    """
    from datetime import datetime

    from app.data.core.market import get_market_timezone

    date_str = str(trade_date).replace("-", "")
    today = datetime.now(get_market_timezone("CN")).strftime("%Y%m%d")
    if date_str != today:
        raise DataNotFoundError(
            "akshare", _DOMAIN, f"排名接口仅支持当日数据: {trade_date}"
        )

    try:
        import akshare as ak

        def _fetch():
            from app.data.sources.cn.akshare.api.anti_scraping import wait_rate_limit
            wait_rate_limit()
            return ak.stock_individual_fund_flow_rank(indicator="今日")

        df = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "akshare", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        raise DataFormatError("akshare", _DOMAIN, f"rank: {exc}")
    except Exception as exc:
        raise DataSourceUnavailableError("akshare", _DOMAIN, f"rank: {exc}")

    if is_empty_result(df):
        logger.warning("AKShare 资金流排名返回空")
        raise DataNotFoundError("akshare", _DOMAIN, "资金流排名无数据")

    df["日期"] = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    logger.info(f"AKShare 资金流排名: {len(df)} 条")
    return df
