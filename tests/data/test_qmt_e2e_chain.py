"""QMT 端到端链路验证 — datadir → Provider → FallbackRouter → Normalizer
→ Validator → Repo → Mongo 文档（PRD 九「格式一致性验收」「回退验收」）。

使用 SimulatedMongoDB（项目测试规约，禁用 unittest.mock）走真实代码路径。
本文件内的 _BulkWriteCapableCollection 仅为弥补 SimulatedMongoDB 不支持
bulk_write 的缺口（Repo.upsert_many 依赖），逻辑等价于 UpdateOne upsert。

验证：
1. 熔断 tushare/akshare/baostock 后，daily_quotes 自动经 qmt 成功回退；
2. 入库文档与既有源同集合、同 Schema、无 QMT 专用字段；
3. basic_info 的 partial 数据（无 name）通过校验并入库，且不覆盖既有名称；
4. QMT_ENABLED=false 时全链路不选 qmt。
"""

from datetime import date, timedelta

import pytest

from app.data.core.registry.capability import CapabilityRegistry
from app.data.core.registry.priority import PriorityConfig
from app.data.processor.fallback_router import FallbackRouter
from app.data.storage.mongo.collections import get_collection_name
from tests.data.test_qmt_datadir_reader import _recent_records, _write_kline_file

_D2 = (date.today() - timedelta(days=2)).isoformat()
_D1 = (date.today() - timedelta(days=1)).isoformat()
_D0 = date.today().isoformat()

_CHAIN = ("tushare", "akshare", "baostock")


def _mk_tree(tmp_path):
    recs = _recent_records([2, 1, 0])
    _write_kline_file(tmp_path / 'SH' / '86400' / '000001.DAT', recs)
    _write_kline_file(tmp_path / 'SZ' / '86400' / '000001.DAT', recs)
    _write_kline_file(tmp_path / 'SH' / '86400' / '600000.DAT', recs)
    return tmp_path


def _open_chain_breakers(router: FallbackRouter, domain: str) -> None:
    """把既有三源打到熔断打开状态（回退演练前提）。"""
    for src in _CHAIN:
        for _ in range(10):
            router._circuit.record_failure(src, domain=domain, market="CN")


def _enable_qmt(monkeypatch, tmp_path) -> None:
    from app.core.config import settings

    monkeypatch.setattr(
        "app.data.sources.cn.qmt.provider.get_qmt_datadir", lambda: str(tmp_path)
    )
    monkeypatch.setattr(settings, "QMT_ENABLED", True)


class _BulkWriteCapableCollection:
    """SimulatedMongoCollection 的 bulk_write 适配（测试专用）。

    不继承原类以避免导入路径耦合；仅实现 Repo upsert 所需的子集：
    update_one/upsert、find/find_one、count_documents、delete_many。
    直接委托给一个内部 SimulatedMongoCollection 实例。
    """

    def __init__(self):
        from tests.test_infra import SimulatedMongoCollection

        self._inner = SimulatedMongoCollection()

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def bulk_write(self, ops, ordered=False):
        upserted = modified = 0
        for op in ops:
            flt = getattr(op, "_filter", {}) or {}
            doc = getattr(op, "_doc", {}) or {}
            set_doc = doc.get("$set", {})
            existing = await self._inner.find_one(flt)
            if existing is None:
                merged = dict(flt)
                merged.update(set_doc)
                self._inner._insert(merged)
                upserted += 1
            else:
                existing.update(set_doc)
                modified += 1
        return type(
            "Result", (), {"upserted_count": upserted, "modified_count": modified}
        )()


def _install_bulk_write(db, collection_name: str):
    coll = _BulkWriteCapableCollection()
    db._collections[collection_name] = coll
    return coll


@pytest.mark.asyncio
async def test_fallback_to_qmt_when_others_circuit_open(tmp_path, inject_sim_db, monkeypatch):
    """回退演练（PRD 3.2 核心验收）：既有源全部熔断 → qmt 兜底成功。"""
    _mk_tree(tmp_path)
    _enable_qmt(monkeypatch, tmp_path)

    router = FallbackRouter(CapabilityRegistry(), PriorityConfig())
    _open_chain_breakers(router, "daily_quotes")

    result = await router.fetch("CN", "daily_quotes", "000001", _D1, _D1)
    assert result.success is True, f"回退失败: {result.error}"
    assert result.source == "qmt"
    # 熔断中的源以 skip 语义跳过（平台既有语义），三项都应已打开
    for src in _CHAIN:
        assert router._circuit.is_open(src, domain="daily_quotes", market="CN")

    assert len(result.records) == 1
    rec = result.records[0]

    # ── 格式一致性（D-5）：与既有源同 Schema 字段 ──
    assert rec["symbol"] == "000001"
    assert rec["market"] == "CN"
    assert rec["data_source"] == "qmt"
    assert rec["trade_date"] == _D1
    assert rec["period"] == "daily"
    assert rec["volume"] == pytest.approx(200_000.0)   # _D1 记录 2000 手 → 20 万股
    assert rec["close"] == 11.0
    assert rec["pre_close"] == 10.5
    assert rec["pct_chg"] == pytest.approx(round(0.5 / 10.5 * 100, 4))
    # 无 QMT 专用旁路字段（D-5 反指标：禁止 QMT 专用表/字段）
    for leaked in ("preClose", "suspendFlag", "adj_f_evt", "adj_f_cum", "time"):
        assert leaked not in rec


