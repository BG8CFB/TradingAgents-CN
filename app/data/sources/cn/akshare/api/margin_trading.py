"""AKShare 融资融券 API"""
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

_DOMAIN = "margin_trading"


async def fetch_margin_trading(
    symbol: str,
) -> pd.DataFrame:
    """获取个股融资融券数据。

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
            code = symbol.zfill(6)
            # 两融明细当日通常盘后才发布；从最近工作日向前回退，取首个有数据的日期
            for date in _recent_trade_dates(4):
                if code.startswith("6"):
                    # akshare >= 1.18: 签名为 date=<交易日>，返回全市场当日明细后按代码过滤
                    df = ak.stock_margin_detail_sse(date=date)
                    if df is not None and not df.empty:
                        return df[
                            df["标的证券代码"].astype(str).str.zfill(6) == code
                        ]
                elif code.startswith("0") or code.startswith("3"):
                    df = ak.stock_margin_detail_szse(date=date)
                    if df is not None and not df.empty:
                        return df
                else:
                    return None
            return None

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
        logger.warning(f"AKShare 融资融券返回空: symbol={symbol}")
        raise DataNotFoundError("akshare", _DOMAIN, f"symbol={symbol} 无融资融券数据")

    # 深市 stock_margin_detail_szse 按日期返回全市场明细，需按代码过滤到目标个股
    if symbol.startswith("0") or symbol.startswith("3"):
        col = "证券代码" if "证券代码" in df.columns else "代码"
        df = df[df[col].astype(str).str.zfill(6) == symbol.zfill(6)]

    logger.info(f"AKShare 融资融券: {symbol} {len(df)} 条")
    return df


def _recent_trade_dates(n: int = 4) -> list:
    """返回最近 n 个工作日日期字符串列表（YYYYMMDD，从近到远）。

    AKShare 两融明细接口按日期查询全市场，当日数据通常盘后才发布；
    调用方依次尝试，取首个有数据的日期。用简单的工作日回退逻辑，
    避免引入对交易日历的异步依赖。
    """
    from datetime import datetime, timedelta

    dates, day, offset = [], datetime.now(), 0
    while len(dates) < n and offset < 14:
        d = day - timedelta(days=offset)
        if d.weekday() < 5:  # 周一至周五
            dates.append(d.strftime("%Y%m%d"))
        offset += 1
    return dates
