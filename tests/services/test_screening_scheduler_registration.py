"""Exercise the real scheduler registry without running any data or model job."""

import ast
import asyncio
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.worker.screening_jobs import JOB_ID, register_screening_jobs, run_screening_daily_recommendations


async def test_registration_is_idempotent_and_does_not_execute():
    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    scheduler.start(paused=True)
    try:
        register_screening_jobs(scheduler)
        register_screening_jobs(scheduler)
        jobs = scheduler.get_jobs()
        assert len(jobs) == 1
        job = scheduler.get_job(JOB_ID)
        assert job.func is run_screening_daily_recommendations
        assert job.max_instances == 1
        assert job.coalesce is True
        assert job.misfire_grace_time == 600
        assert "hour='20'" in str(job.trigger) and "minute='47'" in str(job.trigger)
        assert scheduler.state == 2  # paused; no startup/catch-up invocation
    finally:
        scheduler.shutdown(wait=False)
        await asyncio.sleep(0)


def test_current_startup_wires_consumer_without_old_bulk_registration():
    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / "app/main.py").read_text(encoding="utf-8"))
    init = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                and node.name == "_init_scheduler")
    names = [node.func.id for node in ast.walk(init) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name)]
    assert names.count("register_screening_jobs") == 1
    assert "register_jobs" not in names


def test_screening_consumers_do_not_import_data_layer_internals():
    root = Path(__file__).resolve().parents[2]
    consumers = list((root / "app/services/screening").glob("*.py"))
    consumers.append(root / "app/routers/screening.py")
    for path in consumers:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
            elif isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
        assert not any(module.startswith(("app.data.storage", "app.data.sources"))
                       for module in imports), str(path)
