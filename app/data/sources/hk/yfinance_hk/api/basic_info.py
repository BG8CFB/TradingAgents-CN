"""
yfinance HK 港股基础信息 API — Ticker.info 接口封装。
"""
import asyncio
import logging
from typing import Optional

from app.data.sources.base.exceptions import (
    DataFormatError,
    DataNotFoundError,
    DataSourceUnavailableError,
)
from app.data.sources.base.mappers import is_empty_result, map_network_exception

logger = logging.getLogger(__name__)

_DOMAIN = "basic_info"


def _to_yfinance_symbol(symbol: str) -> str:
    """港股代码转 yfinance 格式: 00700 / 0700.HK → 0700.HK"""
    code = str(symbol).replace(".HK", "").lstrip("0").zfill(4)
    return f"{code}.HK"


async def fetch_basic_info(symbol: str) -> Optional[dict]:
    """获取港股基础信息。

    yfinance Ticker.info 返回包含公司名称 / 行业 / 市值等的字典。

    Raises
    ------
    NetworkError
        网络/超时异常（可重试）。
    DataFormatError
        yfinance 返回结构异常（不可重试）。
    DataNotFoundError
        返回空数据（不可重试）。
    DataSourceUnavailableError
        其他未知异常。

    Parameters
    ----------
    symbol : str
        港股代码，支持 "00700" / "0700.HK" 等格式。

    Returns
    -------
    Optional[dict]
        yfinance 返回的原始信息字典。注意：此处返回 dict 而非 DataFrame，
        后续在 adapter 层可按需转换为 DataFrame 或 Schema。
    """
    try:
        import yfinance as yf

        hk_symbol = _to_yfinance_symbol(symbol)

        def _fetch():
            ticker = yf.Ticker(hk_symbol)
            return ticker.info

        info = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        # 网络异常：可重试
        raise map_network_exception(exc, "yfinance_hk", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        # 数据格式异常：yfinance 返回结构不符合预期，不可重试
        raise DataFormatError("yfinance_hk", _DOMAIN, f"{symbol}: {exc}")
    except Exception as exc:
        # 其他未知异常
        raise DataSourceUnavailableError("yfinance_hk", _DOMAIN, f"{symbol}: {exc}")

    # 空结果：业务正确但无数据，不可重试
    if is_empty_result(info):
        logger.warning(f"yfinance_hk 基础信息返回空: {symbol}")
        raise DataNotFoundError("yfinance_hk", _DOMAIN, f"{symbol} 无基础信息")

    logger.info(f"yfinance_hk 基础信息: {symbol}")
    return info
