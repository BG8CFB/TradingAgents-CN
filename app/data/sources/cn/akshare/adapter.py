"""AKShare CN Adapter — 原始数据 → 标准 Schema。

AKShare 返回的数据单位已是标准单位（股/元），主要做字段名映射。
"""

import logging
from typing import Any, List

import pandas as pd

from app.data.sources.base.adapter import BaseAdapter
from app.data.schema.base.types import _safe_float, _parse_date
from app.data.schema.domains.basic_info import StockBasicInfoSchema
from app.data.schema.domains.daily_quotes import DailyQuotesSchema
from app.data.schema.domains.financial_data import FinancialDataSchema
from app.data.schema.domains.stock_news import StockNewsSchema
from app.data.schema.domains.market_quotes import MarketQuotesSchema

logger = logging.getLogger(__name__)


def _infer_exchange(symbol: str) -> str:
    if symbol.startswith(("60", "68", "90")):
        return "SSE"
    elif symbol.startswith(("00", "30", "20")):
        return "SZSE"
    elif symbol.startswith(("4", "8")):
        return "BSE"
    return ""


class AKShareCNAdapter(BaseAdapter):
    """AKShare A 股数据标准化适配器。"""

    def __init__(self, provider=None):
        super().__init__(provider=provider, market="CN", source_name="akshare")

    def adapt_basic_info(self, raw: Any) -> List[StockBasicInfoSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = str(get("symbol", "") or get("code", "")).zfill(6)
            exchange = _infer_exchange(symbol)
            results.append(StockBasicInfoSchema(
                symbol=symbol,
                market="CN",
                data_source="akshare",
                name=get("name", ""),
                full_symbol=f"{symbol}.{exchange}" if exchange else symbol,
                exchange=exchange,
                industry=get("industry"),
                list_date=_parse_date(get("list_date")),
                currency="CNY",
            ))
        return results

    def adapt_daily_quotes(self, raw: Any) -> List[DailyQuotesSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = str(get("symbol", "") or get("code", "")).zfill(6)
            trade_date = _parse_date(get("trade_date") or get("日期") or get("date"))
            if not trade_date:
                continue

            close = _safe_float(get("close") or get("收盘"))
            pre_close = _safe_float(get("pre_close"))
            change = _safe_float(get("change"))
            pct_chg = _safe_float(get("pct_chg") or get("change_percent") or get("涨跌幅"))
            if change is None and close is not None and pre_close is not None:
                change = round(close - pre_close, 4)
            if pct_chg is None and close is not None and pre_close is not None and pre_close != 0:
                pct_chg = round((close - pre_close) / pre_close * 100, 4)

            results.append(DailyQuotesSchema(
                symbol=symbol,
                market="CN",
                data_source="akshare",
                trade_date=trade_date,
                period="daily",
                open=_safe_float(get("open") or get("开盘")),
                high=_safe_float(get("high") or get("最高")),
                low=_safe_float(get("low") or get("最低")),
                close=close,
                pre_close=pre_close,
                change=change,
                pct_chg=pct_chg,
                volume=_safe_float(get("volume") or get("vol") or get("成交量")),
                amount=_safe_float(get("amount") or get("turnover") or get("成交额")),
                turnover_rate=_safe_float(get("turnover_rate") or get("换手率")),
            ))
        return results

    def adapt_financial_data(self, raw: Any) -> List[FinancialDataSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = str(get("symbol", "") or get("code", "")).zfill(6)
            results.append(FinancialDataSchema(
                symbol=symbol,
                market="CN",
                data_source="akshare",
                report_period=_parse_date(get("report_date") or get("end_date")),
                revenue=_safe_float(get("revenue") or get("营业收入")),
                net_profit=_safe_float(get("net_profit") or get("净利润")),
                total_assets=_safe_float(get("total_assets")),
                total_equity=_safe_float(get("total_equity") or get("所有者权益合计")),
                roe=_safe_float(get("roe")),
                gross_margin=_safe_float(get("gross_margin")),
                net_margin=_safe_float(get("net_margin")),
                eps=_safe_float(get("eps") or get("basic_eps")),
                bps=_safe_float(get("bps")),
            ))
        return results

    def adapt_news(self, raw: Any) -> List[StockNewsSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            title = get("title", "") or get("标题", "")
            publish_time = get("datetime", "") or get("publish_time", "") or get("发布时间", "")
            content_hash = StockNewsSchema.compute_hash(title, str(publish_time)) if title else None
            results.append(StockNewsSchema(
                symbol=str(get("symbol", "")),
                market="CN",
                data_source="akshare",
                title=title,
                content=get("content") or get("内容"),
                content_hash=content_hash,
                source=get("source") or get("来源", ""),
                publish_time=publish_time,
                url=get("url") or get("链接"),
            ))
        return results

    def adapt_market_quotes(self, raw: Any) -> List[MarketQuotesSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = str(get("symbol", "") or get("code", "")).zfill(6)
            results.append(MarketQuotesSchema(
                symbol=symbol,
                market="CN",
                data_source="akshare",
                last_price=_safe_float(get("price") or get("最新价") or get("close")),
                last_volume=_safe_float(get("volume") or get("成交量")),
            ))
        return results
