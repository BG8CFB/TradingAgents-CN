import logging
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from app.llm.mcp import service as mcp_service
from app.routers.auth_db import get_current_user, require_admin
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
# 命令执行由官方 mcp SDK 的 stdio_client / streamablehttp_client 隔离，
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
    all_status = mcp_service.all_server_status()

    data = []
    for name, config in servers_config.items():
        raw = config.model_dump() if hasattr(config, "model_dump") else dict(config)
        enabled = bool(getattr(config, "enabled", raw.get("_enabled", True)))
        server_type = raw.get("type", "stdio")

        # 展示用配置副本（去掉内部启用标记）
        display_config = {k: v for k, v in raw.items() if k not in ("_enabled", "enabled")}

        if not enabled:
            status = "stopped"
        else:
            status = all_status.get(name, {}).get("status", "unknown")

        data.append({
            "id": name,
            "name": name,
            "type": server_type,
            "config": display_config,
            "enabled": enabled,
            "status": status,
        })

    return {"success": True, "data": data}


@router.post("/connectors/update")
async def update_connectors(
    payload: UpdatePayload,
    user: dict = Depends(require_admin)
) -> Dict[str, Any]:
    """
    更新 MCP 连接器配置

    访问控制由 require_admin 守门；命令执行通过官方 mcp SDK 客户端隔离。
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

        # 启用时立即探活建立连接；禁用时仅标记状态（会话懒加载不会再使用它）
        if enabled:
            actual_status = await mcp_service.ping_server(name)
        else:
            actual_status = "stopped"

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
    """
    if not CONFIG_FILE.exists():
        return {"success": True, "message": "未找到 MCP 配置文件", "data": []}

    try:
        tools = await mcp_service.list_tools()

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
        return {"success": False, "message": safe_error_message(exc, "获取 MCP 工具列表失败"), "data": []}
