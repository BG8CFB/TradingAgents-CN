"""MCP 管理面（配置/校验/健康/任务管理）。

连接执行与工具发现已迁移至新层 app/llm/mcp（官方 mcp SDK）；
本包保留配置文件管理与运维能力，供 routers/mcp 与管理界面使用。
"""

from .config_utils import (
    MCPServerConfig,
    MCPServerType,
    HealthCheckConfig,
    load_mcp_config,
    write_mcp_config,
    validate_servers_map,
)
from .health_monitor import (
    HealthMonitor,
    ServerStatus,
    ServerHealthInfo,
)
from .config_validator import (
    validate_config_file,
    validate_config_dict,
    validate_command_path,
    validate_url_format,
    ValidationResult,
    ValidationError,
)
from .task_manager import (
    TaskLevelMCPManager,
    get_task_mcp_manager,
    remove_task_mcp_manager,
    cleanup_all_managers,
    CircuitBreaker,
    RetryMechanism,
    CircuitState,
    CircuitBreakerConfig,
    RetryConfig,
)

__all__ = [
    # Config
    "MCPServerConfig",
    "MCPServerType",
    "HealthCheckConfig",
    "load_mcp_config",
    "write_mcp_config",
    "validate_servers_map",
    # Health Monitor
    "HealthMonitor",
    "ServerStatus",
    "ServerHealthInfo",
    # Config Validator
    "validate_config_file",
    "validate_config_dict",
    "validate_command_path",
    "validate_url_format",
    "ValidationResult",
    "ValidationError",
    # Task Manager
    "TaskLevelMCPManager",
    "get_task_mcp_manager",
    "remove_task_mcp_manager",
    "cleanup_all_managers",
    "CircuitBreaker",
    "RetryMechanism",
    "CircuitState",
    "CircuitBreakerConfig",
    "RetryConfig",
]
