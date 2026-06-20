"""AKShare CN Adapter — 原始数据 → 标准 Schema。

AKShare 返回的数据单位已是标准单位（股/元），主要做字段名映射。
"""

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from app.data.sources.base.adapter import BaseAdapter
from app.data.schema.base.types import _safe_float, _parse_date
from app.data.schema.domains.basic_info import StockBasicInfoSchema
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


from app.data.sources.cn.stock_name_utils import infer_exchange as _infer_exchange  # noqa: E402 (intentional late import)


# AKShare 市值字段单位映射表（按接口名声明，是 AKShare 接口的稳定契约）。
# schema 统一以"元"为单位存储市值，adapter 出口按映射表归一化。
#   - stock_zh_valuation_baidu（百度股市通）→ 亿元（数值 × 1e8 转元）
#   - stock_zh_a_spot_em（东方财富实时）→ 元（数值本身已是元）
#   - stock_zh_a_st_em / 其它 spot 类 → 元
# 未声明接口默认按"元"处理（不换算）；调用方若发现新接口单位异常，应在此显式登记。
_AKSHARE_MV_UNIT_BY_INTERFACE: Dict[str, str] = {
    "stock_zh_valuation_baidu": "亿元",
    "stock_zh_a_spot_em": "元",
    "stock_zh_a_st_em": "元",
}