@pytest.mark.asyncio
async def test_repo_upsert_writes_same_collection(tmp_path, inject_sim_db, monkeypatch):
    """入库验证：qmt 数据写入既有 stock_daily_quotes 集合，文档结构与其他源一致。"""
    from app.data.storage.mongo.repositories.daily_quotes_repo import DailyQuotesRepo

    _mk_tree(tmp_path)
    _enable_qmt(monkeypatch, tmp_path)
    coll_name = get_collection_name("daily_quotes", "CN")
    coll = _install_bulk_write(inject_sim_db, coll_name)

    router = FallbackRouter(CapabilityRegistry(), PriorityConfig())
    _open_chain_breakers(router, "daily_quotes")

    result = await router.fetch("CN", "daily_quotes", "000001", _D2, _D0)
    assert result.success and result.source == "qmt"
    assert len(result.records) == 3

    count = await DailyQuotesRepo().upsert_many(result.records, "CN")
    assert count == 3

    docs = await coll.find({"symbol": "000001"}).to_list(length=10)
    assert len(docs) == 3
    for d in docs:
        assert d["data_source"] == "qmt"
        assert d["period"] == "daily"
        assert "trade_date" in d and "close" in d and "volume" in d
        assert d["volume"] > 0


@pytest.mark.asyncio
async def test_basic_info_partial_merges_without_overwrite(
    tmp_path, inject_sim_db, monkeypatch,
):
    """basic_info 合并语义（FR-05）：qmt 只写代码，不覆盖既有源已入库的 name。"""
    from app.data.storage.mongo.repositories.basic_info_repo import BasicInfoRepo

    _mk_tree(tmp_path)
    _enable_qmt(monkeypatch, tmp_path)
    coll_name = get_collection_name("basic_info", "CN")
    coll = _install_bulk_write(inject_sim_db, coll_name)
    await coll.update_one(
        {"symbol": "000001"}, {"$set": {
            "symbol": "000001", "market": "CN", "name": "平安银行",
            "industry": "银行", "data_source": "tushare",
        }}, upsert=True,
    )

    router = FallbackRouter(CapabilityRegistry(), PriorityConfig())
    _open_chain_breakers(router, "basic_info")

    result = await router.fetch("CN", "basic_info", "__all__")
    assert result.success and result.source == "qmt"
    assert len(result.records) == 2  # 000001.SZ + 600000.SH
    for rec in result.records:
        assert "name" not in rec  # partial：无名称键，upsert 不覆盖

    await BasicInfoRepo().upsert_many(result.records, "CN")
    doc = await coll.find_one({"symbol": "000001"})
    assert doc["name"] == "平安银行"        # 既有名称未被 qmt 覆盖
    assert doc["industry"] == "银行"
    assert doc["exchange"] == "SZSE"        # qmt 补充的交易所字段


@pytest.mark.asyncio
async def test_disabled_qmt_excluded_end_to_end(tmp_path, inject_sim_db, monkeypatch):
    """开关关闭时：即便 datadir 就绪，路由也不会选 qmt（FR-09 GWT 全链路）。"""
    from app.core.config import settings

    _mk_tree(tmp_path)
    monkeypatch.setattr(
        "app.data.sources.cn.qmt.provider.get_qmt_datadir", lambda: str(tmp_path)
    )
    monkeypatch.setattr(settings, "QMT_ENABLED", False)

    router = FallbackRouter(CapabilityRegistry(), PriorityConfig())
    _open_chain_breakers(router, "daily_quotes")

    result = await router.fetch("CN", "daily_quotes", "000001", _D1, _D1)
    assert result.success is False
    assert result.source is None


@pytest.mark.asyncio
async def test_worker_reports_health_on_failure(tmp_path, inject_sim_db, monkeypatch):
    """worker 就绪失败时写 health + sync_events（PRD FR-02/FR-13 闭环）。"""
    from app.core.config import settings

    monkeypatch.setattr(
        "app.data.sources.cn.qmt.provider.get_qmt_datadir", lambda: ""
    )
    monkeypatch.setattr(
        "app.data.sources.cn.qmt.health.get_qmt_datadir", lambda: str(tmp_path / "nope")
    )
    monkeypatch.setattr(settings, "QMT_ENABLED", True)

    from app.worker.qmt.jobs import run_qmt_sync

    result = await run_qmt_sync(force=True)
    assert result["success"] is False

    health = await inject_sim_db["source_health"].find({"source": "qmt"}).to_list(length=5)
    assert len(health) == 1
    assert health[0]["datadir_state"] == "path_missing"

    events = await inject_sim_db["sync_events"].find({"source": "qmt"}).to_list(length=5)
    assert len(events) == 1
    assert events[0]["error_code"] == "path_missing"
