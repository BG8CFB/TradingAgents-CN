"""
MCP 应用服务层（新 MCPManager 之上）— 供 routers/mcp、main 启动生命周期使用

- 配置源沿用 config/mcp.json（app.engine.tools.mcp.config_utils，前端管理界面读写）
- 连接执行走新层 MCPManager（官方 mcp SDK，按 cache_key 复用、断线懒重连）
- startup 预热连接；shutdown 统一关闭；工具/状态查询基于会话列举
"""

import threading
from typing import Any, Dict, List, Optional

from app.utils.logging_init import get_logger

from .client import MCPManager
from .config import MCPServerConfig as NewServerConfig
from .tools import mcp_tool_name

logger = logging = get_logger("app.llm.mcp.service")

_manager: Optional[MCPManager] = None
_lock = threading.Lock()
# server → 状态（connected / disconnected / stopped），由探活/发现流程更新
_server_status: Dict[str, str] = {}


def get_shared_manager() -> MCPManager:
    """进程级共享 MCPManager（懒创建）"""
    global _manager
    if _manager is None:
        with _lock:
            if _manager is None:
                _manager = MCPManager()
    return _manager


def _load_old_config() -> Dict[str, Any]:
    """读取 config/mcp.json（旧格式：mcpServers → pydantic MCPServerConfig）"""
    from app.engine.tools.mcp.config_utils import load_mcp_config

    return load_mcp_config()


def enabled_server_configs() -> Dict[str, NewServerConfig]:
    """旧配置 → 新层 server 配置（跳过禁用项），供 MCPManager 连接"""
    result: Dict[str, NewServerConfig] = {}
    for name, old in _load_old_config().get("mcpServers", {}).items():
        raw = old.model_dump() if hasattr(old, "model_dump") else dict(old)
        if not getattr(old, "enabled", raw.get("_enabled", raw.get("enabled", True))):
            _server_status.setdefault(name, "stopped")
            continue
        stype = raw.get("type") or ("http" if raw.get("url") else "stdio")
        cfg = NewServerConfig(
            name=name,
            type=stype,
            command=raw.get("command"),
            args=list(raw.get("args") or []),
            env={k: str(v) for k, v in (raw.get("env") or {}).items()},
            url=raw.get("url"),
            headers={k: str(v) for k, v in (raw.get("headers") or {}).items()},
        )
        if cfg.type == "stdio" and not cfg.command:
            continue
        if cfg.type == "http" and not cfg.url:
            continue
        result[name] = cfg
    return result


async def startup() -> int:
    """应用启动：预热连接。返回已连接 server 数。"""
    manager = get_shared_manager()
    connected = 0
    for name, cfg in enabled_server_configs().items():
        try:
            await manager.connect(cfg)
            _server_status[name] = "connected"
            connected += 1
        except Exception as e:  # noqa: BLE001 - 单 server 失败不阻断启动
            _server_status[name] = "disconnected"
            logger.warning(f"⚠️ [mcp.service] server '{name}' 连接失败: {e}")
    logger.info(f"🔧 [mcp.service] 启动预热完成: {connected} 个 server 连接")
    return connected


async def shutdown() -> None:
    """应用关闭：统一断开"""
    global _manager
    if _manager is not None:
        try:
            await _manager.close_all()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"⚠️ [mcp.service] 关闭失败: {e}")
        _manager = None
        _server_status.clear()


async def list_tools() -> List[Dict[str, Any]]:
    """列出所有启用 server 的工具（含服务器名与状态）"""
    manager = get_shared_manager()
    result: List[Dict[str, Any]] = []
    for name, cfg in enabled_server_configs().items():
        try:
            session = await manager.get_session(cfg)
            resp = await session.list_tools()
            _server_status[name] = "connected"
            for t in resp.tools:
                result.append(
                    {
                        "name": mcp_tool_name(name, t.name),
                        "originalName": t.name,
                        "description": t.description or "",
                        "serverName": name,
                        "available": True,
                        "status": "connected",
                        "inputSchema": getattr(t, "inputSchema", None),
                    }
                )
        except Exception as e:  # noqa: BLE001
            _server_status[name] = "disconnected"
            logger.warning(f"⚠️ [mcp.service] server '{name}' 工具列举失败: {e}")
    return result


def get_server_status(name: str) -> str:
    """返回 server 状态（connected / disconnected / stopped / unknown）"""
    return _server_status.get(name, "unknown")


async def ping_server(name: str) -> str:
    """主动探活一次并更新状态"""
    manager = get_shared_manager()
    cfg = enabled_server_configs().get(name)
    if cfg is None:
        return "stopped"
    try:
        await manager.get_session(cfg)
        _server_status[name] = "connected"
    except Exception:  # noqa: BLE001
        _server_status[name] = "disconnected"
    return _server_status[name]


def all_server_status() -> Dict[str, Dict[str, Any]]:
    """全部 server 状态摘要"""
    return {name: {"status": s} for name, s in _server_status.items()}
