import json
import logging
import os
import platform
import shutil
from contextlib import nullcontext
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.env import get_env

try:  # 轻量文件锁，避免并发写入损坏；若未安装则降级为无锁
    from filelock import FileLock
except Exception:  # pragma: no cover - 可选依赖
    FileLock = None  # type: ignore

try:
    # Pydantic v2
    from pydantic import BaseModel, Field, field_validator, model_validator
    PYDANTIC_V2 = True
except ImportError:  # pragma: no cover - 兼容 pydantic v1
    from pydantic import BaseModel, Field, validator as field_validator, root_validator as model_validator  # type: ignore
    PYDANTIC_V2 = False

logger = logging.getLogger(__name__)


class MCPServerType(str, Enum):
    """MCP 服务器类型枚举"""
    STDIO = "stdio"
    HTTP = "http"
    STREAMABLE_HTTP = "streamable-http"  # MCP 官方新标准传输协议

# 项目根目录的 config/ 目录（而非 tradingagents/config/）
BASE_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"

# 优先从环境变量获取默认配置路径
_env_config_path = get_env("MCP_CONFIG_PATH")
DEFAULT_CONFIG_FILE = Path(_env_config_path) if _env_config_path else BASE_CONFIG_DIR / "mcp.json"


def _safe_is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except Exception as e:
        logger.debug(f"路径相对检查失败: {path} vs {base}: {e}")
        return False


def _allowed_commands() -> set:
    env_value = get_env("MCP_ALLOWED_COMMANDS", "")
    return {c.strip() for c in env_value.split(",") if c.strip()}


def _allowed_roots() -> List[Path]:
    env_value = get_env("MCP_ALLOWED_ROOTS", "")
    roots: List[Path] = []
    for part in env_value.split(os.pathsep):
        if part.strip():
            roots.append(Path(part).expanduser().resolve())
    # 默认允许 config 目录，避免意外写入工作目录之外
    roots.append(BASE_CONFIG_DIR.resolve())
    return roots


_IS_WINDOWS = platform.system() == "Windows"

_COMMAND_FALLBACKS: Dict[str, List[str]] = {
    "uvx": ["uv", "uvx"],
    "npx": ["npx", "npx.cmd", "npm"],
}

_RESOLVED_COMMAND_CACHE: Dict[str, Optional[str]] = {}


def resolve_command(command: str) -> Tuple[str, Optional[str]]:
    """
    解析 MCP 服务器命令，解决跨平台兼容性问题。

    在 Windows 上，uvx/npx 等脚本包装器可能无法直接被 subprocess 找到，
    需要通过 shutil.which 解析完整路径，或回退到替代命令。

    Args:
        command: 原始命令名称（如 "uvx", "npx"）

    Returns:
        (resolved_command, error_message)
        - resolved_command: 解析后的命令（可能是原始命令、完整路径或回退命令）
        - error_message: 如果解析失败，返回错误信息；成功则为 None
    """
    if not command:
        return command, "命令为空"

    if Path(command).is_absolute():
        if os.path.isfile(command):
            return command, None
        return command, f"绝对路径命令不存在: {command}"

    cmd_name = Path(command).name

    if cmd_name in _RESOLVED_COMMAND_CACHE:
        cached = _RESOLVED_COMMAND_CACHE[cmd_name]
        if cached is not None:
            return cached, None
        return command, f"命令 '{cmd_name}' 未找到（已缓存）"

    resolved = shutil.which(command)
    if resolved:
        _RESOLVED_COMMAND_CACHE[cmd_name] = resolved
        logger.debug("[MCP] 命令解析: %s -> %s", command, resolved)
        return resolved, None

    fallbacks = _COMMAND_FALLBACKS.get(cmd_name, [])
    for fb in fallbacks:
        if fb == command:
            continue
        fb_resolved = shutil.which(fb)
        if fb_resolved:
            _RESOLVED_COMMAND_CACHE[cmd_name] = fb_resolved
            logger.info("[MCP] 命令回退: %s -> %s (%s)", command, fb, fb_resolved)
            return fb_resolved, None

    if cmd_name == "uvx":
        _RESOLVED_COMMAND_CACHE[cmd_name] = None
        msg = (
            f"命令 '{command}' 未找到。"
            "请安装 uv: pip install uv 或 https://docs.astral.sh/uv/getting-started/installation/"
        )
        return command, msg

    if cmd_name == "npx":
        _RESOLVED_COMMAND_CACHE[cmd_name] = None
        msg = (
            f"命令 '{command}' 未找到。"
            "请安装 Node.js: https://nodejs.org/"
        )
        return command, msg

    _RESOLVED_COMMAND_CACHE[cmd_name] = None
    return command, f"命令 '{command}' 未找到，请确认已安装并添加到 PATH"


