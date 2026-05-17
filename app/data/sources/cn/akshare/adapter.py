"""
AKShare 数据源 Adapter — 原始数据 → Schema 标准格式

AKShare 返回的数据单位已经是标准单位（股/元），一般不需要单位转换。
主要做字段名映射（中文列名 → 英文标准字段名）。
"""

from typing import Any

from app.data.schema.stock_basic_info import StockBasicInfoSchema
from app.data.schema.stock_daily_quotes import StockDailyQuoteSchema
from app.data.schema.base import get_full_symbol
from app.data.sources.base.adapter import BaseAdapter


class AKShareAdapter(BaseAdapter):
    """AKShare 数据标准化适配器"""

    def adapt_basic_info(self, row: Any) -> StockBasicInfoSchema:
        get = row.get
        symbol = str(get("symbol", "") or get("code", "")).zfill(6)
        full_symbol = get("full_symbol") or get_full_symbol(symbol, "CN")

        total_mv = self._safe_float(get("total_mv"))
        circ_mv = self._safe_float(get("circ_mv"))

        return StockBasicInfoSchema(
            symbol=symbol,
            full_symbol=full_symbol,
            name=get("name", ""),
            market="CN",
            exchange=self._infer_exchange(symbol),
            industry=get("industry"),
            area=get("area"),
            list_date=get("list_date"),
            currency="CNY",
            total_mv=total_mv,
            circ_mv=circ_mv,
            pe=self._safe_float(get("pe")),
            pb=self._safe_float(get("pb")),
            turnover_rate=self._safe_float(get("turnover_rate")),
            data_source="akshare",
            updated_at=get("updated_at", ""),
        )

    def adapt_daily_quote(self, row: Any) -> StockDailyQuoteSchema:
        get = row.get
        symbol = str(get("symbol", "") or get("code", "")).zfill(6)
        full_symbol = get_full_symbol(symbol, "CN")
        trade_date = self._format_date(
            get("trade_date") or get("date")
        )

        close = self._safe_float(get("close"))
        pre_close = self._safe_float(get("pre_close"))
        change = self._safe_float(get("change"))
        pct_chg = self._safe_float(get("pct_chg") or get("change_percent"))
        if change is None and close is not None and pre_close is not None:
            change = round(close - pre_close, 4)
        if pct_chg is None and close is not None and pre_close is not None and pre_close != 0:
            pct_chg = round((close - pre_close) / pre_close * 100, 4)

        return StockDailyQuoteSchema(
            symbol=symbol,
            full_symbol=full_symbol,
            trade_date=trade_date or "",
            period="daily",
            open=self._safe_float(get("open")),
            high=self._safe_float(get("high")),
            low=self._safe_float(get("low")),
            close=close,
            pre_close=pre_close,
            volume=self._safe_float(get("volume") or get("vol")),
            amount=self._safe_float(get("amount") or get("turnover")),
            change=change,
            pct_chg=pct_chg,
            turnover_rate=self._safe_float(get("turnover_rate")),
            data_source="akshare",
            created_at=get("created_at", ""),
            updated_at=get("updated_at", ""),
        )

    @staticmethod
    def _infer_exchange(symbol: str) -> str:
        if symbol.startswith(("60", "68", "90")):
            return "SSE"
        elif symbol.startswith(("00", "30", "20")):
            return "SZSE"
        elif symbol.startswith(("4", "8")):
            return "BSE"
        return ""

    @staticmethod
    def _format_date(value) -> str:
        if value is None:
            return None
        s = str(value).strip()
        if len(s) == 8 and s.isdigit():
            return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        if len(s) >= 10:
            return s[:10]
        return s
