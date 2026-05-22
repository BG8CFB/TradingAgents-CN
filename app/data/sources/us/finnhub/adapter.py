"""Finnhub US Adapter — 原始数据 → 标准 Schema。"""

import logging
from datetime import datetime
from typing import Any, List

import pandas as pd

from app.data.sources.base.adapter import BaseAdapter
from app.data.schema.base.types import _safe_float, _parse_date
from app.data.schema.domains.basic_info import StockBasicInfoSchema
from app.data.schema.domains.daily_quotes import DailyQuotesSchema
from app.data.schema.domains.stock_news import StockNewsSchema
from app.data.schema.domains.market_quotes import MarketQuotesSchema

logger = logging.getLogger(__name__)


class FinnhubUSAdapter(BaseAdapter):
    """Finnhub 美股数据标准化适配器。"""

    def __init__(self, provider=None):
        super().__init__(provider=provider, market="US", source_name="finnhub")

    def adapt_basic_info(self, raw: Any) -> List[StockBasicInfoSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = str(get("symbol", "") or get("ticker", "")).upper()
            results.append(StockBasicInfoSchema(
                symbol=symbol,
                market="US",
                data_source="finnhub",
                name=get("name", ""),
                full_symbol=symbol,
                exchange=get("exchange", ""),
                industry=get("finnhubIndustry", ""),
                currency="USD",
            ))
        return results

    def adapt_daily_quotes(self, raw: Any) -> List[DailyQuotesSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = str(get("symbol", "")).upper()
            trade_date = _parse_date(get("trade_date", ""))
            if not trade_date:
                continue

            close = _safe_float(get("close"))
            pre_close = _safe_float(get("pre_close"))
            change = _safe_float(get("change"))
            pct_chg = _safe_float(get("pct_change") or get("pct_chg"))

            results.append(DailyQuotesSchema(
                symbol=symbol,
                market="US",
                data_source="finnhub",
                trade_date=trade_date,
                period="daily",
                open=_safe_float(get("open")),
                high=_safe_float(get("high")),
                low=_safe_float(get("low")),
                close=close,
                pre_close=pre_close,
                change=change,
                pct_chg=pct_chg,
                volume=_safe_float(get("volume")),
            ))
        return results

    def adapt_news(self, raw: Any) -> List[StockNewsSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            title = get("headline", "")
            ts = get("datetime", 0)
            publish_time = datetime.fromtimestamp(ts).isoformat() if ts else ""
            content_hash = StockNewsSchema.compute_hash(title, publish_time) if title else None
            results.append(StockNewsSchema(
                symbol=str(get("related", "")).upper(),
                market="US",
                data_source="finnhub",
                title=title,
                content=get("summary", ""),
                content_hash=content_hash,
                source=get("source", ""),
                publish_time=publish_time,
                url=get("url", ""),
            ))
        return results

    def adapt_market_quotes(self, raw: Any) -> List[MarketQuotesSchema]:
        if isinstance(raw, dict):
            symbol = str(raw.get("symbol", "")).upper()
            return [MarketQuotesSchema(
                symbol=symbol,
                market="US",
                data_source="finnhub",
                last_price=_safe_float(raw.get("price") or raw.get("c")),
                last_volume=_safe_float(raw.get("volume") or raw.get("v")),
            )]
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            results.append(MarketQuotesSchema(
                symbol=str(get("symbol", "")).upper(),
                market="US",
                data_source="finnhub",
                last_price=_safe_float(get("price")),
                last_volume=_safe_float(get("volume")),
            ))
        return results
