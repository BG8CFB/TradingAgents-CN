"""Tencent HK Adapter — 准实时行情 → 标准 Schema。"""

import logging
from typing import Any, List

import pandas as pd

from app.data.sources.base.adapter import BaseAdapter
from app.data.schema.base.types import _safe_float
from app.data.schema.domains.market_quotes import MarketQuotesSchema

logger = logging.getLogger(__name__)


class TencentHKAdapter(BaseAdapter):
    """Tencent 港股准实时行情适配器。"""

    def __init__(self, provider=None):
        super().__init__(provider=provider, market="HK", source_name="tencent_hk")

    def adapt_market_quotes(self, raw: Any) -> List[MarketQuotesSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = str(get("symbol", "")).zfill(5)
            results.append(MarketQuotesSchema(
                symbol=symbol,
                market="HK",
                data_source="tencent_hk",
                last_price=_safe_float(get("price")),
                last_volume=_safe_float(get("volume")),
                last_updated=get("update_time"),
                quote_source_type="realtime",
                bid_price=_safe_float(get("bid")),
                ask_price=_safe_float(get("ask")),
            ))
        return results
