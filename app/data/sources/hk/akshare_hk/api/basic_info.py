"""
AKShare HK 港股基础信息 API — stock_hk_spot_em 接口封装。
"""
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

_DOMAIN = "basic_info"


async def fetch_stock_list() -> Optional[pd.DataFrame]:
    """获取港股全市场实时行情快照（东方财富数据源）。

    AKShare 的 stock_hk_spot_em() 返回所有港股的实时快照数据，
    包含 代码 / 名称 / 最新价 / 涨跌幅 / 成交量 等。

    Raises
    ------
    NetworkError
        网络/超时异常（可重试）。
    DataFormatError
        AKShare 返回结构异常（不可重试）。
    DataNotFoundError
        返回空数据（不可重试）。
    DataSourceUnavailableError
        其他未知异常。

    Returns
    -------
    Optional[pd.DataFrame]
        原始 DataFrame，包含 代码 / 名称 / 最新价 等中文列名。
    """
    try:
        import akshare as ak

        df = await asyncio.to_thread(ak.stock_hk_spot_em)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        # 网络异常：可重试
        raise map_network_exception(exc, "akshare_hk", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        # 数据格式异常：AKShare 返回结构不符合预期，不可重试
        raise DataFormatError("akshare_hk", _DOMAIN, str(exc))
    except Exception as exc:
        # 其他未知异常
        raise DataSourceUnavailableError("akshare_hk", _DOMAIN, str(exc))

    # 空结果：业务正确但无数据，不可重试
    if is_empty_result(df):
        logger.warning("akshare_hk 股票列表返回空数据")
        raise DataNotFoundError("akshare_hk", _DOMAIN, "港股列表无数据")

    logger.info(f"akshare_hk 获取股票列表: {len(df)} 只")
    return df
