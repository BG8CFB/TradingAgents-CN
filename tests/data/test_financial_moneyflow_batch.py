"""财务/资金流批量接入测试 — 报告期滚动、归一化、批量分支与豁免逻辑。

覆盖 2026-09 财务按报告期批量 + 资金流按日批量改造：
- recent_report_periods 季度边界
- AKShare 财务兜底修复（report_period 归一 / statement_type / debt_ratio）
- Tushare 批量合并记录的 adapter 兼容（显式 statement_type 优先于列名探测）
- FallbackRouter 批量分支哨兵与 6 日窗口
- sync_job 批量豁免
"""

import pandas as pd
import pytest

from app.data.factors.engine import FactorScoreEngine
from app.data.processor.fallback_router import FallbackRouter
from app.data.sources.base.provider import BaseProvider
from app.data.sources.cn.akshare.adapter import AKShareCNAdapter
from app.data.sources.cn.akshare.api.financial import (
    _build_financial_row,
    _normalize_report_period,
    _rename_key_cols,
    _YJBB_KEY_COLS,
    _ZCFZ_KEY_COLS,
)
from app.data.sources.cn.reporting import recent_report_periods
from app.data.sources.cn.tushare.adapter import TushareCNAdapter


# ============================================================
# recent_report_periods — 滚动报告期边界
# ============================================================

class TestRecentReportPeriods:
    def test_mid_quarter_rolls_back_five_quarters(self):
        # 2026-09-14：最新已过报告期 20260630，往回推 5 期
        assert recent_report_periods(5, "2026-09-14") == [
            "20260630", "20260331", "20251231", "20250930", "20250630",
        ]

    def test_year_start_crosses_two_years(self):
        # 1 月 1 日：当年无已过季末，全部来自上一年及更早
        assert recent_report_periods(5, "2026-01-01") == [
            "20251231", "20250930", "20250630", "20250331", "20241231",
        ]

    def test_after_q4_end_includes_it(self):
        # 12 月 31 日当天：1231 未过（不含等于），从 0930 起推
        assert recent_report_periods(2, "2026-12-31") == ["20260930", "20260630"]

    def test_next_year_first_day_includes_q4(self):
        assert recent_report_periods(1, "2027-01-01") == ["20261231"]


# ============================================================
# AKShare 财务兜底修复
# ============================================================

class TestAkshareFinancialFix:
    def test_normalize_report_period_variants(self):
        assert _normalize_report_period(2025) == "2025-12-31"       # THS 年份 int
        assert _normalize_report_period("2025") == "2025-12-31"
        assert _normalize_report_period("2025-06-30 00:00:00") == "2025-06-30"
        assert _normalize_report_period("20250630") == "2025-06-30"
        assert _normalize_report_period(None) is None

    def test_build_financial_row_ths_year_form(self):
        """THS 按年度摘要（年份报告期）合并出的记录三修复点齐备。"""
        tables = {
            "abstract": pd.DataFrame([{
                "报告期": 2025, "营业收入": "100亿", "净利润": "10亿",
                "净资产收益率": 18.0, "毛利率": 35.0,
            }]),
            "balance": pd.DataFrame([{
                "REPORT_DATE": "2025-12-31 00:00:00",
                "总资产": 200.0, "总负债": 120.0, "所有者权益合计": 80.0,
            }]),
        }
        row = _build_financial_row("000001", tables)
        assert row["report_period"] == "2025-12-31"
        assert row["statement_type"] == "indicator"
        assert row["debt_ratio"] == 60.0  # 120/200×100
        assert row["total_liab"] == 120.0

    def test_build_financial_row_no_balance_no_crash(self):
        """资产负债表缺失时 debt_ratio 为 None，不崩。"""
        tables = {
            "abstract": pd.DataFrame([{"报告期": 2025, "净利润": "5亿"}]),
        }
        row = _build_financial_row("000001", tables)
        assert row["debt_ratio"] is None
        assert row["statement_type"] == "indicator"

    def test_adapter_maps_statement_type_and_debt_ratio(self):
        df = pd.DataFrame([{
            "symbol": "000001", "report_period": "2025-12-31",
            "statement_type": "indicator",
            "revenue": 100.0, "net_profit": 10.0, "roe": 18.0,
            "debt_ratio": 60.0,
        }])
        results = AKShareCNAdapter().adapt_financial_data(df)
        assert len(results) == 1
        r = results[0]
        assert r.statement_type == "indicator"
        assert r.debt_ratio == 60.0
        assert r.report_period == "2025-12-31"


# ============================================================
# Tushare 批量合并记录 — adapter 契约
# ============================================================