def check_command_available(command: str) -> Tuple[bool, Optional[str]]:
    """
    检查命令是否可用（不修改命令，仅检查）。

    Returns:
        (is_available, error_message)
    """
    if not command:
        return False, "命令为空"

    resolved = shutil.which(command)
    if resolved:
        return True, None

    cmd_name = Path(command).name
    fallbacks = _COMMAND_FALLBACKS.get(cmd_name, [])
    for fb in fallbacks:
        if shutil.which(fb):
            return True, None

    return False, f"命令 '{command}' 未找到，请确认已安装并添加到 PATH"


def clear_command_cache() -> None:
    """清除命令解析缓存（用于测试或重新检测环境）"""
    _RESOLVED_COMMAND_CACHE.clear()


class HealthCheckConfig(BaseModel):
    """健康检查配置"""
    enabled: bool = Field(default=True, description="是否启用健康检查")
    interval: int = Field(default=60, ge=10, le=3600, description="检查间隔（秒）")
    timeout: int = Field(default=10, ge=1, le=60, description="超时时间（秒）")


class MCPServerConfig(BaseModel):
    """
    服务器配置模型：支持 stdio 和 HTTP 两种模式。
    - stdio 模式：通过子进程通信，需要 command 和 args
    - HTTP 模式：通过 HTTP 协议通信，需要 url
    """

    type: MCPServerType = Field(default=MCPServerType.STDIO, description="服务器类型")
    # stdio 模式字段
    command: Optional[str] = Field(default=None, min_length=1, max_length=256, description="可执行程序路径或名称")
    args: List[str] = Field(default_factory=list, max_length=32)
    env: Dict[str, str] = Field(default_factory=dict)
    # HTTP 模式字段
    url: Optional[str] = Field(default=None, max_length=2048, description="HTTP 服务器 URL")
    headers: Dict[str, str] = Field(default_factory=dict, description="HTTP 请求头")
    # 通用字段
    description: Optional[str] = Field(default=None, max_length=500)
    enabled: bool = Field(default=True, alias="_enabled", description="内部启用标记")
    healthCheck: Optional[HealthCheckConfig] = Field(default=None, description="健康检查配置")

    model_config = {"extra": "ignore", "populate_by_name": True, "use_enum_values": True}

    @field_validator("command", mode="before")
    @classmethod
    def _validate_command(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if any(ch in value for ch in ("\n", "\r", "\t")):
            raise ValueError("command 含有非法控制字符")

        allowed_commands = _allowed_commands()
        command_path = Path(value).expanduser()

        # 允许列表存在时，必须命中
        if allowed_commands:
            if command_path.name not in allowed_commands and value not in allowed_commands:
                raise ValueError("command 不在允许列表中，请配置 MCP_ALLOWED_COMMANDS")
        else:
            # 未配置 allowlist 时，仅允许相对路径，避免意外绝对路径执行
            if command_path.is_absolute():
                raise ValueError("未配置 MCP_ALLOWED_COMMANDS 时禁止使用绝对路径 command")

        # 如果是绝对路径，需落在允许根目录
        if command_path.is_absolute():
            roots = _allowed_roots()
            if not any(_safe_is_relative_to(command_path, root) for root in roots):
                raise ValueError("command 不在允许的根目录下")

        return value

    @field_validator("url", mode="before")
    @classmethod
    def _validate_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if not value.startswith(("http://", "https://")):
            raise ValueError("url 必须以 http:// 或 https:// 开头")
        if len(value) > 2048:
            raise ValueError("url 过长")
        return value

    @field_validator("headers", mode="before")
    @classmethod
    def _validate_headers(cls, value: Dict[str, Any]) -> Dict[str, str]:
        if not value:
            return {}
        sanitized: Dict[str, str] = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise ValueError("headers key 必须为字符串")
            if len(k) > 128:
                raise ValueError("headers key 过长")
            sanitized[k] = "" if v is None else str(v)
        return sanitized

    @field_validator("args", mode="before")
    @classmethod
    def _validate_args(cls, value: List[str]) -> List[str]:
        if not value:
            return []
        result = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("args 必须为字符串列表")
            if len(item) > 512:
                raise ValueError("单个参数过长")
            result.append(item)
        return result

    @field_validator("env", mode="before")
    @classmethod
    def _validate_env(cls, value: Dict[str, Any]) -> Dict[str, str]:
        if not value:
            return {}
        sanitized: Dict[str, str] = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise ValueError("env key 必须为字符串")
            if len(k) > 128:
                raise ValueError("env key 过长")
            sanitized[k] = "" if v is None else str(v)
        return sanitized

    @model_validator(mode="before")
    @classmethod
    def _ensure_enabled(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(values, dict):
            if "_enabled" not in values and "enabled" not in values:
                values["_enabled"] = True
        return values

    @model_validator(mode="after")
    def _validate_server_type(self) -> "MCPServerConfig":
        """根据服务器类型验证必需字段"""
        server_type = self.type
        # 处理字符串类型
        if isinstance(server_type, str):
            server_type = MCPServerType(server_type)
        
        if server_type == MCPServerType.STDIO:
            if not self.command:
                raise ValueError("stdio 类型服务器需要 'command' 字段")
        elif server_type in (MCPServerType.HTTP, MCPServerType.STREAMABLE_HTTP):
            if not self.url:
                raise ValueError("http/streamable-http 类型服务器需要 'url' 字段")
        return self

    def sanitized(self) -> Dict[str, Any]:
        """返回清理后的配置字典"""
        result: Dict[str, Any] = {
            "type": self.type if isinstance(self.type, str) else self.type.value,
            "description": self.description,
            "_enabled": bool(self.enabled),
        }
        
        if self.type == MCPServerType.STDIO or self.type == "stdio":
            result["command"] = self.command
            result["args"] = list(self.args)
            result["env"] = dict(self.env)
        elif self.type in (MCPServerType.HTTP, MCPServerType.STREAMABLE_HTTP) or self.type in ("http", "streamable-http"):
            result["url"] = self.url
            result["headers"] = dict(self.headers)
        
        if self.healthCheck:
            result["healthCheck"] = {
                "enabled": self.healthCheck.enabled,
                "interval": self.healthCheck.interval,
                "timeout": self.healthCheck.timeout,
            }
        
        return result
    
    def is_stdio(self) -> bool:
        """检查是否为 stdio 类型"""
        return self.type == MCPServerType.STDIO or self.type == "stdio"
    
    def is_http(self) -> bool:
        """检查是否为 HTTP 类型（包括 streamable-http）"""
        return self.type in (MCPServerType.HTTP, MCPServerType.STREAMABLE_HTTP) or self.type in ("http", "streamable-http")
    
    def is_streamable_http(self) -> bool:
        """检查是否为 streamable-http 类型"""
        return self.type == MCPServerType.STREAMABLE_HTTP or self.type == "streamable-http"


class MCPConfig(BaseModel):
    mcpServers: Dict[str, MCPServerConfig] = Field(default_factory=dict)

    model_config = {"extra": "ignore"}


def get_config_path(config_file: Optional[Path] = None) -> Path:
    path = Path(config_file) if config_file else DEFAULT_CONFIG_FILE
    return path


def validate_servers_map(
    servers: Dict[str, Any],
    *,
    strict: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """
    校验并清理 mcpServers 映射。
    strict=True 时遇到不合法配置立即抛出异常；否则跳过并记录警告。
    """
    validated: Dict[str, Dict[str, Any]] = {}
    for name, raw in servers.items():
        try:
            model = MCPServerConfig(**raw)
            validated[name] = model.sanitized()
        except Exception as exc:
            logger.warning("[MCP] 无效配置已跳过 (%s): %s", name, exc)
            if strict:
                raise
    return validated


def load_mcp_config(config_file: Optional[Path] = None, *, strict: bool = False) -> Dict[str, Any]:
    """
    读取配置文件并进行基本校验。返回 dict 结构，确保 mcpServers 字段存在。
    """
    path = get_config_path(config_file)
    if not path.exists():
        return {"mcpServers": {}}

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:  # pragma: no cover - 保护 IO/解析异常
        logger.error("[MCP] 读取配置失败: %s", exc)
        return {"mcpServers": {}}

    servers = data.get("mcpServers", {}) or {}
    validated = validate_servers_map(servers, strict=strict)
    return {"mcpServers": validated}


def merge_servers(
    current: Dict[str, Dict[str, Any]],
    incoming: Dict[str, Dict[str, Any]],
    *,
    strict: bool = True,
) -> Dict[str, Dict[str, Any]]:
    """
    合并新旧服务器配置，保留已有 _enabled 状态。
    """
    validated = validate_servers_map(incoming, strict=strict)
    merged = dict(current)
    for name, cfg in validated.items():
        cfg["_enabled"] = bool(current.get(name, {}).get("_enabled", cfg.get("_enabled", True)))
        merged[name] = cfg
    return merged


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def write_mcp_config(config: Dict[str, Any], config_file: Optional[Path] = None) -> None:
    """
    原子写入配置并可选文件锁，避免并发写导致文件损坏。
    """
    path = get_config_path(config_file)
    payload = {"mcpServers": config.get("mcpServers", {})}
    lock_ctx = (
        FileLock(str(path) + ".lock")
        if FileLock is not None
        else nullcontext()
    )
    with lock_ctx:
        _atomic_write_json(path, payload)
