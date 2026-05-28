"""Tushare CN Adapter — 原始数据 → 标准 Schema。

转换规则：
- ts_code "000001.SZ" → symbol "000001"
- vol: 手 → 股（×100）
- amount: 千元 → 元（×1000）
- total_mv/circ_mv (daily_basic): 万元 → 元（×10000）
"""

import logging
from typing import Any, List

import pandas as pd

from app.data.sources.base.adapter import BaseAdapter
from app.data.schema.base.types import _safe_float, _parse_date
from app.data.schema.domains.basic_info import StockBasicInfoSchema
from app.data.schema.domains.trade_calendar import TradeCalendarSchema
from app.data.schema.domains.daily_quotes import DailyQuotesSchema
from app.data.schema.domains.daily_indicators import DailyIndicatorsSchema
from app.data.schema.domains.adj_factors import AdjFactorsSchema
from app.data.schema.domains.financial_data import FinancialDataSchema
from app.data.schema.domains.stock_news import StockNewsSchema
from app.data.schema.domains.market_quotes import MarketQuotesSchema
from app.data.schema.domains.money_flow import MoneyFlowSchema
from app.data.schema.domains.margin_trading import MarginTradingSchema
from app.data.schema.domains.dragon_tiger import DragonTigerSchema
from app.data.schema.domains.block_trade import BlockTradeSchema
from app.data.schema.domains.intraday_quotes import IntradayQuotesSchema

logger = logging.getLogger(__name__)


def _parse_symbol_from_ts_code(ts_code: str) -> str:
    if isinstance(ts_code, str) and "." in ts_code:
        return ts_code.split(".")[0]
    return str(ts_code).zfill(6)


def _parse_exchange(ts_code: str) -> str:
    if not isinstance(ts_code, str) or "." not in ts_code:
        return ""
    suffix = ts_code.split(".")[1].upper()
    return {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}.get(suffix, suffix)


from app.data.sources.cn.stock_name_utils import infer_exchange as _infer_exchange


