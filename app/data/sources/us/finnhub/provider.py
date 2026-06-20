"""Finnhub US Provider — 新闻 / 盘前盘后 / 公司概览。"""

import asyncio
import logging
from datetime import datetime, timezone

import pandas as pd

from app.utils.ds_key_utils import get_datasource_api_key

from app.data.sources.base.provider import BaseProvider

logger = logging.getLogger(__name__)


def _get_finnhub_client():
    import finnhub
    api_key = get_datasource_api_key("finnhub")
    if not api_key:
        raise RuntimeError("Finnhub API Key 未配置，请在 Web UI 配置管理中添加")
    return finnhub.Client(api_key=api_key)


class FinnhubUSProvider(BaseProvider):
    """Finnhub 美股数据源 Provider。"""

    def __init__(self):
        super().__init__(name="finnhub", market="US")

    async def connect(self) -> bool:
        self.connected = True
        return True

    def is_available(self) -> bool:
        try:
            import finnhub  # noqa: F401
            return bool(get_datasource_api_key("finnhub"))
        except ImportError:
            return False

    async def get_stock_list(self, **kwargs) -> pd.DataFrame:
        try:
            def _fetch():
                client = _get_finnhub_client()
                symbols = client.stock_symbols(exchange="US")
                return pd.DataFrame(symbols) if symbols else None
            df = await asyncio.to_thread(_fetch)
            if df is not None:
                logger.info(f"Finnhub-US: {len(df)} 只美股")
            return df
        except Exception as e:
            logger.error(f"Finnhub-US 股票列表失败: {e}")
            return None

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        try:
            def _fetch():
                client = _get_finnhub_client()
                # Finnhub 返回的 candle timestamp 是 UTC 秒，查询边界也用 UTC 午夜，
                # 避免宿主机时区导致日期偏移。
                start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
                end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
                candles = client.stock_candles(symbol.upper(), "D", start_ts, end_ts)
                if not candles or candles.get("s") != "ok":
                    return None
                records = []
                for i in range(len(candles["t"])):
                    records.append({
                        "trade_date": datetime.fromtimestamp(candles["t"][i], tz=timezone.utc).strftime("%Y-%m-%d"),
                        "open": candles["o"][i], "high": candles["h"][i],
                        "low": candles["l"][i], "close": candles["c"][i],
                        "volume": candles["v"][i], "symbol": symbol.upper(),
                    })
                return pd.DataFrame(records)

            return await asyncio.to_thread(_fetch)
        except Exception as e:
            logger.error(f"Finnhub-US 行情失败 {symbol}: {e}")
            return None

    async def get_news(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        try:
            def _fetch():
                client = _get_finnhub_client()
                news = client.company_news(
                    symbol.upper(), _from=start_date, to=end_date
                )
                return pd.DataFrame(news[:50]) if news else None

            return await asyncio.to_thread(_fetch)
        except Exception as e:
            logger.debug(f"Finnhub-US 新闻失败 {symbol}: {e}")
            return None

    async def get_market_quotes(
        self, symbols=None, **kwargs
    ) -> pd.DataFrame:
        if not symbols:
            return None
        try:
            symbol = symbols[0].upper()

            def _fetch():
                client = _get_finnhub_client()
                quote = client.quote(symbol)
                return quote if quote and "c" in quote else None

            quote = await asyncio.to_thread(_fetch)
            if not quote:
                return None
            return pd.DataFrame([{
                "symbol": symbol,
                "price": quote.get("c"),
                "change": quote.get("d"),
                "pct_change": quote.get("dp"),
                "volume": quote.get("v"),
                "high": quote.get("h"),
                "low": quote.get("l"),
                "open": quote.get("o"),
                "previous_close": quote.get("pc"),
            }])
        except Exception as e:
            logger.debug(f"Finnhub-US 快照失败: {e}")
            return None
