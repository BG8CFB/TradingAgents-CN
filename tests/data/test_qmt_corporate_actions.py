"""分红送配 + 复权因子双源保护（M2 / PRD FR-07）测试。

覆盖：
- `adapt_corporate_actions`：一行事件拆分为 cash_dividend / bonus_issue /
  rights_issue（唯一键 `(symbol, ex_date, action_type)` 决定必须拆行）、
  单位口径（`interest`/送转/配股数**已是每股**，2026-10-20 真实 datadir 定版）、
  `date_src=ts_key` 的可疑除权日**拒写**；
- `provider._filter_dividends`：ts_code 注入 + 除权日窗口过滤 + 无窗口=全量；
- `guarded_write.write_preserving_primary`（FR-07 规则 3）：只补缺口与自我更新，
  **不覆盖其他源**；不一致率超阈值写告警事件；
- `QmtAdjFactorsSync` 走保主源写入路径。

已知未覆盖项（记录在验收文档）：DividData LevelDB 二进制解析没有 fixture，
`reader.dividends()` 的真实文件读取路径无自动化测试。
"""

import pandas as pd
import pytest

from app.data.sources.cn.qmt.adapter import QmtAdapter
from app.data.sources.cn.qmt.field_maps import (
    CORPORATE_ACTIONS_TRUST_TS_KEY,
    DIVIDEND_PER_UNIT,
)
from app.data.sources.cn.qmt.provider import QmtProvider


def _dividend_frame() -> pd.DataFrame:
    """合成分红帧（provider 注入 ts_code 后的形状）。

    数值口径与真实 datadir 一致：``interest`` / ``stock_bonus`` / ``stock_gift`` /
    ``allot_num`` 均为**每股**（实证见 field_maps.DIVIDEND_PER_UNIT 注释）。
    """
    return pd.DataFrame([
        {   # 纯现金派息，含登记日：每股派 0.35 元（= 每 10 股派 3.5 元）
            "ts_code": "600000.SH", "trade_date": "20260612",
            "record_date": "20260611", "date_src": "ex_u32",
            "interest": 0.35, "stock_bonus": 0.0, "stock_gift": 0.0,
            "allot_num": 0.0, "allot_price": 0.0, "dr": 0.99,
        },
        {   # 派息 + 送转（每股送 0.3 转 0.2）→ 必须拆成两行
            "ts_code": "000001.SZ", "trade_date": "20260612",
            "record_date": "", "date_src": "ex_u32",
            "interest": 0.2, "stock_bonus": 0.3, "stock_gift": 0.2,
            "allot_num": 0.0, "allot_price": 0.0, "dr": 0.95,
        },
        {   # 纯配股（每股配 0.2 股，配股价 7.5）
            "ts_code": "000002.SZ", "trade_date": "20260612",
            "record_date": "", "date_src": "ex_u32",
            "interest": 0.0, "stock_bonus": 0.0, "stock_gift": 0.0,
            "allot_num": 0.2, "allot_price": 7.5, "dr": 0.98,
        },
        {   # 除权日由 key 回退派生 → 不可信，拒写
            "ts_code": "000003.SZ", "trade_date": "20150601",
            "record_date": "", "date_src": "ts_key",
            "interest": 0.1, "stock_bonus": 0.0, "stock_gift": 0.0,
            "allot_num": 0.0, "allot_price": 0.0, "dr": 1.0,
        },
    ])