class TushareCNAdapter(BaseAdapter):
    """Tushare A 股数据标准化适配器。"""

    def __init__(self, provider=None):
        super().__init__(provider=provider, market="CN", source_name="tushare")

    # ── basic_info ──

    def adapt_basic_info(self, raw: Any) -> List[StockBasicInfoSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            ts_code = str(get("ts_code", ""))
            symbol = str(get("symbol", "") or _parse_symbol_from_ts_code(ts_code)).zfill(6)
            results.append(StockBasicInfoSchema(
                symbol=symbol,
                market="CN",
                data_source="tushare",
                name=get("name", ""),
                full_symbol=f"{symbol}.{_parse_exchange(ts_code)}" if _parse_exchange(ts_code) else symbol,
                exchange=_parse_exchange(ts_code),
                industry=get("industry"),
                list_status=get("list_status"),
                list_date=_parse_date(get("list_date")),
                delist_date=_parse_date(get("delist_date")),
                currency="CNY",
            ))
        return results

    # ── trade_calendar ──

    def adapt_trade_calendar(self, raw: Any) -> List[TradeCalendarSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            cal_date = _parse_date(get("cal_date"))
            if not cal_date:
                continue
            results.append(TradeCalendarSchema(
                symbol="__calendar__",
                market="CN",
                data_source="tushare",
                exchange=get("exchange", "SSE"),
                cal_date=cal_date,
                is_open=bool(get("is_open", 1)),
                pretrade_date=_parse_date(get("pretrade_date")),
            ))
        return results

    # ── daily_quotes ──

    def adapt_daily_quotes(self, raw: Any) -> List[DailyQuotesSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = _parse_symbol_from_ts_code(str(get("ts_code", "")))
            trade_date = _parse_date(get("trade_date"))
            if not trade_date:
                continue

            # 单位转换: 手→股, 千元→元
            volume = _safe_float(get("vol") or get("volume"))
            if volume is not None:
                volume = volume * 100

            amount = _safe_float(get("amount") or get("turnover"))
            if amount is not None:
                amount = amount * 1000

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
                data_source="tushare",
                trade_date=trade_date,
                period="daily",
                open=_safe_float(get("open")),
                high=_safe_float(get("high")),
                low=_safe_float(get("low")),
                close=close,
                pre_close=pre_close,
                change=change,
                pct_chg=pct_chg,
                volume=volume,
                amount=amount,
                turnover_rate=_safe_float(get("turn") or get("turnover_rate")),
            ))
        return results

    # ── daily_indicators ──

    def adapt_daily_indicators(self, raw: Any) -> List[DailyIndicatorsSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = _parse_symbol_from_ts_code(str(get("ts_code", "")))
            trade_date = _parse_date(get("trade_date"))
            if not trade_date:
                continue

            # 万元 → 元
            total_mv = _safe_float(get("total_mv"))
            if total_mv is not None:
                total_mv = total_mv * 10000
            circ_mv = _safe_float(get("circ_mv"))
            if circ_mv is not None:
                circ_mv = circ_mv * 10000

            results.append(DailyIndicatorsSchema(
                symbol=symbol,
                market="CN",
                data_source="tushare",
                trade_date=trade_date,
                pe_ttm=_safe_float(get("pe")),
                pb=_safe_float(get("pb")),
                ps_ttm=_safe_float(get("ps")),
                turnover_rate=_safe_float(get("turnover_rate")),
                turnover_rate_f=_safe_float(get("turnover_rate_f")),
                total_mv=total_mv,
                circ_mv=circ_mv,
                volume_ratio=_safe_float(get("volume_ratio")),
            ))
        return results

    # ── adj_factors ──

    def adapt_adj_factors(self, raw: Any) -> List[AdjFactorsSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = _parse_symbol_from_ts_code(str(get("ts_code", "")))
            trade_date = _parse_date(get("trade_date"))
            if not trade_date:
                continue
            results.append(AdjFactorsSchema(
                symbol=symbol,
                market="CN",
                data_source="tushare",
                trade_date=trade_date,
                adj_factor=_safe_float(get("adj_factor")),
                fore_adj_factor=_safe_float(get("fore_adj_factor")),
                back_adj_factor=_safe_float(get("back_adj_factor")),
            ))
        return results

    # ── financial_data ──

    def adapt_financial_data(self, raw: Any) -> List[FinancialDataSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = _parse_symbol_from_ts_code(str(get("ts_code", "") or get("symbol", "")))
            report_period = _parse_date(
                get("report_period") or get("end_date") or get("ann_date")
            )

            # 判断报表类型
            stmt_type = get("statement_type") or self._detect_stmt_type(row)

            results.append(FinancialDataSchema(
                symbol=symbol,
                market="CN",
                data_source="tushare",
                report_period=report_period,
                statement_type=stmt_type,
                announce_date=_parse_date(get("ann_date")),
                revenue=_safe_float(get("total_revenue") or get("revenue")),
                net_profit=_safe_float(get("net_profit") or get("n_income")),
                total_assets=_safe_float(get("total_assets")),
                total_equity=_safe_float(
                    get("total_hldr_eqy_exc_min_int") or get("total_equity")
                ),
                roe=_safe_float(get("roe")),
                roa=_safe_float(get("roa")),
                gross_margin=_safe_float(get("grossprofit_margin")),
                net_margin=_safe_float(get("netprofit_margin")),
                debt_ratio=_safe_float(get("debt_to_assets")),
                current_ratio=_safe_float(get("current_ratio")),
                eps=_safe_float(get("eps")),
                bps=_safe_float(get("bps")),
                operating_cashflow=_safe_float(get("n_cashflow_act")),
            ))
        return results

    @staticmethod
    def _detect_stmt_type(row) -> str:
        keys = set(row.index) if isinstance(row, pd.Series) else set(row.keys())
        if keys & {"total_revenue", "oper_cost", "n_income"}:
            return "income"
        if keys & {"total_assets", "total_cur_assets", "total_hldr_eqy_exc_min_int"}:
            return "balance"
        if keys & {"n_cashflow_act", "n_cashflow_inv_act", "n_cashflow_fnc_act"}:
            return "cashflow"
        return "indicator"

    # ── news ──

    def adapt_news(self, raw: Any) -> List[StockNewsSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            title = get("title", "")
            publish_time = get("datetime", "") or get("publish_time", "")
            content_hash = StockNewsSchema.compute_hash(title, str(publish_time)) if title else None
            results.append(StockNewsSchema(
                symbol=str(get("symbol", "")),
                market="CN",
                data_source="tushare",
                title=title,
                content=get("content"),
                content_hash=content_hash,
                source=get("source") or get("channels", ""),
                publish_time=publish_time,
                url=get("url"),
            ))
        return results

    # ── market_quotes ──

    def adapt_market_quotes(self, raw: Any) -> List[MarketQuotesSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = _parse_symbol_from_ts_code(str(get("ts_code", get("symbol", ""))))
            close = _safe_float(get("price") or get("close"))
            pre_close = _safe_float(get("pre_close") or get("close"))
            pct_chg = _safe_float(get("pct_chg") or get("change_percent"))

            # 成交量单位转换: 手 → 股（×100）
            volume = _safe_float(get("volume") or get("vol"))
            if volume is not None:
                volume = volume * 100

            # 成交额单位转换: 千元 → 元（×1000）
            amount = _safe_float(get("amount") or get("turnover"))
            if amount is not None:
                amount = amount * 1000

            results.append(MarketQuotesSchema(
                symbol=symbol,
                market="CN",
                data_source="tushare",
                open=_safe_float(get("open")),
                high=_safe_float(get("high")),
                low=_safe_float(get("low")),
                close=close,
                pre_close=pre_close,
                pct_chg=pct_chg,
                volume=volume,
                amount=amount,
                turnover_rate=_safe_float(get("turn") or get("turnover_rate")),
                last_price=close,
                last_volume=volume,
                last_updated=get("update_time"),
                trade_date=get("trade_date"),
            ))
        return results

    # ── money_flow ──

    def adapt_money_flow(self, raw: Any) -> List[MoneyFlowSchema]:
        """Tushare moneyflow → MoneyFlowSchema

        单位转换: 万元 → 元（×10000）
        """
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = _parse_symbol_from_ts_code(str(get("ts_code", "")))
            td = _parse_date(get("trade_date"))
            if not td:
                continue

            # 万元 → 元
            main_net_inflow = _safe_float(get("net_mf_amount"))
            if main_net_inflow is not None:
                main_net_inflow = main_net_inflow * 10000
            huge_net_inflow = _safe_float(get("buy_elg_amount"))
            if huge_net_inflow is not None:
                huge_net_inflow = huge_net_inflow * 10000
            large_net_inflow = _safe_float(get("buy_lg_amount"))
            if large_net_inflow is not None:
                large_net_inflow = large_net_inflow * 10000
            medium_net_inflow = _safe_float(get("buy_md_amount"))
            if medium_net_inflow is not None:
                medium_net_inflow = medium_net_inflow * 10000
            small_net_inflow = _safe_float(get("buy_sm_amount"))
            if small_net_inflow is not None:
                small_net_inflow = small_net_inflow * 10000

            results.append(MoneyFlowSchema(
                symbol=symbol,
                market="CN",
                data_source="tushare",
                trade_date=td,
                main_net_inflow=main_net_inflow,
                main_net_inflow_pct=_safe_float(get("net_mf_vol")),
                huge_net_inflow=huge_net_inflow,
                large_net_inflow=large_net_inflow,
                medium_net_inflow=medium_net_inflow,
                small_net_inflow=small_net_inflow,
            ))
        return results

    # ── margin_trading ──

    def adapt_margin_trading(self, raw: Any) -> List[MarginTradingSchema]:
        """Tushare margin_detail → MarginTradingSchema"""
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = _parse_symbol_from_ts_code(str(get("ts_code", "")))
            td = _parse_date(get("trade_date"))
            if not td:
                continue
            results.append(MarginTradingSchema(
                symbol=symbol,
                market="CN",
                data_source="tushare",
                trade_date=td,
                rzye=_safe_float(get("rzye")),
                rqye=_safe_float(get("rqye")),
                rz_buy=_safe_float(get("rzmre")),
                rq_sell=_safe_float(get("rqmcl")),
                rzrqye=_safe_float(get("rzrqye")),
                rqyl=_safe_float(get("rqyl")),
            ))
        return results

    # ── dragon_tiger ──

    def adapt_dragon_tiger(self, raw: Any) -> List[DragonTigerSchema]:
        """Tushare top_list → DragonTigerSchema"""
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = _parse_symbol_from_ts_code(str(get("ts_code", "")))
            td = _parse_date(get("trade_date"))
            if not td:
                continue
            results.append(DragonTigerSchema(
                symbol=symbol,
                market="CN",
                data_source="tushare",
                trade_date=td,
                name=str(get("name", "")),
                close=_safe_float(get("close")),
                pct_chg=_safe_float(get("pct_change")),
                direction=str(get("reason", "")),
                buy_amount=_safe_float(get("l_buy")),
                sell_amount=_safe_float(get("l_sell")),
                net_amount=_safe_float(get("net_amount")),
            ))
        return results

    # ── block_trade ──

    def adapt_block_trade(self, raw: Any) -> List[BlockTradeSchema]:
        """Tushare block_trade → BlockTradeSchema"""
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = _parse_symbol_from_ts_code(str(get("ts_code", "")))
            td = _parse_date(get("trade_date"))
            if not td:
                continue
            results.append(BlockTradeSchema(
                symbol=symbol,
                market="CN",
                data_source="tushare",
                trade_date=td,
                name=str(get("name", "")),
                price=_safe_float(get("price")),
                volume=_safe_float(get("vol")),
                amount=_safe_float(get("amount")),
                buyer=str(get("buyer", "")),
                seller=str(get("seller", "")),
            ))
        return results

    # ── intraday_quotes ──

    def adapt_intraday_quotes(self, raw: Any) -> List[IntradayQuotesSchema]:
        """Tushare stk_mins → IntradayQuotesSchema"""
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            ts_code = str(get("ts_code", ""))
            symbol = _parse_symbol_from_ts_code(ts_code)
            dt = str(get("trade_time", ""))
            if not dt:
                continue
            results.append(IntradayQuotesSchema(
                symbol=symbol,
                market="CN",
                data_source="tushare",
                datetime=dt,
                freq="30min",
                open=_safe_float(get("open")),
                close=_safe_float(get("close")),
                high=_safe_float(get("high")),
                low=_safe_float(get("low")),
                volume=_safe_float(get("vol")),
                amount=_safe_float(get("amount")),
            ))
        return results
