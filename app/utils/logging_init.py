"""
日志系统初始化模块（兼容层）

核心初始化逻辑已迁移到 app.utils.logging_manager。
本文件仅保留 re-export 以兼容旧 import 路径。
新代码请直接使用: from app.utils.logging_manager import get_logger
"""

from app.utils.logging_manager import get_logger, setup_logging  # noqa: F401


def setup_dataflow_logging():
    """设置数据流专用日志（兼容旧调用）"""
    return get_logger('dataflows')
