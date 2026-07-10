"""AKShare 涨停板（连板）行情 API

AKShare stock_zt_pool_em 按交易日拉取涨停股池，含连板数等字段，
对应 limit_step 域。
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
_DOMAIN = "limit_step"


async def fetch_limit_step(
    trade_date: str = None,
    start_date: str = None,
    end_date: str = None,
) -> pd.DataFrame:
    """获取涨停板（连板）行情。

    Args:
        trade_date: 交易日 YYYY-MM-DD（优先）
        start_date / end_date: 未使用，AKShare 按单日查询

    Raises:
        DataNotFoundError: 未提供查询日期或无数据
        NetworkError / DataFormatError / DataSourceUnavailableError
    """
    date = trade_date or end_date
    if not date:
        raise DataNotFoundError("akshare", _DOMAIN, "未提供查询日期")
    date_fmt = str(date).replace("-", "")

    try:
        import akshare as ak

        def _fetch():
            from app.data.sources.cn.akshare.api.anti_scraping import wait_rate_limit
            wait_rate_limit()
            return ak.stock_zt_pool_em(date=date_fmt)

        df = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "akshare", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        raise DataFormatError("akshare", _DOMAIN, f"date={date}: {exc}")
    except Exception as exc:
        raise DataSourceUnavailableError("akshare", _DOMAIN, f"date={date}: {exc}")

    if is_empty_result(df):
        raise DataNotFoundError("akshare", _DOMAIN, f"date={date} 无涨停股池数据")

    df = df.copy()
    df["trade_date"] = date
    return df.reset_index(drop=True)
