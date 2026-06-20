"""
队列服务用到的 Redis 键名（集中定义）

并发上限、可见性超时等"配置默认值"不在此处定义，统一由
``app.core.config.settings`` 提供（``DEFAULT_USER_CONCURRENT_LIMIT`` /
``GLOBAL_CONCURRENT_LIMIT`` / ``QUEUE_VISIBILITY_TIMEOUT``）。
这样 .env 与运行期动态配置只有唯一数据源，避免 keys.py 与 config.py
双重定义漂移（历史问题：keys.py=3 / config.py=50 并存导致行为不确定）。
"""

# Redis键名常量
READY_LIST = "qa:ready"

TASK_PREFIX = "qa:task:"
BATCH_PREFIX = "qa:batch:"
SET_PROCESSING = "qa:processing"
SET_COMPLETED = "qa:completed"
SET_FAILED = "qa:failed"
SET_DEAD_LETTER = "qa:dead_letter"
BATCH_TASKS_PREFIX = "qa:batch_tasks:"

# 并发控制相关
USER_PROCESSING_PREFIX = "qa:user_processing:"
GLOBAL_CONCURRENT_KEY = "qa:global_concurrent"
VISIBILITY_TIMEOUT_PREFIX = "qa:visibility:"

