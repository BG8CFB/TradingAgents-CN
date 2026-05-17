"""
Tushare 数据源 Adapter

职责：将 TushareProvider 返回的原始数据转换为 Schema 标准格式。

关键转换规则：
- 股票代码：ts_code "000001.SZ" → symbol "000001"
- 成交量：手 → 股（×100）
- 成交额：千元 → 元（×1000）
- 市值：万元 → 亿元（÷10000）
"""

from typing import Any, Dict, Optional

from app.data.schema.stock_basic_info import StockBasicInfoSchema
from app.data.schema.stock_daily_quotes import StockDailyQuoteSchema
from app.data.schema.base import get_full_symbol

from app.data.sources.base.adapter import BaseAdapter


class TushareAdapter(BaseAdapter):
    """Tushare 数据标准化适配器"""

    def _parse_symbol_from_ts_code(self, ts_code: str) -> str:
        """从 ts_code 提取 6 位股票代码（如 '000001.SZ' → '000001'）"""
        if isinstance(ts_code, str) and "." in ts_code:
            return ts_code.split(".")[0]
        return str(ts_code).zfill(6)

    def _parse_exchange_from_ts_code(self, ts_code: str) -> str:
        """从 ts_code 解析交易所"""
        if not isinstance(ts_code, str) or "." not in ts_code:
            return ""
        suffix = ts_code.split(".")[1].upper()
        mapping = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}
        return mapping.get(suffix, suffix)

    # ── 基础信息适配 ──

    def adapt_basic_info(self, row: Any) -> StockBasicInfoSchema:
        """
        将 Tushare 原始行数据转换为 StockBasicInfoSchema

        输入格式（Tushare stock_basic 返回）:
            ts_code, symbol, name, area, industry, market, list_date, ...

        同时接收 daily_basic 的补充字段：total_mv, circ_mv, pe, pb, turnover_rate 等
        """
        if hasattr(row, "get"):
            get = row.get
        elif hasattr(row, "__getitem__"):
            get = lambda k: row[k] if k in (row.index if hasattr(row, 'index') else row) else None
            # pandas Series
            get = row.get
        else:
            get = lambda k: getattr(row, k, None)

        ts_code = get("ts_code", "")
        symbol = str(get("symbol", "") or self._parse_symbol_from_ts_code(str(ts_code))).zfill(6)
        exchange = self._parse_exchange_from_ts_code(str(ts_code))
        full_symbol = get("full_symbol") or get_full_symbol(symbol, "CN")

        # 市值转换：万元 → 亿元
        total_mv = self._safe_float(get("total_mv"))
        if total_mv is not None:
            total_mv = total_mv / 10000.0
        circ_mv = self._safe_float(get("circ_mv"))
        if circ_mv is not None:
            circ_mv = circ_mv / 10000.0

        return StockBasicInfoSchema(
            symbol=symbol,
            full_symbol=full_symbol,
            name=get("name", ""),
            market="CN",
            exchange=exchange,
            industry=get("industry"),
            area=get("area"),
            list_date=self._format_date(get("list_date")),
            currency="CNY",
            total_mv=total_mv,
            circ_mv=circ_mv,
            pe=self._safe_float(get("pe")),
            pe_ttm=self._safe_float(get("pe_ttm")),
            pb=self._safe_float(get("pb")),
            pb_mrq=self._safe_float(get("pb_mrq")),
            ps=self._safe_float(get("ps")),
            ps_ttm=self._safe_float(get("ps_ttm")),
            roe=self._safe_float(get("roe")),
            turnover_rate=self._safe_float(get("turnover_rate")),
            volume_ratio=self._safe_float(get("volume_ratio")),
            total_shares=self._safe_float(get("total_share")),
            float_shares=self._safe_float(get("float_share")),
            data_source="tushare",
            updated_at=get("updated_at", ""),
        )

    # ── 行情数据适配 ──

    def adapt_daily_quote(self, row: Any) -> StockDailyQuoteSchema:
        """
        将 Tushare 日线原始行转换为 StockDailyQuoteSchema

        关键单位转换：
        - vol: 手 → 股（×100）
        - amount: 千元 → 元（×1000）
        """
        get = row.get

        symbol = str(get("symbol", "") or get("ts_code", "")).zfill(6)
        if "." in symbol:
            symbol = symbol.split(".")[0]
        full_symbol = get_full_symbol(symbol, "CN")
        trade_date = self._format_date(get("trade_date"))

        # 单位转换
        volume = self._safe_float(get("vol") or get("volume"))
        if volume is not None:
            volume = volume * 100  # 手 → 股

        amount = self._safe_float(get("amount") or get("turnover"))
        if amount is not None:
            amount = amount * 1000  # 千元 → 元

        close = self._safe_float(get("close"))
        pre_close = self._safe_float(get("pre_close") or get("preclose"))

        # 计算涨跌
        change = self._safe_float(get("change"))
        pct_chg = self._safe_float(get("pct_chg") or get("change_percent"))
        if change is None and close is not None and pre_close is not None:
            change = round(close - pre_close, 4)
        if pct_chg is None and close is not None and pre_close is not None and pre_close != 0:
            pct_chg = round((close - pre_close) / pre_close * 100, 4)

        return StockDailyQuoteSchema(
            symbol=symbol,
            full_symbol=full_symbol,
            trade_date=trade_date,
            period="daily",
            open=self._safe_float(get("open")),
            high=self._safe_float(get("high")),
            low=self._safe_float(get("low")),
            close=close,
            pre_close=pre_close,
            volume=volume,
            amount=amount,
            change=change,
            pct_chg=pct_chg,
            turnover_rate=self._safe_float(get("turn") or get("turnover_rate")),
            data_source="tushare",
            created_at=get("created_at", ""),
            updated_at=get("updated_at", ""),
        )

    # ── 工具方法 ──

    @staticmethod
    def _format_date(value) -> Optional[str]:
        """格式化日期为 YYYY-MM-DD"""
        if value is None:
            return None
        s = str(value).strip()
        if len(s) == 8 and s.isdigit():  # YYYYMMDD
            return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        if len(s) == 10 and "-" in s:  # Already YYYY-MM-DD
            return s
        return s