class TestCorporateActionsAdapter:
    def test_splits_one_event_into_action_rows(self):
        rows = QmtAdapter().adapt_corporate_actions(_dividend_frame())
        # 600000 派息1 + 000001 派息+送转2 + 000002 配股1 = 4（ts_key 行被拒）
        assert len(rows) == 4
        assert {r.action_type for r in rows} == {
            "cash_dividend", "bonus_issue", "rights_issue"
        }

    def test_cash_dividend_is_per_share(self):
        rows = QmtAdapter().adapt_corporate_actions(_dividend_frame())
        cash = [r for r in rows if r.symbol == "600000"][0]
        assert cash.action_type == "cash_dividend"
        assert cash.ex_date == "2026-06-12"
        assert cash.record_date == "2026-06-11"
        assert cash.currency == "CNY"
        # interest 已是每股 → 换算系数 1.0（真实 datadir 定版，见 field_maps）
        assert cash.amount == pytest.approx(0.35 * DIVIDEND_PER_UNIT)

    def test_bonus_issue_ratio(self):
        rows = QmtAdapter().adapt_corporate_actions(_dividend_frame())
        bonus = [r for r in rows if r.symbol == "000001" and r.action_type == "bonus_issue"][0]
        # 每股送 0.3 转 0.2 → 1 股变 1.5 股
        assert bonus.ratio_from == pytest.approx(1.0)
        assert bonus.ratio_to == pytest.approx(1.5)
        assert bonus.amount is None

    def test_rights_issue_carries_price(self):
        rows = QmtAdapter().adapt_corporate_actions(_dividend_frame())
        rights = [r for r in rows if r.action_type == "rights_issue"][0]
        assert rights.ratio_to == pytest.approx(1.2)   # 每 10 股配 2 股
        assert rights.rights_price == pytest.approx(7.5)

    def test_untrusted_ex_date_is_rejected(self):
        """date_src=ts_key 的除权日实测 437 条错位 → 绝不写可疑值。"""
        rows = QmtAdapter().adapt_corporate_actions(_dividend_frame())
        assert all(r.symbol != "000003" for r in rows)
        assert CORPORATE_ACTIONS_TRUST_TS_KEY is False

    def test_to_db_doc_no_dialect(self):
        rows = QmtAdapter().adapt_corporate_actions(_dividend_frame())
        doc = rows[0].to_db_doc()
        assert doc["data_source"] == "qmt"
        assert doc["market"] == "CN"
        for leaked in ("ts_code", "date_src", "interest", "stock_bonus",
                       "stock_gift", "allot_num", "dr"):
            assert leaked not in doc

    def test_empty(self):
        assert QmtAdapter().adapt_corporate_actions(pd.DataFrame()) == []

    def test_normalizer_routes_corporate_actions(self):
        from app.data.processor.normalizer import NORMALIZE_OK, Normalizer

        result = Normalizer().normalize_with_status(
            _dividend_frame(), "corporate_actions", QmtAdapter()
        )
        assert result.status == NORMALIZE_OK
        assert len(result.records) == 4


class TestDividendWindowFilter:
    def test_injects_ts_code_and_filters_window(self):
        df = _dividend_frame().drop(columns=["ts_code"])
        out = QmtProvider._filter_dividends(df, "600000.SH", "2026-06-01", "2026-06-30")
        assert not out.empty
        assert set(out["ts_code"]) == {"600000.SH"}
        assert set(out["trade_date"]) == {"20260612"}

    def test_window_excludes_out_of_range(self):
        df = _dividend_frame().drop(columns=["ts_code"])
        out = QmtProvider._filter_dividends(df, "600000.SH", "2026-07-01", "2026-07-31")
        assert out.empty

    def test_no_window_returns_all_history(self):
        """事件域允许无窗口（全量历史）——首轮回补场景。"""
        df = _dividend_frame().drop(columns=["ts_code"])
        out = QmtProvider._filter_dividends(df, "600000.SH", "", "")
        assert len(out) == len(df)

    def test_none_frame(self):
        assert QmtProvider._filter_dividends(None, "600000.SH", "", "").empty


# ---------------------------------------------------------------------------
# 保主源写入（FR-07 规则 3）
# ---------------------------------------------------------------------------

_DAY = "2026-10-20"


def _adj(symbol: str, factor: float, source: str = "qmt") -> dict:
    return {
        "symbol": symbol, "market": "CN", "data_source": source,
        "trade_date": _DAY, "adj_factor": factor,
    }


def _install_adj(db):
    from app.data.storage.mongo.collections import get_collection_name
    from tests.data.test_qmt_e2e_chain import _install_bulk_write

    return _install_bulk_write(db, get_collection_name("adj_factors", "CN"))


