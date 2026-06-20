import asyncio
import logging
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from app.routers.auth_db import get_current_user, require_admin
from app.engine.tools.mcp import LANGCHAIN_MCP_AVAILABLE, get_mcp_loader_factory
from app.engine.tools.mcp.config_utils import (
    MCPServerConfig,
    get_config_path,
    load_mcp_config,
    merge_servers,
    write_mcp_config,
)
from app.core.response import safe_error_message

router = APIRouter(prefix="/api/mcp", tags=["MCP"])
CONFIG_FILE = get_config_path()
logger = logging.getLogger("app.routers.mcp")

# 安全模型说明：
# MCP 服务器是管理员通过 /api/mcp/connectors/update 自配置的——
# 这是用户对自己服务器负责的场景，访问控制由 require_admin 守门即可。
# 命令执行由 langchain-mcp 的 stdio_client / streamablehttp_client 隔离，
# 不存在直接的 subprocess.Popen 路径。配置类型/字段校验由 Pydantic schema 完成。


class UpdatePayload(BaseModel):
    mcpServers: Dict[str, MCPServerConfig] = Field(default_factory=dict)


# -----------------------------------------------------------------------------
# 基础端点
# -----------------------------------------------------------------------------

@router.get("/connectors")
async def list_connectors(user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """
    列出所有 MCP 连接器，包含健康状态和服务器类型信息

    注意：MCP 连接在应用启动时已建立，此处直接读取状态
    """
    full_config = load_mcp_config(CONFIG_FILE)
    servers_config = full_config.get("mcpServers", {})

    # 获取服务器健康状态
    server_status_map: Dict[str, str] = {}
    health_info_map: Dict[str, Any] = {}

    if LANGCHAIN_MCP_AVAILABLE and servers_config:
        try:
            factory = get_mcp_loader_factory()
            # 不再检查 _initialized，因为连接在应用启动时已建立
            all_status = factory.get_all_server_status()
            server_status_map = {name: info.get("status", "unknown") for name, info in all_status.items()}

            # 获取健康检查信息
            for name in servers_config.keys():
                try:
                    health_data = factory._health_monitor.get_server_health_info(name)
                    if health_data:
                        health_info_map[name] = health_data.to_dict()
                except Exception as e:
                    logger.debug(f"获取 MCP 健康信息失败: {name}: {e}")
        except Exception as exc:
            logger.warning("获取 MCP 健康状态失败: %s", exc)

    data = []
    for name, config in servers_config.items():
        # Check if enabled, default to True if not specified
        enabled = config.get("_enabled", True)
        server_type = config.get("type", "stdio")

        # Create a clean config copy for display
        display_config = config.copy()
        if "_enabled" in display_config:
            del display_config["_enabled"]

        # 确定状态
        if not enabled:
            status = "stopped"
        elif not LANGCHAIN_MCP_AVAILABLE:
            status = "unavailable"
        else:
            status = server_status_map.get(name, "unknown")

        data.append({
            "id": name,
            "name": name,
            "type": server_type,
            "config": display_config,
            "enabled": enabled,
            "status": status,
            "healthInfo": health_info_map.get(name),
        })

    return {"success": True, "data": data}


@router.post("/connectors/update")
async def update_connectors(
    payload: UpdatePayload,
    user: dict = Depends(require_admin)
) -> Dict[str, Any]:
    """
    更新 MCP 连接器配置

    访问控制由 require_admin 守门；命令执行通过 langchain-mcp 客户端隔离。
    用户（管理员）自行对自己配置的 MCP 服务器负责。
    配置更新后需要手动重载才能生效。
    """
    current_config = load_mcp_config(CONFIG_FILE)
    incoming = {name: cfg.sanitized() for name, cfg in payload.mcpServers.items()}
    merged = merge_servers(current_config.get("mcpServers", {}), incoming, strict=True)
    write_mcp_config({"mcpServers": merged}, CONFIG_FILE)
    return {
        "success": True,
        "message": "Configuration updated. Use /api/mcp/reload to apply changes."
    }


@router.patch("/connectors/{name}/toggle")
async def toggle_connector(
    name: str,
    body: Dict[str, bool] = Body(...),
    user: dict = Depends(require_admin)
) -> Dict[str, Any]:
    """
    切换 MCP 连接器的启用状态

    注意：此操作会实时更新配置并立即连接/断开服务器。
    """
    config = load_mcp_config(CONFIG_FILE)
    if "mcpServers" not in config or name not in config["mcpServers"]:
        raise HTTPException(status_code=404, detail="Server not found")

    enabled = body.get("enabled", True)

    try:
        # 更新配置文件
        config["mcpServers"][name]["_enabled"] = enabled
        write_mcp_config(config, CONFIG_FILE)

        # 通知加载器切换服务器状态（实时连接/断开）
        if LANGCHAIN_MCP_AVAILABLE:
            factory = get_mcp_loader_factory()
            await factory.toggle_server(name, enabled)

        # 获取实际状态
        actual_status = "stopped"
        if enabled and LANGCHAIN_MCP_AVAILABLE:
            factory = get_mcp_loader_factory()
            actual_status_obj = factory.get_server_status(name)
            actual_status = actual_status_obj.value if hasattr(actual_status_obj, 'value') else str(actual_status_obj)

        return {
            "success": True,
            "data": {
                "enabled": enabled,
                "status": actual_status,
                "message": f"服务器已{'启用并连接' if enabled else '禁用并断开'}"
            }
        }
    except Exception as e:
        logger.error(f"切换服务器 {name} 状态失败: {e}")
        raise HTTPException(status_code=500, detail=safe_error_message(e, "切换服务器状态失败"))


@router.delete("/connectors/{name}")
async def delete_connector(
    name: str,
    user: dict = Depends(require_admin)
) -> Dict[str, Any]:
    """
    删除 MCP 连接器配置

    注意：删除配置后需要手动重载才能生效
    """
    config = load_mcp_config(CONFIG_FILE)
    if "mcpServers" in config and name in config["mcpServers"]:
        del config["mcpServers"][name]
        write_mcp_config(config, CONFIG_FILE)

    return {
        "success": True,
        "message": "Configuration updated. Use /api/mcp/reload to apply changes."
    }


@router.get("/tools")
async def list_all_mcp_tools(user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """
    列出所有已启用 MCP 服务器的可用工具

    返回的工具列表包含：
    - 工具名称、描述和输入模式
    - 所属服务器名称和 ID
    - 服务器健康状态
    - 工具是否可用
    """
    if not LANGCHAIN_MCP_AVAILABLE:
        return {"success": False, "message": "langchain-mcp 未安装", "data": []}

    if not CONFIG_FILE.exists():
        return {"success": True, "message": "未找到 MCP 配置文件", "data": []}

    factory = get_mcp_loader_factory()

    # 不再检查 _initialized，因为连接在应用启动时已建立

    try:
        tools = await asyncio.to_thread(factory.list_available_tools)

        # 按服务器分组统计
        server_stats: Dict[str, Dict[str, Any]] = {}
        for tool in tools:
            server_name = tool.get("serverName", "unknown")
            if server_name not in server_stats:
                server_stats[server_name] = {
                    "total": 0,
                    "available": 0,
                    "status": tool.get("status", "unknown")
                }
            server_stats[server_name]["total"] += 1
            if tool.get("available", True):
                server_stats[server_name]["available"] += 1

        return {
            "success": True,
            "data": tools,
            "serverStats": server_stats,
        }
    except Exception as exc:
        logger.error(f"获取 MCP 工具列表失败: {exc}")
        return {"success": False, "message": str(exc), "data": []}
