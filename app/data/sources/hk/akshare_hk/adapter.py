"""AKShare HK Adapter — 原始数据 → 标准 Schema。"""

import logging
from typing import Any, List

import pandas as pd

from app.data.sources.base.adapter import BaseAdapter
from app.data.schema.base.types import _safe_float, _parse_date
from app.data.schema.domains.basic_info import StockBasicInfoSchema
from app.data.schema.domains.daily_quotes import DailyQuotesSchema
from app.data.schema.domains.corporate_actions import CorporateActionsSchema
from app.data.schema.domains.stock_news import StockNewsSchema
from app.data.schema.domains.market_quotes import MarketQuotesSchema

logger = logging.getLogger(__name__)


class AKShareHKAdapter(BaseAdapter):
    """AKShare 港股数据标准化适配器。"""

    def __init__(self, provider=None):
        super().__init__(provider=provider, market="HK", source_name="akshare_hk")

    def adapt_basic_info(self, raw: Any) -> List[StockBasicInfoSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            code_col = "代码" if "代码" in df.columns else "symbol"
            symbol = str(get(code_col, "") or get("symbol", "")).zfill(5)
            results.append(StockBasicInfoSchema(
                symbol=symbol,
                market="HK",
                data_source="akshare_hk",
                name=get("名称", "") or get("name", ""),
                full_symbol=f"{symbol}.HK",
                exchange="HKEX",
                industry=get("industry") or get("所属行业", ""),
                list_status="L",
                currency="HKD",
            ))
        return results

    def adapt_daily_quotes(self, raw: Any) -> List[DailyQuotesSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = str(get("symbol", "") or get("代码", "")).zfill(5)
            date_col = "日期" if "日期" in df.columns else "date"
            trade_date = _parse_date(get(date_col, ""))
            if not trade_date:
                continue

            close = _safe_float(get("收盘", "") or get("close"))
            pre_close = _safe_float(get("pre_close"))
            change = _safe_float(get("涨跌额", "") or get("change"))
            pct_chg = _safe_float(get("涨跌幅", "") or get("pct_chg"))

            results.append(DailyQuotesSchema(
                symbol=symbol,
                market="HK",
                data_source="akshare_hk",
                trade_date=trade_date,
                period="daily",
                open=_safe_float(get("开盘", "") or get("open")),
                high=_safe_float(get("最高", "") or get("high")),
                low=_safe_float(get("最低", "") or get("low")),
                close=close,
                pre_close=pre_close,
                change=change,
                pct_chg=pct_chg,
                volume=_safe_float(get("成交量", "") or get("volume")),
                amount=_safe_float(get("成交额", "") or get("amount")),
                turnover_rate=_safe_float(get("换手率", "") or get("turnover_rate")),
            ))
        return results

    def adapt_corporate_actions(self, raw: Any) -> List[CorporateActionsSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = str(get("symbol", "") or get("代码", "")).zfill(5)
            ex_date = _parse_date(get("除净日", "") or get("ex_date"))
            action_type = self._map_action_type(get("类型", "") or get("action_type", ""))

            results.append(CorporateActionsSchema(
                symbol=symbol,
                market="HK",
                data_source="akshare_hk",
                ex_date=ex_date,
                action_type=action_type,
                amount=_safe_float(get("派息", "") or get("amount")),
                currency="HKD",
                ratio_from=_safe_float(get("送股比例", "") or get("ratio_from")),
                ratio_to=_safe_float(get("ratio_to")),
                rights_price=_safe_float(get("供股价", "") or get("rights_price")),
            ))
        return results

    def adapt_news(self, raw: Any) -> List[StockNewsSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            title = get("标题", "") or get("title", "")
            publish_time = (
                get("公告日期", "") or get("发布时间", "") or get("publish_time", "")
            )
            content_hash = StockNewsSchema.compute_hash(title, str(publish_time)) if title else None
            raw_symbol = str(get("symbol", "") or get("股票代码", ""))
            results.append(StockNewsSchema(
                symbol=raw_symbol.zfill(5) if raw_symbol else "",
                market="HK",
                data_source="akshare_hk",
                title=title,
                content=get("内容", "") or get("摘要", "") or get("content"),
                content_hash=content_hash,
                source=get("来源", "") or "hkexnews",
                publish_time=publish_time,
                url=get("链接", "") or get("url"),
            ))
        return results

    def adapt_market_quotes(self, raw: Any) -> List[MarketQuotesSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            code_col = "代码" if "代码" in df.columns else "symbol"
            symbol = str(get(code_col, "") or get("symbol", "")).zfill(5)
            results.append(MarketQuotesSchema(
                symbol=symbol,
                market="HK",
                data_source="akshare_hk",
                last_price=_safe_float(get("最新价", "") or get("close") or get("price")),
                last_volume=_safe_float(get("成交量", "") or get("volume")),
                turnover_rate=_safe_float(get("换手率", "") or get("turnover_rate")),
            ))
        return results

    @staticmethod
    def _map_action_type(raw_type: str) -> str:
        mapping = {
            "分红": "cash_dividend", "派息": "cash_dividend",
            "特别息": "special_dividend",
            "拆股": "stock_split", "拆细": "stock_split",
            "合股": "consolidation",
            "送股": "bonus_issue", "红股": "bonus_issue",
            "供股": "rights_issue",
        }
        for key, val in mapping.items():
            if key in raw_type:
                return val
        return raw_type if raw_type else "unknown"
