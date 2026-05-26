"""BaoStock CN Adapter — 原始数据 → 标准 Schema。

BaoStock 返回的 volume 单位是股，amount 单位是元，无需转换。
"""

import logging
from typing import Any, List

import pandas as pd

from app.data.sources.base.adapter import BaseAdapter
from app.data.schema.base.types import _safe_float, _parse_date
from app.data.schema.domains.basic_info import StockBasicInfoSchema
from app.data.schema.domains.daily_quotes import DailyQuotesSchema
from app.data.schema.domains.financial_data import FinancialDataSchema
from app.data.schema.domains.adj_factors import AdjFactorsSchema

logger = logging.getLogger(__name__)


from app.data.sources.cn.stock_name_utils import infer_exchange as _infer_exchange


def _to_bs_code(symbol: str) -> str:
    """标准代码 → BaoStock 代码（带交易所前缀）。"""
    code = str(symbol).zfill(6)
    if code.startswith(("6", "9")):
        return f"sh{code}"
    if code.startswith(("4", "8")):
        logger.warning(f"北交所股票 {code} 不被 BaoStock 支持")
        return ""
    return f"sz{code}"


class BaoStockCNAdapter(BaseAdapter):
    """BaoStock A 股数据标准化适配器。"""

    def __init__(self, provider=None):
        super().__init__(provider=provider, market="CN", source_name="baostock")

    def adapt_basic_info(self, raw: Any) -> List[StockBasicInfoSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = str(get("symbol", "") or get("code", "")).zfill(6)
            # BaoStock code 可能是 "sh.600000" 格式
            if "." in symbol:
                symbol = symbol.split(".")[-1]
            exchange = _infer_exchange(symbol)
            results.append(StockBasicInfoSchema(
                symbol=symbol,
                market="CN",
                data_source="baostock",
                name=get("name", "") or get("code_name", ""),
                full_symbol=f"{symbol}.{exchange}" if exchange else symbol,
                exchange=exchange,
                industry=get("industry") or get("type"),
                list_date=_parse_date(get("list_date") or get("ipoDate")),
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
            raw_code = str(get("symbol", "") or get("code", ""))
            symbol = raw_code.split(".")[-1] if "." in raw_code else raw_code.zfill(6)
            trade_date = _parse_date(get("trade_date") or get("date"))
            if not trade_date:
                continue

            close = _safe_float(get("close"))
            pre_close = _safe_float(get("pre_close") or get("preclose"))
            change = _safe_float(get("change"))
            pct_chg = _safe_float(get("pct_chg"))

            if change is None and close is not None and pre_close is not None:
                change = round(close - pre_close, 4)
            if pct_chg is None and close is not None and pre_close is not None and pre_close != 0:
                pct_chg = round((close - pre_close) / pre_close * 100, 4)

            results.append(DailyQuotesSchema(
                symbol=symbol,
                market="CN",
                data_source="baostock",
                trade_date=trade_date,
                period="daily",
                open=_safe_float(get("open")),
                high=_safe_float(get("high")),
                low=_safe_float(get("low")),
                close=close,
                pre_close=pre_close,
                change=change,
                pct_chg=pct_chg,
                volume=_safe_float(get("volume") or get("vol")),
                amount=_safe_float(get("amount") or get("turnover")),
                turnover_rate=_safe_float(get("turnover_rate") or get("turn")),
            ))
        return results

    def adapt_financial_data(self, raw: Any) -> List[FinancialDataSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            raw_code = str(get("symbol", "") or get("code", ""))
            symbol = raw_code.split(".")[-1] if "." in raw_code else raw_code.zfill(6)
            results.append(FinancialDataSchema(
                symbol=symbol,
                market="CN",
                data_source="baostock",
                report_period=_parse_date(get("report_date") or get("end_date") or get("pubDate")),
                revenue=_safe_float(get("revenue") or get("total_revenue")),
                net_profit=_safe_float(get("net_profit") or get("n_income")),
                total_assets=_safe_float(get("total_assets")),
                total_equity=_safe_float(get("total_equity")),
                roe=_safe_float(get("roe")),
                eps=_safe_float(get("eps")),
            ))
        return results

    def adapt_adj_factors(self, raw: Any) -> List[AdjFactorsSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            raw_code = str(get("code", ""))
            symbol = raw_code.split(".")[-1] if "." in raw_code else raw_code.zfill(6)
            trade_date = _parse_date(get("date"))
            if not trade_date:
                continue

            results.append(AdjFactorsSchema(
                symbol=symbol,
                market="CN",
                data_source="baostock",
                trade_date=trade_date,
                fore_adj_factor=_safe_float(get("foreAdjustFactor")),
                back_adj_factor=_safe_float(get("backAdjustFactor")),
            ))
        return results
