"""
A 股 Worker 同步任务

通过 CNSyncOrchestrator 域级编排器统一调度，支持依赖链并行、
自动源选择、增量同步和交易时间检查。
"""

from app.worker.cn.cn_sync_orchestrator import (
    CNSyncOrchestrator,
    get_cn_sync_orchestrator,
)
