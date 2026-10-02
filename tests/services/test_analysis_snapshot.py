"""analysis_service 执行计划快照落库测试（真实 Mongo I/O）。

契约：_save_analysis_result_web_style 从 result["state"] 提取 _plan_snapshot →
任务/报告文档存 workflow_snapshot 字段，且对外 state 剥离该键。
"""

import pytest

from app.services.analysis_service import AnalysisService

pytestmark = pytest.mark.requires_db


@pytest.mark.asyncio
async def test_save_extracts_workflow_snapshot(real_mongo_db):
    db = real_mongo_db
    task_id = "t-snap-test"
    snap = {
        "workflow_slug": "default-4stage",
        "spec_version": 1,
        "spec_hash": "sha256:test",
        "params": {"selected_nodes": ["market-analyst"], "stage_overrides": {}},
        "compiled_at": "2026-09-14T00:00:00+00:00",
    }
    result = {
        "stock_symbol": "000001",
        "analysis_date": "2026-09-14",
        "state": {"final_trade_decision": "hold", "_plan_snapshot": snap},
        "decision": {"action": "观望"},
        "reports": {"market_report": "content"},
    }
    try:
        # 任务文档由任务创建流程预写（update_one 非 upsert），此处模拟该前置
        await db.analysis_tasks.insert_one({"task_id": task_id, "status": "running"})
        service = AnalysisService()
        await service._save_analysis_result_web_style(task_id, result)

        # 对外 state 已剥离快照（内部执行元数据不外泄）
        assert "_plan_snapshot" not in result["state"]

        report_doc = await db.analysis_reports.find_one({"task_id": task_id})
        task_doc = await db.analysis_tasks.find_one({"task_id": task_id})
        assert report_doc is not None and task_doc is not None
        assert report_doc["workflow_snapshot"] == snap
        assert task_doc["result"]["workflow_snapshot"] == snap
    finally:
        await db.analysis_reports.delete_many({"task_id": task_id})
        await db.analysis_tasks.delete_many({"task_id": task_id})
