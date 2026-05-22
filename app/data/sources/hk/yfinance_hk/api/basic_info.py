"""
yfinance HK 港股基础信息 API — Ticker.info 接口封装。
"""
import asyncio
import logging
from typing import Optional


logger = logging.getLogger(__name__)


def _to_yfinance_symbol(symbol: str) -> str:
    """港股代码转 yfinance 格式: 00700 / 0700.HK → 0700.HK"""
    code = str(symbol).replace(".HK", "").lstrip("0").zfill(4)
    return f"{code}.HK"


async def fetch_basic_info(symbol: str) -> Optional[dict]:
    """获取港股基础信息。

    yfinance Ticker.info 返回包含公司名称 / 行业 / 市值等的字典。

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
        if info:
            logger.info(f"yfinance HK 基础信息: {symbol}")
        return info
    except Exception as e:
        logger.error(f"yfinance HK 获取基础信息失败: {symbol} - {e}")
        return None
