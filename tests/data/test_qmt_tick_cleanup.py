"""tick 保留期清理 Job 测试（PRD FR-06 规则 3 / DD-03）。

为什么独立成文件：清理 Job 属于「运维作业」交付批次（tick_cleanup.py），
与 tick_quotes 域本身的治理测试（test_tick_quotes_domain.py）不是同一批交付，
拆开后每个 PR 的测试可以独立跑通。

覆盖：
- cutoff 计算（按自然日，禁止 0/负数清空全表）
- 保留天数解析链（显式入参 → Web UI → ENV/Settings）
- 只删保留期外分区 + `sync_events` 审计（`data_source=qmt_tick_cleanup`）
- 源关闭时跳过清理（PRD 10.4：回滚后已入库数据保留无害）
"""

import pytest

from tests.data.test_tick_quotes_domain import _install, _row


class TestCleanupCutoff:
    def test_cutoff_is_natural_days_before_today(self):
        from datetime import datetime

        from app.worker.qmt.tick_cleanup import _cutoff_date

        assert _cutoff_date(60, datetime(2026, 10, 21)) == "2026-08-22"
        assert _cutoff_date(1, datetime(2026, 3, 1)) == "2026-02-28"

    def test_retention_resolution_prefers_explicit_then_settings(self):
        from app.core.config import settings
        from app.worker.qmt.tick_cleanup import _resolve_retention_days

        assert _resolve_retention_days(7) == 7
        assert _resolve_retention_days(0) == 1  # 下界钳制，禁止 0/负数清空全表
        default_days = _resolve_retention_days()
        assert default_days >= 1
        assert default_days == max(1, int(settings.QMT_TICK_RETENTION_DAYS))


@pytest.mark.asyncio
async def test_cleanup_deletes_only_expired_partitions(inject_sim_db):
    """只删保留期外的分区，并写 sync_events 审计（PRD FR-06 GWT）。"""
    from datetime import datetime, timedelta

    from app.core.config import settings
    from app.worker.qmt.tick_cleanup import cleanup_qmt_tick

    coll = _install(inject_sim_db, "tick_quotes")
    repo_rows = [
        _row("000001", "2026-01-05", 1000),   # 远超保留期 → 应删
        _row("000001", "2026-02-10", 1000),   # 远超保留期 → 应删
        _row("000001", datetime.now().strftime("%Y-%m-%d"), 1000),  # 当日 → 保留
    ]
    for r in repo_rows:
        await coll._inner.insert_one(dict(r))

    old_enabled = settings.QMT_ENABLED
    settings.QMT_ENABLED = True
    try:
        result = await cleanup_qmt_tick(retention_days=60)
    finally:
        settings.QMT_ENABLED = old_enabled

    assert result["success"] is True
    assert result["deleted"] == 2
    assert result["retention_days"] == 60
    expected_cutoff = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
    assert result["cutoff_date"] == expected_cutoff

    remaining = await coll.find({}).to_list(length=10)
    assert len(remaining) == 1

    events = await inject_sim_db["sync_events"].find(
        {"data_source": "qmt_tick_cleanup"}
    ).to_list(length=5)
    assert len(events) == 1
    assert events[0]["event_type"] == "SYNC_SUCCESS"
    assert events[0]["domain"] == "tick_quotes"
    assert events[0]["record_count"] == 2
    assert events[0]["cutoff_date"] == expected_cutoff
    assert events[0]["retention_days"] == 60


@pytest.mark.asyncio
async def test_cleanup_skips_when_source_disabled(inject_sim_db):
    """QMT_ENABLED=false 时不清理（PRD 10.4：回滚后已入库数据保留无害）。"""
    from app.core.config import settings
    from app.worker.qmt.tick_cleanup import cleanup_qmt_tick

    coll = _install(inject_sim_db, "tick_quotes")
    await coll._inner.insert_one(_row("000001", "2020-01-02", 1000))

    old_enabled = settings.QMT_ENABLED
    settings.QMT_ENABLED = False
    try:
        result = await cleanup_qmt_tick(retention_days=1)
    finally:
        settings.QMT_ENABLED = old_enabled

    assert result["success"] is False
    assert result.get("skipped") is True
    assert result["deleted"] == 0
    assert len(await coll.find({}).to_list(length=10)) == 1
    assert not await inject_sim_db["sync_events"].find(
        {"data_source": "qmt_tick_cleanup"}
    ).to_list(length=1)
