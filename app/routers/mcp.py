import logging
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from app.llm.mcp import service as mcp_service
from app.routers.auth_db import get_current_user, require_admin
from app.llm.mcp.management.config_store import (
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


class ImportPayload(BaseModel):
    raw: str = Field(..., min_length=2, max_length=200_000, description="待导入的配置 JSON 文本")


class RuntimeToolPayload(BaseModel):
    tool: str = Field(..., pattern="^(uv|node)$", description="要安装的运行时工具（uv 自动安装，node 仅引导）")


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
    return {"success": True, "message": "配置已更新，调用 /api/mcp/reload 立即生效"}


@router.post("/connectors/import")
async def import_connectors(
    payload: ImportPayload,
    user: dict = Depends(require_admin)
) -> Dict[str, Any]:
    """
    多格式配置导入（dry-run）：识别 claude-desktop / cline / kilo / 裸服务器对象格式，
    归一化为标准 MCPServerConfig 并回显丢弃字段与失败项。不落盘；
    前端确认后拿返回的 servers 调 /connectors/update 落盘。
    """
    from app.llm.mcp.management.import_normalizer import normalize_import_raw

    try:
        insight = normalize_import_raw(payload.raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"success": True, "data": insight.to_dict()}


@router.post("/reload")
async def reload_mcp(user: dict = Depends(require_admin)) -> Dict[str, Any]:
    """重载 MCP 连接：断开全部会话并按当前配置重建（保存/导入后调用）"""
    try:
        await mcp_service.shutdown()
        connected = await mcp_service.startup()
        return {"success": True, "data": {"connected": connected}, "message": "MCP 连接已重载"}
    except Exception as e:
        logger.error(f"重载 MCP 连接失败: {e}")
        raise HTTPException(status_code=500, detail=safe_error_message(e, "重载 MCP 连接失败"))


@router.post("/connectors/check-runtime")
async def check_connector_runtime(
    cfg: MCPServerConfig,
    user: dict = Depends(require_admin)
) -> Dict[str, Any]:
    """检测 stdio 服务器运行时可用性（未落盘即可测；command 可用性 + 安装引导）"""
    from app.llm.mcp.management.runtime import check_stdio_runtime

    if not cfg.is_stdio():
        return {"success": True, "data": {"command_available": True, "skipped_reason": "not_stdio"}}
    return {"success": True, "data": check_stdio_runtime(cfg).to_dict()}


@router.post("/connectors/{name}/test")
async def test_connector(
    name: str,
    user: dict = Depends(require_admin)
) -> Dict[str, Any]:
    """主动测试已配置服务器的连接（探活一次并返回状态）"""
    config = load_mcp_config(CONFIG_FILE)
    if name not in config.get("mcpServers", {}):
        raise HTTPException(status_code=404, detail="Server not found")
    status = await mcp_service.ping_server(name)
    return {"success": True, "data": {"name": name, "status": status}}


@router.post("/connectors/{name}/install-deps")
async def install_connector_deps(
    name: str,
    user: dict = Depends(require_admin)
) -> Dict[str, Any]:
    """安装 stdio 服务器声明的 deps 到容器 Python（审计写入 skill_install_logs, kind=mcp）"""
    from app.llm.mcp.management.runtime import install_server_deps

    config = load_mcp_config(CONFIG_FILE)
    raw = config.get("mcpServers", {}).get(name)
    if raw is None:
        raise HTTPException(status_code=404, detail="Server not found")
    try:
        model = MCPServerConfig(**raw) if not isinstance(raw, MCPServerConfig) else raw
        result = await install_server_deps(name, model, installed_by=f"user:{user.get('username', 'admin')}")
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"安装服务器 {name} 依赖失败: {e}")
        raise HTTPException(status_code=500, detail=safe_error_message(e, "安装依赖失败"))


@router.post("/runtime/install-tool")
async def install_runtime_tool(
    payload: RuntimeToolPayload,
    user: dict = Depends(require_admin)
) -> Dict[str, Any]:
    """一键安装缺失的运行时工具（当前支持 uv；node 仅返回引导链接）"""
    from app.llm.mcp.management.runtime import install_runtime_tool as do_install

    result = await do_install(payload.tool, installed_by=f"user:{user.get('username', 'admin')}")
    return {"success": bool(result.get("success")), "data": result}


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

    return {"success": True, "message": "配置已删除，调用 /api/mcp/reload 立即生效"}


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
