"""Tushare 通用 Adapter 函数 — HK/US 逐字相同/可参数化的标准化逻辑上移。

保留市场差异，仅消除结构性重复：
- ``adapt_trade_calendar`` / ``adapt_adj_factors``：HK/US 逐字相同，
  仅 market / source_name / 默认交易所 / symbol 解析不同 → 直接参数化。
- ``adapt_daily_quotes`` / ``adapt_daily_indicators`` / ``adapt_financial_data``：
  结构相同但字段映射与单位换算不同 → 通过 ``field_map``（字段候选链）
  与 ``unit_scales``（单位倍率）由子类注入。
- CN Adapter 独有方法（vol 手→股、多域映射等）不在此收敛。
"""

import logging
from typing import Any, Callable, Dict, List, Optional, Sequence

import pandas as pd

from app.data.schema.base.types import _parse_date, _safe_float
from app.data.schema.domains.adj_factors import AdjFactorsSchema
from app.data.schema.domains.daily_quotes import DailyQuotesSchema
from app.data.schema.domains.financial_data import FinancialDataSchema
from app.data.schema.domains.trade_calendar import TradeCalendarSchema

logger = logging.getLogger(__name__)


def _to_df(raw: Any) -> pd.DataFrame:
    return raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)


def adapt_trade_calendar(
    raw: Any,
    *,
    market: str,
    source_name: str,
    default_exchange: str,
) -> List[TradeCalendarSchema]:
    df = _to_df(raw)
    if df.empty:
        return []
    results = []
    for _, row in df.iterrows():
        get = row.get
        cal_date = _parse_date(get("cal_date"))
        if not cal_date:
            continue
        results.append(
            TradeCalendarSchema(
                symbol="__calendar__",
                market=market,
                data_source=source_name,
                exchange=get("exchange", default_exchange),
                cal_date=cal_date,
                is_open=bool(get("is_open", 1)),
                pretrade_date=_parse_date(get("pretrade_date")),
            )
        )
    return results


def adapt_adj_factors(
    raw: Any,
    *,
    market: str,
    source_name: str,
    parse_symbol: Callable[[str], str],
) -> List[AdjFactorsSchema]:
    df = _to_df(raw)
    if df.empty:
        return []
    results = []
    for _, row in df.iterrows():
        get = row.get
        symbol = parse_symbol(str(get("ts_code", "")))
        trade_date = _parse_date(get("trade_date"))
        if not trade_date:
            continue
        results.append(
            AdjFactorsSchema(
                symbol=symbol,
                market=market,
                data_source=source_name,
                trade_date=trade_date,
                adj_factor=_safe_float(get("adj_factor")),
            )
        )
    return results


def adapt_daily_quotes(
    raw: Any,
    *,
    market: str,
    source_name: str,
    parse_symbol: Callable[[str], str],
    amount_scale: float = 1.0,
    compute_change: bool = False,
    with_turnover: bool = False,
) -> List[DailyQuotesSchema]:
    """日线行情标准化。

    Args:
        amount_scale: amount 字段单位倍率（HK 千港元→元 = 1000；US 无换算 = 1）。
        compute_change: 缺失时是否由 close/pre_close 推算 change/pct_chg（HK 行为）。
        with_turnover: 是否携带 turnover_rate 字段（HK 行为；US 原始数据无此列）。
    """
    df = _to_df(raw)
    if df.empty:
        return []
    results = []
    for _, row in df.iterrows():
        get = row.get
        symbol = parse_symbol(str(get("ts_code", "")))
        trade_date = _parse_date(get("trade_date"))
        if not trade_date:
            continue

        close = _safe_float(get("close"))
        pre_close = _safe_float(get("pre_close"))
        change = _safe_float(get("change"))
        pct_chg = _safe_float(get("pct_chg"))
        if compute_change:
            if change is None and close is not None and pre_close is not None:
                change = round(close - pre_close, 4)
            if pct_chg is None and close is not None and pre_close is not None and pre_close != 0:
                pct_chg = round((close - pre_close) / pre_close * 100, 4)

        amount = _safe_float(get("amount"))
        if amount is not None and amount_scale != 1.0:
            amount = amount * amount_scale

        kwargs: Dict[str, Any] = {}
        if with_turnover:
            kwargs["turnover_rate"] = _safe_float(get("turnover_rate"))

        results.append(
            DailyQuotesSchema(
                symbol=symbol,
                market=market,
                data_source=source_name,
                trade_date=trade_date,
                period="daily",
                open=_safe_float(get("open")),
                high=_safe_float(get("high")),
                low=_safe_float(get("low")),
                close=close,
                pre_close=pre_close,
                change=change,
                pct_chg=pct_chg,
                volume=_safe_float(get("vol")),
                amount=amount,
                **kwargs,
            )
        )
    return results


def adapt_daily_indicators(
    raw: Any,
    *,
    market: str,
    source_name: str,
    parse_symbol: Callable[[str], str],
    field_map: Dict[str, Sequence[str]],
    unit_scales: Dict[str, float],
) -> List:
    """每日指标标准化（当前仅 HK 使用；字段映射由子类注入）。"""
    from app.data.schema.domains.daily_indicators import DailyIndicatorsSchema

    df = _to_df(raw)
    if df.empty:
        return []
    results = []
    for _, row in df.iterrows():
        get = row.get
        symbol = parse_symbol(str(get("ts_code", "")))
        trade_date = _parse_date(get("trade_date"))
        if not trade_date:
            continue

        def _pick(attr: str) -> Optional[float]:
            for cand in field_map.get(attr, (attr,)):
                val = _safe_float(get(cand))
                if val is not None:
                    scale = unit_scales.get(attr, 1.0)
                    return val * scale if scale != 1.0 else val
            return None

        results.append(
            DailyIndicatorsSchema(
                symbol=symbol,
                market=market,
                data_source=source_name,
                trade_date=trade_date,
                pe_ttm=_pick("pe_ttm"),
                pb=_pick("pb"),
                turnover_rate=_pick("turnover_rate"),
                total_mv=_pick("total_mv"),
                circ_mv=_pick("circ_mv"),
            )
        )
    return results


def adapt_financial_data(
    raw: Any,
    *,
    market: str,
    source_name: str,
    parse_symbol: Callable[[str], str],
    field_map: Dict[str, Sequence[str]],
    unit_scales: Dict[str, float],
) -> List[FinancialDataSchema]:
    """财务数据标准化。

    field_map: schema 字段 → 原始字段候选链（按 ``or`` 语义取第一个真值）。
    unit_scales: schema 字段 → 单位倍率（HK 千元→元 = 1000；US 无换算）。
    """
    df = _to_df(raw)
    if df.empty:
        return []
    results = []
    for _, row in df.iterrows():
        get = row.get
        symbol = parse_symbol(str(get("ts_code", "")))

        def _pick(attr: str) -> Optional[float]:
            for cand in field_map.get(attr, (attr,)):
                val = _safe_float(get(cand))
                if val is not None:
                    scale = unit_scales.get(attr, 1.0)
                    return val * scale if scale != 1.0 else val
            return None

        results.append(
            FinancialDataSchema(
                symbol=symbol,
                market=market,
                data_source=source_name,
                report_period=_parse_date(get("end_date") or get("ann_date")),
                announce_date=_parse_date(get("ann_date")),
                revenue=_pick("revenue"),
                net_profit=_pick("net_profit"),
                total_assets=_pick("total_assets"),
                total_equity=_pick("total_equity"),
                roe=_pick("roe"),
                eps=_pick("eps"),
                bps=_pick("bps"),
                operating_cashflow=_pick("operating_cashflow"),
            )
        )
    return results