class TestTushareBatchContract:
    def test_adapt_financial_batch_merged_row(self):
        """批量合并记录同时含 income 列与 indicator 列，显式
        statement_type 必须优先于 _detect_stmt_type 的列名探测。"""
        df = pd.DataFrame([{
            "ts_code": "000001.SZ", "ann_date": 20260830, "end_date": 20260630,
            "statement_type": "indicator",
            "roe": 18.0, "roa": 1.5, "grossprofit_margin": 35.0,
            "netprofit_margin": 20.0, "debt_to_assets": 60.0,
            "current_ratio": 1.8, "eps": 1.2, "bps": 10.0,
            "total_revenue": 100.0, "n_income": 20.0,
        }])
        results = TushareCNAdapter().adapt_financial_data(df)
        assert len(results) == 1
        r = results[0]
        assert r.statement_type == "indicator"
        assert r.report_period == "2026-06-30"
        assert r.revenue == 100.0
        assert r.net_profit == 20.0
        assert r.roe == 18.0
        assert r.debt_ratio == 60.0

    def test_adapt_daily_indicators_dividend_yield(self):
        """dv_ttm → dividend_yield 股息率映射（高ROE低估值策略依赖）。"""
        df = pd.DataFrame([{
            "ts_code": "000001.SZ", "trade_date": 20260911,
            "pe_ttm": 5.5, "pb": 0.8, "dv_ttm": 3.2,
        }])
        results = TushareCNAdapter().adapt_daily_indicators(df)
        assert results[0].dividend_yield == 3.2


class TestAkshareEmBatchContract:
    def test_rename_key_cols_missing_source_col(self):
        """接口改版缺列时置 None 而非 KeyError（早暴露但不崩同步）。"""
        df = pd.DataFrame([{"股票代码": "000001", "净资产收益率": 18.0}])
        renamed = _rename_key_cols(df, _YJBB_KEY_COLS)
        assert renamed.loc[0, "symbol"] == "000001"
        assert renamed.loc[0, "roe"] == 18.0
        assert pd.isna(renamed.loc[0, "gross_margin"])

    def test_em_merged_row_adapts_to_schema(self):
        """东财 yjbb+zcfz 合并行（批量路径产物）经 adapter 落全财务字段。"""
        yjbb = _rename_key_cols(pd.DataFrame([{
            "股票代码": "000001", "每股收益": 1.2,
            "营业总收入-营业总收入": 1e9, "净利润-净利润": 2e8,
            "每股净资产": 10.0, "净资产收益率": 18.0,
            "销售毛利率": 35.0, "最新公告日期": "2026-09-12",
        }]), _YJBB_KEY_COLS)
        zcfz = _rename_key_cols(pd.DataFrame([{
            "股票代码": "000001", "资产-总资产": 2e10, "负债-总负债": 1.2e10,
            "资产负债率": 60.0, "股东权益合计": 8e9,
        }]), _ZCFZ_KEY_COLS)
        merged = yjbb.merge(zcfz, on="symbol", how="left")
        merged["report_period"] = "2026-06-30"
        merged["statement_type"] = "indicator"

        results = AKShareCNAdapter().adapt_financial_data(merged)
        r = results[0]
        assert r.symbol == "000001"
        assert r.statement_type == "indicator"
        assert r.report_period == "2026-06-30"
        assert r.revenue == 1e9
        assert r.net_profit == 2e8
        assert r.roe == 18.0
        assert r.gross_margin == 35.0
        assert r.debt_ratio == 60.0
        assert r.eps == 1.2
        assert r.bps == 10.0


# ============================================================
# FallbackRouter 批量分支
# ============================================================

class _PlainProvider(BaseProvider):
    """只实现连接桩的最小真实 Provider — 未覆写任何批量方法。"""

    async def connect(self) -> bool:
        return False

    def is_available(self) -> bool:
        return False


class _BatchMoneyFlowProvider(_PlainProvider):
    """覆写资金流批量的真实 Provider（返回固定真实 DataFrame）。"""

    async def get_money_flow_batch(self, trade_date: str, **kwargs) -> pd.DataFrame:
        if trade_date < "2026-09-10":
            from app.data.sources.base.exceptions import DataNotFoundError
            raise DataNotFoundError("test", "money_flow", trade_date)
        return pd.DataFrame([{
            "ts_code": "000001.SZ", "trade_date": trade_date,
            "net_mf_amount": 1000.0,
        }])


