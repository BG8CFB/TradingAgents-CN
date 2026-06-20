"""
Queue 子包
- keys: Redis 键名
- helpers: 队列相关的 Redis 操作辅助函数

并发上限 / 可见性超时等配置默认值已迁移到 ``app.core.config.settings``，
子包不再导出 ``DEFAULT_USER_CONCURRENT_LIMIT`` / ``GLOBAL_CONCURRENT_LIMIT`` /
``VISIBILITY_TIMEOUT_SECONDS``；调用方请改用 ``settings.*``。
"""
from .keys import (
    READY_LIST,
    TASK_PREFIX,
    BATCH_PREFIX,
    SET_PROCESSING,
    SET_COMPLETED,
    SET_FAILED,
    SET_DEAD_LETTER,
    BATCH_TASKS_PREFIX,
    USER_PROCESSING_PREFIX,
    GLOBAL_CONCURRENT_KEY,
    VISIBILITY_TIMEOUT_PREFIX,
)

from .helpers import (
    check_user_concurrent_limit,
    check_global_concurrent_limit,
    mark_task_processing,
    unmark_task_processing,
    set_visibility_timeout,
    clear_visibility_timeout,
)

__all__ = [
    "READY_LIST",
    "TASK_PREFIX",
    "BATCH_PREFIX",
    "SET_PROCESSING",
    "SET_COMPLETED",
    "SET_FAILED",
    "SET_DEAD_LETTER",
    "BATCH_TASKS_PREFIX",
    "USER_PROCESSING_PREFIX",
    "GLOBAL_CONCURRENT_KEY",
    "VISIBILITY_TIMEOUT_PREFIX",
    "check_user_concurrent_limit",
    "check_global_concurrent_limit",
    "mark_task_processing",
    "unmark_task_processing",
    "set_visibility_timeout",
    "clear_visibility_timeout",
]