class TestGuardedWrite:
    async def test_writes_when_no_existing(self, inject_sim_db):
        from app.worker.qmt.guarded_write import write_preserving_primary

        coll = _install_adj(inject_sim_db)
        result = await write_preserving_primary(
            "adj_factors", [_adj("000001", 1.23)], "CN",
            compare_fields=("adj_factor",),
        )
        assert result["written"] == 1
        assert result["compared"] == 0
        assert result["alerted"] is False
        docs = await coll.find({"symbol": "000001"}).to_list(length=5)
        assert docs[0]["adj_factor"] == pytest.approx(1.23)
        assert docs[0]["data_source"] == "qmt"

    async def test_overwrites_own_previous_value(self, inject_sim_db):
        from app.worker.qmt.guarded_write import write_preserving_primary

        coll = _install_adj(inject_sim_db)
        await write_preserving_primary(
            "adj_factors", [_adj("000001", 1.00)], "CN", compare_fields=("adj_factor",)
        )
        await write_preserving_primary(
            "adj_factors", [_adj("000001", 1.23)], "CN", compare_fields=("adj_factor",)
        )
        docs = await coll.find({"symbol": "000001"}).to_list(length=5)
        assert len(docs) == 1
        assert docs[0]["adj_factor"] == pytest.approx(1.23)

    async def test_keeps_existing_primary_value_on_mismatch(self, inject_sim_db):
        """既有 tushare 值 → 不一致时不覆盖（PRD FR-07 规则 3）。"""
        from app.worker.qmt.guarded_write import write_preserving_primary

        coll = _install_adj(inject_sim_db)
        await coll.update_one(
            {"symbol": "000001", "trade_date": _DAY},
            {"$set": _adj("000001", 1.10, source="tushare")}, upsert=True,
        )

        result = await write_preserving_primary(
            "adj_factors", [_adj("000001", 1.23)], "CN",
            compare_fields=("adj_factor",), mismatch_threshold=1.0,
        )
        assert result["written"] == 0
        assert result["kept_existing"] == 1
        assert result["compared"] == 1
        assert result["mismatch_rate"] == pytest.approx(1.0)
        assert result["alerted"] is False    # 100% 不 > 100% 阈值：只保主源不告警
        docs = await coll.find({"symbol": "000001"}).to_list(length=5)
        assert docs[0]["adj_factor"] == pytest.approx(1.10)      # 保留 tushare
        assert docs[0]["data_source"] == "tushare"

    async def test_equal_value_is_skipped_without_rewrite(self, inject_sim_db):
        from app.worker.qmt.guarded_write import write_preserving_primary

        _install_adj(inject_sim_db)
        coll = inject_sim_db["stock_adj_factors"]
        await coll.update_one(
            {"symbol": "000001", "trade_date": _DAY},
            {"$set": _adj("000001", 1.23, source="tushare")}, upsert=True,
        )
        result = await write_preserving_primary(
            "adj_factors", [_adj("000001", 1.23)], "CN", compare_fields=("adj_factor",)
        )
        assert result["skipped_same"] == 1
        assert result["written"] == 0
        assert result["compared"] == 1
        assert result["mismatch_rate"] == 0.0

    async def test_alerts_when_rate_exceeds_threshold(self, inject_sim_db):
        from app.worker.qmt.guarded_write import write_preserving_primary

        _install_adj(inject_sim_db)
        coll = inject_sim_db["stock_adj_factors"]
        # 10 条里 2 条不一致 → 20% > 5%
        records = [_adj(f"0000{i:02d}", 2.0) for i in range(10)]
        for i in range(10):
            await coll.update_one(
                {"symbol": f"0000{i:02d}", "trade_date": _DAY},
                {"$set": {
                    "symbol": f"0000{i:02d}", "market": "CN",
                    "data_source": "tushare", "trade_date": _DAY,
                    "adj_factor": 9.9 if i < 2 else 2.0,
                }}, upsert=True,
            )

        result = await write_preserving_primary(
            "adj_factors", records, "CN",
            compare_fields=("adj_factor",), mismatch_threshold=0.05,
        )
        assert result["compared"] == 10
        assert result["kept_existing"] == 2
        assert result["mismatch_rate"] == pytest.approx(0.2)
        assert result["alerted"] is True

        events = await inject_sim_db["sync_events"].find(
            {"data_source": "qmt_cross_check"}
        ).to_list(length=5)
        assert len(events) == 1
        assert events[0]["mismatch_count"] == 2
        assert events[0]["domain"] == "adj_factors"
        assert events[0]["event_type"] == "SYNC_FAILED"

    async def test_empty_records(self, inject_sim_db):
        from app.worker.qmt.guarded_write import write_preserving_primary

        _install_adj(inject_sim_db)
        result = await write_preserving_primary(
            "adj_factors", [], "CN", compare_fields=("adj_factor",)
        )
        assert result["written"] == 0


class TestAdjFactorsSyncUsesGuard:
    async def test_persist_keeps_primary_source(self, inject_sim_db):
        from app.worker.qmt.jobs import QmtAdjFactorsSync

        coll = _install_adj(inject_sim_db)
        await coll.update_one(
            {"symbol": "000001", "trade_date": _DAY},
            {"$set": _adj("000001", 1.10, source="tushare")}, upsert=True,
        )

        sync = QmtAdjFactorsSync()
        written = await sync._persist([_adj("000001", 1.23)], "qmt")
        assert written == 0
        assert sync.last_guard["kept_existing"] == 1

        docs = await coll.find({"symbol": "000001"}).to_list(length=5)
        assert docs[0]["data_source"] == "tushare"


class TestCapabilityWiring:
    def test_corporate_actions_is_qmt_only(self):
        """CN 既有源无 corporate_actions 通道 → 该域 qmt 是唯一源，不是回退末位。"""
        from app.core.config import settings
        from app.data.core.registry.capability import CapabilityRegistry

        old = settings.QMT_ENABLED
        settings.QMT_ENABLED = True
        try:
            chain = CapabilityRegistry().get_ordered_sources("CN", "corporate_actions")
        finally:
            settings.QMT_ENABLED = old
        assert chain == ["qmt"]

    def test_corporate_actions_absent_when_disabled(self):
        from app.core.config import settings
        from app.data.core.registry.capability import CapabilityRegistry

        old = settings.QMT_ENABLED
        settings.QMT_ENABLED = False
        try:
            chain = CapabilityRegistry().get_ordered_sources("CN", "corporate_actions")
        finally:
            settings.QMT_ENABLED = old
        assert chain == []
