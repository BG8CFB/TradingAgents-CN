"""数据层测试共享 fixtures。

提供 SimulatedMongoDB 注入、DataInterface 构造、SchedulerEngine 构造等 fixture，
替代 unittest.mock.patch 方案，使用真实的代码路径 + 内存数据库。
"""

import os
import pytest

from test_infra import SimulatedMongoDB, SimulatedRedis


# ============================================================
# SimulatedMongoDB 注入 — 直接替换 _motor_db 全局变量
# ============================================================

@pytest.fixture
def sim_db_fresh():
    """创建全新的 SimulatedMongoDB 实例（每个测试独立）。"""
    return SimulatedMongoDB()


@pytest.fixture
def inject_sim_db(sim_db_fresh):
    """将 SimulatedMongoDB 注入到 app.data.storage.mongo.client._motor_db。

    直接替换全局 _motor_db 变量，使所有通过 get_motor_db() 获取数据库的代码
    走内存模拟，而不是连接真实 MongoDB。
    """
    from app.data.storage.mongo import client as mongo_client

    original = mongo_client._motor_db
    mongo_client._motor_db = sim_db_fresh
    yield sim_db_fresh
    mongo_client._motor_db = original


# ============================================================
# MetadataRepo 基于 SimulatedMongoDB
# ============================================================

@pytest.fixture
def metadata_repo(inject_sim_db):
    """创建使用 SimulatedMongoDB 的 MetadataRepo 实例。"""
    from app.data.storage.mongo.repositories.metadata_repo import MetadataRepo
    return MetadataRepo()


# ============================================================
# CheckpointManager 基于 SimulatedMongoDB
# ============================================================

@pytest.fixture
def checkpoint_manager(inject_sim_db):
    """创建使用 SimulatedMongoDB 的 CheckpointManager 实例。"""
    from app.data.scheduler.checkpoint import CheckpointManager
    return CheckpointManager()


# ============================================================
# SchedulerEngine fixture
# ============================================================

@pytest.fixture
def scheduler_engine():
    """创建 SchedulerEngine 实例（不启动调度器）。"""
    from app.data.scheduler.engine import SchedulerEngine
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    # 重置单例，确保每个测试获得独立实例
    SchedulerEngine._instance = None
    scheduler = AsyncIOScheduler(timezone="UTC")
    engine = SchedulerEngine(scheduler=scheduler)
    yield engine
    if engine._scheduler.running:
        engine._scheduler.shutdown(wait=False)
    SchedulerEngine._instance = None


# ============================================================
# FallbackRouter fixture
# ============================================================

@pytest.fixture
def fallback_router():
    """创建使用真实 CapabilityRegistry + PriorityConfig 的 FallbackRouter。"""
    from app.data.processor.fallback_router import FallbackRouter
    from app.data.core.registry.capability import CapabilityRegistry
    from app.data.core.registry.priority import PriorityConfig

    registry = CapabilityRegistry()
    priority = PriorityConfig()
    return FallbackRouter(registry, priority)


# ============================================================
# DataInterface fixture
# ============================================================

@pytest.fixture
def data_interface():
    """创建 DataInterface 实例（使用真实 Reader/Registry/PriorityConfig）。"""
    from app.data.core.interface import DataInterface
    DataInterface.reset_instance()
    di = DataInterface()
    yield di
    DataInterface.reset_instance()


# ============================================================
# 临时 YAML 配置 fixture
# ============================================================

@pytest.fixture
def sample_schedule_yaml(tmp_path):
    """创建包含 cron 调度配置的临时 YAML 文件。"""
    import yaml
    config = {
        "daily_quotes": {
            "cron": "15 16 * * 1-5",
            "timezone": "Asia/Shanghai",
            "mode": "incremental",
        },
        "basic_info": {
            "cron": "0 9 * * *",
            "timezone": "Asia/Shanghai",
            "mode": "full",
        },
    }
    path = tmp_path / "schedule.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True)
    return str(path)


@pytest.fixture
def sample_schedule_yaml_no_cron(tmp_path):
    """创建不含 cron 字段的 YAML。"""
    import yaml
    config = {
        "daily_quotes": {
            "timezone": "Asia/Shanghai",
            "mode": "incremental",
        },
    }
    path = tmp_path / "schedule_no_cron.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True)
    return str(path)


@pytest.fixture
def sample_schedule_yaml_empty(tmp_path):
    """创建空的 YAML 文件。"""
    path = tmp_path / "schedule_empty.yaml"
    path.write_text("", encoding="utf-8")
    return str(path)
