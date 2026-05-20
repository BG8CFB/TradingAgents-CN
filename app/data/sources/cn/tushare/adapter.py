"""
Tushare 数据源 Adapter

职责：将 TushareProvider 返回的原始数据转换为 Schema 标准格式。

关键转换规则：
- 股票代码：ts_code "000001.SZ" → symbol "000001"
- 成交量：手 → 股（×100）
- 成交额：千元 → 元（×1000）
- 市值：万元 → 元（×10000）或 亿元 → 元（视 API 而定）
"""

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from app.data.schema.base import get_full_symbol
from app.data.schema.stock_basic_info import StockBasicInfoSchema
from app.data.schema.stock_daily_quotes import StockDailyQuoteSchema
from app.data.schema.stock_daily_indicators import DailyIndicatorsSchema
from app.data.schema.stock_adj_factors import AdjFactorsSchema
from app.data.schema.stock_financial_data import FinancialDataSchema
from app.data.sources.base.adapter import BaseAdapter

logger = logging.getLogger(__name__)


class TushareAdapter(BaseAdapter):
    """Tushare 数据标准化适配器"""

    def __init__(self, provider=None, market: str = "CN", source_name: str = "tushare"):
        super().__init__(
            provider=provider,
            market=market,
            source_name=source_name,
        )

    # ── 工具方法 ──

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

    def _get_row_value(self, row: Any) -> Any:
        """从 DataFrame 行或 dict 获取取值函数"""
        if hasattr(row, "get"):
            return row.get
        return lambda k: getattr(row, k, None)

    # ── 基础信息适配 ──

    def adapt_basic_info(self, row: Any) -> StockBasicInfoSchema:
        """
        将 Tushare 原始行数据转换为 StockBasicInfoSchema

        输入格式（Tushare stock_basic 返回）:
            ts_code, symbol, name, area, industry, market, list_date, ...

        同时接收 daily_basic 的补充字段：total_mv, circ_mv, pe, pb, turnover_rate 等
        """
        get = self._get_row_value(row)

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
        get = self._get_row_value(row)

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

    # ── 每日指标适配 ──

    def adapt_daily_indicators(self, row: Any) -> Optional[DailyIndicatorsSchema]:
        """
        将 Tushare daily_basic 行数据转换为 DailyIndicatorsSchema

        字段映射：
          ts_code → symbol（纯数字）
          trade_date → trade_date（YYYY-MM-DD）
          pe → pe_ttm（Tushare 的 pe 就是 TTM）
          pb → pb
          ps → ps_ttm
          turnover_rate → turnover_rate
          turnover_rate_f → turnover_rate_f
          total_mv → total_mv（万元 → 元 × 10000）
          circ_mv → circ_mv（万元 → 元 × 10000）
          volume_ratio → volume_ratio
        """
        get = self._get_row_value(row)

        ts_code = str(get("ts_code", ""))
        symbol = self._parse_symbol_from_ts_code(ts_code) if "." in ts_code else str(get("symbol", "")).zfill(6)

        trade_date = self._format_date(get("trade_date"))
        if not trade_date:
            return None

        # 市值转换：万元 → 元
        total_mv = self._safe_float(get("total_mv"))
        if total_mv is not None:
            total_mv = total_mv * 10000

        circ_mv = self._safe_float(get("circ_mv"))
        if circ_mv is not None:
            circ_mv = circ_mv * 10000

        return DailyIndicatorsSchema(
            symbol=symbol,
            trade_date=trade_date,
            pe_ttm=self._safe_float(get("pe")),
            pb=self._safe_float(get("pb")),
            ps_ttm=self._safe_float(get("ps")),
            turnover_rate=self._safe_float(get("turnover_rate")),
            turnover_rate_f=self._safe_float(get("turnover_rate_f")),
            total_mv=total_mv,
            circ_mv=circ_mv,
            volume_ratio=self._safe_float(get("volume_ratio")),
            data_source="tushare",
            updated_at="",
        )

    # ── 复权因子适配 ──

    def adapt_adj_factors(self, row: Any) -> Optional[AdjFactorsSchema]:
        """
        将 Tushare adj_factor 行数据转换为 AdjFactorsSchema

        字段映射：
          ts_code → symbol（纯数字）
          trade_date → trade_date（YYYY-MM-DD）
          adj_factor → adj_factor
        """
        get = self._get_row_value(row)

        ts_code = str(get("ts_code", ""))
        symbol = self._parse_symbol_from_ts_code(ts_code) if "." in ts_code else str(get("symbol", "")).zfill(6)

        trade_date = self._format_date(get("trade_date"))
        if not trade_date:
            return None

        return AdjFactorsSchema(
            symbol=symbol,
            trade_date=trade_date,
            adj_factor=self._safe_float(get("adj_factor")),
            fore_adj_factor=self._safe_float(get("fore_adj_factor")),
            back_adj_factor=self._safe_float(get("back_adj_factor")),
            data_source="tushare",
            updated_at="",
        )

    # ── 财务数据适配 ──

    def adapt_financial(self, row: Any) -> Optional[FinancialDataSchema]:
        """
        将 Tushare 财务数据行转换为 FinancialDataSchema

        Tushare 财务 API（income/balancesheet/cashflow/financial_indicator）
        返回字段各不相同，本方法通过字段名自动识别并映射到标准 Schema。
        未知字段存入 extra_data。

        关键单位转换：
        - 金额字段：千元 → 元（× 1000）或 元（保持）
        """
        get = self._get_row_value(row)

        ts_code = str(get("ts_code", ""))
        symbol = self._parse_symbol_from_ts_code(ts_code) if "." in ts_code else str(get("symbol", "")).zfill(6)
        full_symbol = get_full_symbol(symbol, "CN")

        # 报告期
        report_period = self._format_date(get("end_date") or get("ann_date") or get("report_period"))

        # 判断 statement_type
        stmt_type = self._detect_statement_type(row, get)

        # 报告类型
        report_type = str(get("report_type", "")) if get("report_type") else None

        # 公告日期
        announce_date = self._format_date(get("ann_date") or get("announce_date"))

        # 提取公共财务字段（各 API 可能返回部分字段）
        # 金额类字段：Tushare 财务默认单位为元
        revenue = self._safe_float(get("total_revenue") or get("revenue"))
        net_profit = self._safe_float(
            get("net_profit") or get("n_income") or get("n_income_attr_p")
        )
        total_assets = self._safe_float(get("total_assets") or get("total_assets_hldr"))
        total_equity = self._safe_float(
            get("total_hldr_eqy_exc_min_int") or get("total_equity")
            or get("total_hldr_eqy")
        )

        # 比率类字段（直接映射）
        roe = self._safe_float(get("roe") or get("roe_waa"))
        roa = self._safe_float(get("roa") or get("roa_waa"))
        gross_margin = self._safe_float(get("grossprofit_margin") or get("gross_margin"))
        net_margin = self._safe_float(get("netprofit_margin") or get("net_margin"))
        debt_ratio = self._safe_float(get("debt_to_assets") or get("debt_ratio"))
        current_ratio = self._safe_float(get("current_ratio"))
        eps = self._safe_float(get("eps") or get("basic_eps"))
        bps = self._safe_float(get("bps") or get("bps"))

        # 经营活动现金流
        operating_cashflow = self._safe_float(
            get("n_cashflow_act") or get("operating_cashflow")
        )

        # 收集未映射的原始字段到 extra_data
        known_fields = {
            "ts_code", "symbol", "end_date", "ann_date", "report_type",
            "total_revenue", "revenue", "net_profit", "n_income", "n_income_attr_p",
            "total_assets", "total_assets_hldr", "total_hldr_eqy_exc_min_int",
            "total_equity", "total_hldr_eqy", "roe", "roe_waa", "roa", "roa_waa",
            "grossprofit_margin", "gross_margin", "netprofit_margin", "net_margin",
            "debt_to_assets", "debt_ratio", "current_ratio", "eps", "basic_eps",
            "bps", "n_cashflow_act", "operating_cashflow",
            "announce_date", "report_period", "statement_type", "full_symbol",
            "data_source", "updated_at", "created_at",
        }

        extra_data = {}
        if isinstance(row, dict):
            for k, v in row.items():
                if k not in known_fields and v is not None:
                    extra_data[k] = v
        elif isinstance(row, pd.Series):
            for k in row.index:
                if k not in known_fields and row[k] is not None and not (isinstance(row[k], float) and pd.isna(row[k])):
                    extra_data[k] = row[k]

        return FinancialDataSchema(
            symbol=symbol,
            full_symbol=full_symbol,
            report_period=report_period or "",
            statement_type=stmt_type,
            report_type=report_type,
            announce_date=announce_date,
            revenue=revenue,
            net_profit=net_profit,
            total_assets=total_assets,
            total_equity=total_equity,
            roe=roe,
            roa=roa,
            gross_margin=gross_margin,
            net_margin=net_margin,
            debt_ratio=debt_ratio,
            current_ratio=current_ratio,
            eps=eps,
            bps=bps,
            operating_cashflow=operating_cashflow,
            extra_data=extra_data if extra_data else None,
            raw_data=dict(row) if isinstance(row, (dict, pd.Series)) else None,
            data_source="tushare",
            updated_at="",
        )

    @staticmethod
    def _detect_statement_type(row: Any, get_fn) -> str:
        """根据行数据中的字段自动判断报表类型"""
        # 如果数据自带 type 字段
        explicit_type = get_fn("statement_type") or get_fn("type")
        if explicit_type:
            return str(explicit_type)

        # 根据特征字段判断
        row_keys = set()
        if isinstance(row, dict):
            row_keys = set(row.keys())
        elif isinstance(row, pd.Series):
            row_keys = set(row.index)

        # 利润表特征字段
        income_fields = {"total_revenue", "operating_rev", "revenue", "total_cogs",
                         "oper_cost", "sell_exp", "admin_exp", "n_income", "n_income_attr_p"}
        # 资产负债表特征字段
        balance_fields = {"total_assets", "total_cur_assets", "total_nca",
                          "total_liab", "total_cur_liab", "total_hldr_eqy_exc_min_int",
                          "money_cap", "accounts_rece", "inventory"}
        # 现金流量表特征字段
        cashflow_fields = {"n_cashflow_act", "n_cashflow_inv_act", "n_cashflow_fnc_act",
                           "c_fr_sale_sg", "c_paid_goods", "c_paid_employee"}
        # 财务指标特征字段
        indicator_fields = {"roe", "roe_waa", "roa", "roa_waa", "eps", "bps",
                            "grossprofit_margin", "netprofit_margin", "debt_to_assets"}

        income_overlap = len(row_keys & income_fields)
        balance_overlap = len(row_keys & balance_fields)
        cashflow_overlap = len(row_keys & cashflow_fields)
        indicator_overlap = len(row_keys & indicator_fields)

        max_overlap = max(income_overlap, balance_overlap, cashflow_overlap, indicator_overlap)
        if max_overlap == 0:
            return "indicator"  # 默认

        if max_overlap == income_overlap:
            return "income"
        if max_overlap == balance_overlap:
            return "balance"
        if max_overlap == cashflow_overlap:
            return "cashflow"
        return "indicator"