def _convert_mv(value: Optional[float], unit: str) -> Optional[float]:
    """按声明单位把市值归一化为元。"""
    if value is None:
        return None
    if unit == "亿元":
        return value * 1e8
    if unit == "万元":
        return value * 1e4
    return value  # "元" 或未知单位 → 原值


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

    def adapt_daily_indicators(self, raw: Any) -> List[DailyIndicatorsSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        # AKShare daily_indicators 的数据来自百度股市通（stock_zh_valuation_baidu），
        # 该接口返回的市值数值单位为"亿元"；按接口契约显式声明，不再用数值阈值猜测。
        # 详见 _AKSHARE_MV_UNIT_BY_INTERFACE。
        mv_unit = _AKSHARE_MV_UNIT_BY_INTERFACE.get(
            "stock_zh_valuation_baidu", "元"
        )
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = str(get("symbol", "") or get("code", "") or get("代码", "")).zfill(6)
            trade_date = _parse_date(
                get("trade_date") or get("日期") or get("date")
            )
            if not trade_date:
                continue

            total_mv = _convert_mv(
                _safe_float(get("total_mv") or get("总市值")),
                mv_unit,
            )
            circ_mv = _convert_mv(
                _safe_float(get("circ_mv") or get("流通市值")),
                mv_unit,
            )

            results.append(DailyIndicatorsSchema(
                symbol=symbol,
                market="CN",
                data_source="akshare",
                trade_date=trade_date,
                pe_ttm=_safe_float(
                    get("pe_ttm") or get("市盈率-动态") or get("pe")
                ),
                pb=_safe_float(get("pb") or get("市净率")),
                ps_ttm=_safe_float(get("ps_ttm")),
                turnover_rate=_safe_float(get("turnover_rate") or get("换手率")),
                total_mv=total_mv,
                circ_mv=circ_mv,
                volume_ratio=_safe_float(get("volume_ratio") or get("量比")),
            ))
        return results

    def adapt_adj_factors(self, raw: Any) -> List[AdjFactorsSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            trade_date = _parse_date(
                get("trade_date") or get("date") or get("日期")
            )
            if not trade_date:
                continue

            qfq_factor = _safe_float(get("qfq_factor") or get("fore_adj_factor"))
            hfq_factor = _safe_float(get("hfq_factor") or get("back_adj_factor"))
            adj_factor = _safe_float(get("adj_factor"))
            if adj_factor is None and qfq_factor is not None:
                adj_factor = qfq_factor

            results.append(AdjFactorsSchema(
                symbol=str(get("symbol", "") or get("code", "")).zfill(6),
                market="CN",
                data_source="akshare",
                trade_date=trade_date,
                adj_factor=adj_factor,
                fore_adj_factor=qfq_factor,
                back_adj_factor=hfq_factor,
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
            report_period = _parse_date(
                get("report_period") or get("report_date") or get("end_date")
            )
            results.append(FinancialDataSchema(
                symbol=symbol,
                market="CN",
                data_source="akshare",
                report_period=report_period,
                revenue=_safe_float(get("revenue") or get("营业收入")),
                net_profit=_safe_float(get("net_profit") or get("净利润")),
                total_assets=_safe_float(get("total_assets")),
                total_equity=_safe_float(get("total_equity") or get("所有者权益合计")),
                roe=_safe_float(get("roe")),
                gross_margin=_safe_float(get("gross_margin") or get("grossprofit_margin")),
                net_margin=_safe_float(get("net_margin") or get("netprofit_margin")),
                eps=_safe_float(get("eps") or get("basic_eps")),
                bps=_safe_float(get("bps")),
                operating_cashflow=_safe_float(get("operating_cashflow")),
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
            symbol = str(get("symbol", "") or get("code", "") or get("股票代码", "")).zfill(6)
            close = _safe_float(get("price") or get("最新价") or get("close"))
            pre_close = _safe_float(get("昨收") or get("pre_close"))
            pct_chg = _safe_float(get("涨跌幅") or get("pct_chg") or get("change_percent"))
            volume = _safe_float(get("volume") or get("成交量"))
            amount = _safe_float(get("amount") or get("成交额") or get("turnover"))
            results.append(MarketQuotesSchema(
                symbol=symbol,
                market="CN",
                data_source="akshare",
                open=_safe_float(get("开盘") or get("open")),
                high=_safe_float(get("最高") or get("high")),
                low=_safe_float(get("最低") or get("low")),
                close=close,
                pre_close=pre_close,
                pct_chg=pct_chg,
                volume=volume,
                amount=amount,
                turnover_rate=_safe_float(get("换手率") or get("turnover_rate")),
                last_price=close,
                last_volume=volume,
            ))
        return results

    def adapt_intraday_quotes(self, raw: Any) -> List[IntradayQuotesSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = str(get("股票代码", "") or get("code", "")).zfill(6)
            dt = str(get("时间", "") or get("datetime", "") or get("day", ""))
            results.append(IntradayQuotesSchema(
                symbol=symbol,
                market="CN",
                data_source="akshare",
                datetime=dt,
                freq=str(get("freq", "30min")),
                open=_safe_float(get("开盘", "") or get("open")),
                close=_safe_float(get("收盘", "") or get("close")),
                high=_safe_float(get("最高", "") or get("high")),
                low=_safe_float(get("最低", "") or get("low")),
                volume=_safe_float(get("成交量", "") or get("volume")),
                amount=_safe_float(get("成交额", "") or get("amount")),
                pct_chg=_safe_float(get("涨跌幅", "") or get("change")),
            ))
        return results

    def adapt_money_flow(self, raw: Any) -> List[MoneyFlowSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = str(get("股票代码", "") or get("代码", "") or get("symbol", "")).zfill(6)
            td = _parse_date(get("日期", "") or get("trade_date", ""))
            results.append(MoneyFlowSchema(
                symbol=symbol,
                market="CN",
                data_source="akshare",
                trade_date=td,
                main_net_inflow=_safe_float(get("主力净流入-净额", "") or get("main_net_inflow")),
                main_net_inflow_pct=_safe_float(get("主力净流入-净占比", "") or get("main_net_pct")),
                huge_net_inflow=_safe_float(get("超大单净流入-净额", "") or get("huge_net_inflow")),
                large_net_inflow=_safe_float(get("大单净流入-净额", "") or get("large_net_inflow")),
                medium_net_inflow=_safe_float(get("中单净流入-净额", "") or get("medium_net_inflow")),
                small_net_inflow=_safe_float(get("小单净流入-净额", "") or get("small_net_inflow")),
            ))
        return results

    def adapt_margin_trading(self, raw: Any) -> List[MarginTradingSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = str(get("证券代码", "") or get("股票代码", "") or get("symbol", "")).zfill(6)
            td = _parse_date(get("日期", "") or get("trade_date", ""))
            results.append(MarginTradingSchema(
                symbol=symbol,
                market="CN",
                data_source="akshare",
                trade_date=td,
                rzye=_safe_float(get("融资余额", "") or get("rzye")),
                rqye=_safe_float(get("融券余额", "") or get("rqye")),
                rz_buy=_safe_float(get("融资买入额", "") or get("rz_buy")),
                rq_sell=_safe_float(get("融券卖出量", "") or get("rq_sell")),
                rzrqye=_safe_float(get("融资融券余额", "") or get("rzrqye")),
            ))
        return results

    def adapt_dragon_tiger(self, raw: Any) -> List[DragonTigerSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = str(get("代码", "") or get("股票代码", "") or get("symbol", "")).zfill(6)
            td = _parse_date(get("日期", "") or get("trade_date", ""))
            results.append(DragonTigerSchema(
                symbol=symbol,
                market="CN",
                data_source="akshare",
                trade_date=td,
                name=str(get("名称", "") or get("name", "")),
                close=_safe_float(get("收盘价", "") or get("close")),
                pct_chg=_safe_float(get("涨跌幅", "") or get("change_pct")),
                direction=str(get("解读", "") or get("direction", "")),
                buy_amount=_safe_float(get("买入额", "") or get("buy")),
                sell_amount=_safe_float(get("卖出额", "") or get("sell")),
                net_amount=_safe_float(get("净额", "") or get("net")),
            ))
        return results

    def adapt_block_trade(self, raw: Any) -> List[BlockTradeSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = str(get("证券代码", "") or get("代码", "") or get("symbol", "")).zfill(6)
            td = _parse_date(get("成交日期", "") or get("trade_date", ""))
            results.append(BlockTradeSchema(
                symbol=symbol,
                market="CN",
                data_source="akshare",
                trade_date=td,
                name=str(get("证券名称", "") or get("名称", "") or get("name", "")),
                price=_safe_float(get("成交价", "") or get("price")),
                volume=_safe_float(get("成交量", "") or get("volume")),
                amount=_safe_float(get("成交额", "") or get("amount")),
                buyer=str(get("买方营业部", "") or get("buyer", "")),
                seller=str(get("卖方营业部", "") or get("seller", "")),
            ))
        return results