class TestFallbackRouterBatch:
    def setup_method(self):
        from app.data.core.registry.capability import CapabilityRegistry
        from app.data.core.registry.priority import PriorityConfig
        self.router = FallbackRouter(CapabilityRegistry(), PriorityConfig())

    async def test_financial_batch_not_supported_sentinel(self):
        """未覆写 get_financial_data_batch 的源 → 哨兵 skip 语义。"""
        result = await self.router._fetch_financial_batch(
            _PlainProvider("plain", "CN"), "__all__", "2020-01-01", "2099-12-31")
        assert result is FallbackRouter._BATCH_NOT_SUPPORTED

    async def test_money_flow_batch_not_supported_sentinel(self):
        result = await self.router._fetch_money_flow_batch(
            _PlainProvider("plain", "CN"), "__all__", "2020-01-01", "2099-12-31")
        assert result is FallbackRouter._BATCH_NOT_SUPPORTED

    async def test_money_flow_batch_six_day_window_selfheal(self, inject_sim_db):
        """6 日窗口：历史日无数据跳过、可用日照常返回、合并去重。"""
        from app.data.storage.mongo.collections import get_collection_name

        dates = ["2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10",
                 "2026-09-11", "2026-09-14"]
        coll = inject_sim_db[get_collection_name("daily_quotes", "CN")]
        for d in dates:
            await coll.insert_one({"symbol": "000001", "trade_date": d})

        provider = _BatchMoneyFlowProvider("batch", "CN")
        df = await self.router._fetch_money_flow_batch(
            provider, "__all__", "2020-01-01", "2099-12-31")
        # 09-10 起有数据（3 日），09-07/08/09 抛 DataNotFoundError 跳过；
        # 窗口按最新在前遍历，行序不影响入库（唯一键 upsert）
        assert set(df["trade_date"]) == {"2026-09-10", "2026-09-11", "2026-09-14"}
        assert len(df) == 3

    async def test_recent_quote_trade_dates_desc(self, inject_sim_db):
        from app.data.storage.mongo.collections import get_collection_name

        coll = inject_sim_db[get_collection_name("daily_quotes", "CN")]
        for d in ["2026-09-08", "2026-09-11", "2026-09-09"]:
            await coll.insert_one({"symbol": "000001", "trade_date": d})
        assert await self.router._recent_quote_trade_dates("CN", 2) == \
            ["2026-09-11", "2026-09-09"]


# ============================================================
# sync_job 批量豁免
# ============================================================

class TestSyncJobBatchExemption:
    def test_financial_and_money_flow_exempt_from_symbol_list(self):
        from app.data.scheduler.jobs.cn import CNFinancialDataJob, CNMoneyFlowJob

        assert CNFinancialDataJob()._needs_symbol_list() is False
        assert CNMoneyFlowJob()._needs_symbol_list() is False


# ============================================================
# Provider 批量覆写方法的 lazy import 可达性
# ============================================================

class TestProviderBatchImportReachability:
    async def test_tushare_financial_batch_import_reachable(self):
        """覆写方法函数体内的 lazy import 必须可达。

        真实回归：recent_report_periods 从 tushare/api/financial.py 移到
        cn/reporting.py 后 tushare provider 的 import 悬空，运行时
        ImportError → 整源不可用被迫回退 AKShare。直调覆写方法验证
        import 链；token/网络异常非本测试目标，放行。
        """
        from app.data.sources.cn.tushare.provider import TushareCNProvider

        try:
            await TushareCNProvider().get_financial_data_batch()
        except ImportError as exc:
            pytest.fail(f"tushare get_financial_data_batch 函数内 import 损坏: {exc}")
        except Exception:
            pass


# ============================================================
# 因子引擎 quality 加固
# ============================================================

class TestQualityStatementTypeHardening:
    async def test_indicator_row_preferred_on_same_period(self, real_mongo_db):
        """同报告期双行（income + indicator）时取 indicator 合并行。"""
        from app.data.storage.mongo.collections import get_collection_name

        coll = real_mongo_db[get_collection_name("financial_data", "CN")]
        await coll.delete_many({"symbol": "TESTQ001"})
        for stmt, np_ in [("income", 5.0), ("indicator", 30.0)]:
            await coll.update_one(
                {"symbol": "TESTQ001", "report_period": "2026-06-30",
                 "statement_type": stmt},
                {"$set": {
                    "symbol": "TESTQ001", "report_period": "2026-06-30",
                    "statement_type": stmt, "net_profit": np_,
                    "roe": 18.0, "gross_margin": 35.0, "debt_ratio": 45.0,
                    "data_source": "test",
                }}, upsert=True)
        await coll.update_one(
            {"symbol": "TESTQ001", "report_period": "2025-06-30"},
            {"$set": {
                "symbol": "TESTQ001", "report_period": "2025-06-30",
                "statement_type": "indicator", "net_profit": 20.0,
                "roe": 16.0, "gross_margin": 33.0, "debt_ratio": 50.0,
                "data_source": "test",
            }}, upsert=True)
        try:
            out = await FactorScoreEngine()._compute_quality("CN")
            # indicator 行 net_profit=30 → yoy = 30/20-1 = 50%
            assert out.loc["TESTQ001", "net_profit_yoy"] == pytest.approx(50.0)
            assert out.loc["TESTQ001", "roe"] == 18.0
        finally:
            await coll.delete_many({"symbol": "TESTQ001"})
