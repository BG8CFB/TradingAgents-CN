# pyright: reportMissingImports=false
"""
MCP 工具加载器 - 应用级基础设施版本

基于官方 langchain-mcp-adapters 实现，支持 stdio 和 SSE 两种传输模式。
参考文档: https://docs.langchain.com/oss/python/langchain/mcp

核心设计原则：
1. 应用级生命周期管理：在应用启动时建立连接，关闭时清理
2. 连接复用：所有任务共享同一个 MCP 连接池
3. 健康检查：基于 MCP 协议 ping 机制（send_ping），定期检查服务器状态
4. 配置手动重载：配置变更不自动触发重载，需手动调用
"""
import asyncio
import atexit
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, TYPE_CHECKING

from app.engine.tools.mcp.config_utils import (
    DEFAULT_CONFIG_FILE,
    MCPServerConfig,
    get_config_path,
    load_mcp_config,
    resolve_command,
)
from app.engine.tools.mcp.health_monitor import HealthMonitor, ServerStatus

logger = logging.getLogger(__name__)

# 检查 langchain-mcp-adapters 是否可用
try:
    from langchain_mcp_adapters.client import MultiServerMCPClient
    LANGCHAIN_MCP_AVAILABLE = True
except ImportError:
    MultiServerMCPClient = None  # type: ignore
    LANGCHAIN_MCP_AVAILABLE = False
    logger.warning("langchain-mcp-adapters 未安装，外部 MCP 服务器不可用")

# MCP Python SDK — 用于创建持久 ping 会话
try:
    from mcp.client.stdio import stdio_client as mcp_stdio_client, StdioServerParameters
    from mcp.client.session import ClientSession as MCPClientSession
    MCP_SDK_AVAILABLE = True
except ImportError:
    MCP_SDK_AVAILABLE = False
    logger.warning("mcp SDK 未安装，MCP ping 健康检查不可用")

# 检查 LangChain 工具是否可用
try:
    from langchain_core.tools import tool, StructuredTool, BaseTool
    LANGCHAIN_TOOLS_AVAILABLE = True
except ImportError:
    LANGCHAIN_TOOLS_AVAILABLE = False
    StructuredTool = None  # type: ignore
    BaseTool = None  # type: ignore
    tool = None  # type: ignore
    logger.warning("langchain-core 未安装，工具转换功能受限")

# 可选：用于识别并展开 RunnableBinding（langchain-mcp-adapters 输出常见类型）
try:
    from langchain_core.runnables import RunnableBinding
    LANGCHAIN_RUNNABLE_AVAILABLE = True
except ImportError:
    RunnableBinding = None  # type: ignore
    LANGCHAIN_RUNNABLE_AVAILABLE = False

if TYPE_CHECKING:
    pass


def load_local_mcp_tools(toolkit: Optional[Dict] = None) -> List[Any]:
    """
    加载内置金融工具（已迁移到 builtin 模块）。

    此函数保留旧签名以向后兼容，内部委托给 ToolRegistry。
    不再依赖旧的 app.engine.tools.mcp.tools.finance 模块。

    Args:
        toolkit: 工具配置字典

    Returns:
        LangChain 工具列表
    """
    try:
        from app.engine.tools.registry import get_all_tools
        return get_all_tools(toolkit=toolkit, enable_mcp=False)
    except Exception as e:
        logger.error(f"❌ [MCP Loader] 加载内置工具失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return []


def get_all_tools_mcp(toolkit: Optional[Dict] = None) -> List[Any]:
    """
    获取所有内置工具（向后兼容接口）。

    已弃用：新代码请直接使用 app.engine.tools.registry.get_all_tools()。
    """
    return load_local_mcp_tools(toolkit)


class MCPToolLoaderFactory:
    """
    MCP 工具加载工厂 - 应用级基础设施版本

    核心设计原则：
    1. 应用级生命周期管理：在应用启动时建立连接，关闭时清理
    2. 连接复用：所有任务共享同一个 MCP 连接池
    3. 健康检查：基于 MCP 协议 ping（send_ping），通过持久 ClientSession 检测

    支持两种传输模式：
    - stdio: 通过子进程通信的本地服务器
    - streamable_http: 通过 HTTP 协议通信的远程服务器
    """

    # 重启策略配置（用于手动重启）
    MAX_RESTART_ATTEMPTS = 3
    RESTART_WINDOW_SECONDS = 300  # 5分钟
    RESTART_DELAY_SECONDS = 2.0

    def __init__(self, config_file: str | Path | None = None):
        self.config_file = get_config_path(Path(config_file) if config_file else DEFAULT_CONFIG_FILE)

        # 官方 MultiServerMCPClient 实例集合
        self._mcp_clients: Dict[str, Any] = {}

        # 从 MCP 服务器加载的工具
        self._mcp_tools: List[Any] = []

        # 健康监控
        self._health_monitor = HealthMonitor()

        # 服务器配置缓存
        self._server_configs: Dict[str, MCPServerConfig] = {}

        # 是否已初始化
        self._initialized = False
        # 初始化锁，防止并发调用导致重复初始化
        self._lock = asyncio.Lock()

        # MCP 协议 ping 健康检查会话
        # {server_name: (exit_stack, session)}
        self._ping_sessions: Dict[str, tuple] = {}

        # 服务器重启计数：{server_name: count}
        self._restart_counts: Dict[str, int] = {}

        # 最后重启时间：{server_name: timestamp}
        self._last_restart_time: Dict[str, float] = {}

        # 清理函数是否已注册
        self._cleanup_registered = False

        # 健康检查任务
        self._health_check_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # 工具兼容处理
    # ------------------------------------------------------------------
    def _fix_tool_schema(self, tool: Any) -> Any:
        """
        通用的 MCP 工具参数信息补全

        解决 langchain-mcp-adapters 转换过程中可能丢失的参数信息。
        将所有参数定义（名称、类型、是否必需、描述、默认值、枚举）整合到工具描述中，
        确保 LLM 能够获得完整的工具信息。
        """
        getattr(tool, 'name', 'unknown')
        original_desc = getattr(tool, 'description', '')
        args_schema = getattr(tool, 'args_schema', None)

        # 没有参数的工具直接返回
        if not args_schema:
            return tool

        # 提取 schema 定义
        try:
            schema_dict = args_schema.schema()
        except Exception as e:
            logger.debug(f"提取工具 schema 失败: {e}")
            return tool

        required_params = set(schema_dict.get('required', []))
        properties = schema_dict.get('properties', {})

        # 没有参数定义直接返回
        if not properties:
            return tool

        # 生成参数说明
        param_lines = []
        for param_name, param_def in properties.items():
            param_type = param_def.get('type', 'unknown')
            param_desc = param_def.get('description', '')
            is_required = param_name in required_params
            default_val = param_def.get('default', None)
            enum_vals = param_def.get('enum', None)

            status_mark = "✅ REQUIRED" if is_required else "⚪ OPTIONAL"

            # 构建参数描述行
            line_parts = [f"  - `{param_name}` ({param_type}) [{status_mark}]"]

            if param_desc:
                line_parts.append(f": {param_desc}")

            # 补充额外信息（默认值、枚举）
            extras = []
            if default_val is not None:
                extras.append(f"Default: {default_val}")
            if enum_vals:
                extras.append(f"Enum: {enum_vals}")

            if extras:
                line_parts.append(f" ({', '.join(extras)})")

            param_lines.append("".join(line_parts))

        # 整合到工具描述
        enhanced_desc = f"""{original_desc}

--- Parameters ---
{chr(10).join(param_lines)}"""

        try:
            tool.description = enhanced_desc.strip()
        except Exception as e:
            logger.debug(f"设置工具描述失败: {e}")
            pass

    def _unwrap_runnable_binding(self, tool: Any) -> Any:
        """
        将 RunnableBinding 解包为原始工具，确保具备 __name__/name 属性。
        """
        if not LANGCHAIN_RUNNABLE_AVAILABLE or RunnableBinding is None:
            return tool

        if not isinstance(tool, RunnableBinding):
            return tool

        bound = getattr(tool, "bound", None)
        base = bound or tool

        name = getattr(base, "name", None) or getattr(base, "__name__", None) or base.__class__.__name__
        try:
            if not hasattr(base, "__name__"):
                base.__name__ = name  # type: ignore[attr-defined]
        except Exception as e:
            logger.debug(f"设置工具 __name__ 失败: {e}")
            pass
        try:
            tool_classes = tuple(
                cls for cls in (BaseTool, StructuredTool) if cls is not None  # type: ignore[arg-type]
            )
            if tool_classes and isinstance(base, tool_classes):
                tool_obj = base
        except Exception as e:
            logger.debug(f"工具类检查失败: {e}")

        # 附加 metadata
        metadata: Dict[str, Any] = {}
        for candidate in (getattr(tool, "metadata", None), getattr(base, "metadata", None)):
            if isinstance(candidate, dict):
                metadata.update(candidate)
        try:
            if metadata:
                existing = getattr(tool_obj, "metadata", {}) or {}
                if isinstance(existing, dict):
                    metadata = {**existing, **metadata}
                setattr(tool_obj, "metadata", metadata)
        except Exception as e:
            logger.debug(f"设置工具 metadata 失败: {e}")

    def _attach_server_metadata(self, tool: Any, server_name: str) -> Any:
        """为工具附加服务器元数据。"""
        tool = self._unwrap_runnable_binding(tool)

        if tool is None:
            return tool

        metadata = {}
        try:
            existing = getattr(tool, "metadata", {}) or {}
            if isinstance(existing, dict):
                metadata.update(existing)
        except Exception as e:
            logger.debug(f"读取工具现有元数据失败: {e}")
            pass

        try:
            if hasattr(tool, "with_config"):
                return tool.with_config({"metadata": metadata})
        except Exception as e:
            logger.debug(f"[MCP] with_config 附加元数据失败: {e}")

        try:
            setattr(tool, "metadata", metadata)
        except Exception as e:
            logger.debug(f"设置工具 metadata 属性失败: {e}")
            pass

        for attr in ("server_name", "_server_name"):
            try:
                setattr(tool, attr, server_name)
            except Exception as e:
                logger.debug(f"设置工具 {attr} 属性失败: {e}")
                continue

        return tool

    # ------------------------------------------------------------------
    # MCP 协议 Ping 会话管理
    # ------------------------------------------------------------------
    async def _create_ping_session(self, server_name: str, params: Dict[str, Any]) -> bool:
        """
        为指定服务器创建持久的 MCP ClientSession，用于 send_ping() 健康检查。

        使用 MCP Python SDK 直接创建会话，与 langchain-mcp-adapters 的
        工具加载客户端独立。stdio 模式下会保持子进程存活。
        """
        if not MCP_SDK_AVAILABLE:
            logger.debug(f"[MCP] MCP SDK 不可用，跳过 ping 会话创建: {server_name}")
            return False

        transport = params.get("transport", "")

        try:
            from contextlib import AsyncExitStack

            stack = AsyncExitStack()

            if transport == "stdio":
                server_params = StdioServerParameters(
                    command=params["command"],
                    args=params.get("args", []),
                    env=params.get("env"),
                )
                read_stream, write_stream = await stack.enter_async_context(
                    mcp_stdio_client(server_params)
                )
                session = await stack.enter_async_context(
                    MCPClientSession(read_stream, write_stream)
                )
                await session.initialize()
                self._ping_sessions[server_name] = (stack, session)
                logger.info(f"[MCP] ping 会话已建立: {server_name}")
                return True

            # HTTP 类型暂不支持持久 ping 会话，回退到客户端实例检查
            logger.debug(f"[MCP] 传输类型 {transport} 暂不支持 ping 会话: {server_name}")
            return False

        except Exception as e:
            logger.warning(f"[MCP] 创建 ping 会话失败: {server_name} - {e}")
            return False

    async def _close_ping_session(self, server_name: str) -> None:
        """关闭指定服务器的 ping 会话。"""
        if server_name not in self._ping_sessions:
            return

        stack, _ = self._ping_sessions.pop(server_name)
        try:
            await stack.aclose()
            logger.debug(f"[MCP] ping 会话已关闭: {server_name}")
        except Exception as e:
            logger.warning(f"[MCP] 关闭 ping 会话失败: {server_name} - {e}")

    async def _ping_server(self, server_name: str, timeout: float = 5.0) -> bool:
        """
        通过 MCP 协议 send_ping() 检查服务器是否存活。

        Returns:
            True = ping 成功，服务器健康
            False = ping 失败或无可用会话
        """
        if server_name not in self._ping_sessions:
            return False

        _, session = self._ping_sessions[server_name]
        try:
            await asyncio.wait_for(session.send_ping(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            logger.warning(f"[MCP] ping 超时 ({timeout}s): {server_name}")
            return False
        except Exception as e:
            logger.warning(f"[MCP] ping 失败: {server_name} - {e}")
            return False

    # ------------------------------------------------------------------
    # 重启管理
    # ------------------------------------------------------------------
    def _can_restart_server(self, server_name: str) -> bool:
        """检查服务器是否可以重启"""
        # 检查重启次数
        restart_count = self._restart_counts.get(server_name, 0)
        if restart_count >= self.MAX_RESTART_ATTEMPTS:
            # 检查是否在时间窗口内
            last_restart = self._last_restart_time.get(server_name, 0)
            if time.time() - last_restart < self.RESTART_WINDOW_SECONDS:
                logger.error(
                    f"[MCP] 服务器 {server_name} 在 {self.RESTART_WINDOW_SECONDS}s "
                    f"内已重启 {restart_count} 次，停止自动重启"
                )
                return False
            else:
                # 重置计数
                self._restart_counts[server_name] = 0

        return True

    def _record_restart(self, server_name: str) -> None:
        """记录重启事件"""
        self._restart_counts[server_name] = self._restart_counts.get(server_name, 0) + 1
        self._last_restart_time[server_name] = time.time()

    # ------------------------------------------------------------------
    # 服务器参数构建
    # ------------------------------------------------------------------
    def _build_server_params(self) -> Dict[str, Dict[str, Any]]:
        """构建符合官方 MultiServerMCPClient 格式的服务器参数。"""
        server_params = {}

        for name, config in self._server_configs.items():
            if not config.enabled:
                continue

            if config.is_stdio():
                resolved_cmd, cmd_error = resolve_command(config.command)
                if cmd_error:
                    logger.warning(f"[MCP] 服务器 {name} 命令解析失败: {cmd_error}")
                    self._health_monitor._update_status(
                        name, ServerStatus.UNREACHABLE, error=cmd_error
                    )
                    continue

                # 只传递白名单环境变量 + config.env 中指定的变量
                safe_env = {k: v for k, v in os.environ.items()
                            if k in ("PATH", "HOME", "USER", "LANG", "LC_ALL",
                                     "SYSTEMROOT", "TEMP", "TMP")}
                if config.env:
                    safe_env.update(config.env)

                server_params[name] = {
                    "command": resolved_cmd,
                    "args": config.args or [],
                    "env": safe_env if safe_env else None,
                    "transport": "stdio",
                }
            elif config.is_http():
                if config.is_streamable_http():
                    transport = "streamable_http"
                else:
                    transport = "sse"

                server_params[name] = {
                    "url": config.url,
                    "transport": transport,
                }
                if config.headers:
                    server_params[name]["headers"] = config.headers

        return server_params

    def _build_single_server_param(self, name: str) -> Optional[Dict[str, Any]]:
        """构建单个服务器的参数"""
        if name not in self._server_configs:
            return None

        config = self._server_configs[name]
        if not config.enabled:
            return None

        server_param = {}
        if config.is_stdio():
            resolved_cmd, cmd_error = resolve_command(config.command)
            if cmd_error:
                logger.warning(f"[MCP] 服务器 {name} 命令解析失败: {cmd_error}")
                return None

            # 只传递白名单环境变量 + config.env 中指定的变量
            safe_env = {k: v for k, v in os.environ.items()
                        if k in ("PATH", "HOME", "USER", "LANG", "LC_ALL",
                                 "SYSTEMROOT", "TEMP", "TMP")}
            if config.env:
                safe_env.update(config.env)

            server_param = {
                "command": resolved_cmd,
                "args": config.args or [],
                "env": safe_env if safe_env else None,
                "transport": "stdio",
            }
        elif config.is_http():
            if config.is_streamable_http():
                transport = "streamable_http"
            else:
                transport = "sse"

            server_param = {
                "url": config.url,
                "transport": transport,
            }
            if config.headers:
                server_param["headers"] = config.headers

        return server_param

    async def _connect_server(self, name: str) -> bool:
        """
        连接单个服务器

        优化逻辑：
        - 如果服务器已连接且健康，直接返回 True（避免重复创建进程）
        - 只在必要时才创建新的 MultiServerMCPClient 实例
        """
        if not LANGCHAIN_MCP_AVAILABLE:
            return False

        try:
            # 🔥 关键修复：先检查服务器是否已连接且健康
            if name in self._mcp_clients:
                # 检查连接是否健康
                is_healthy = await self._check_server_alive(name)
                if is_healthy:
                    logger.debug(f"[MCP] 服务器 {name} 已连接且健康，跳过重复连接")
                    return True
                else:
                    # 连接存在但不健康，需要重新连接
                    logger.info(f"[MCP] 服务器 {name} 连接不健康，将重新连接")
                    await self._disconnect_server(name)

            params = self._build_single_server_param(name)
            if not params:
                return False

            logger.info(f"[MCP] 正在连接服务器 {name}...")
            single_client = MultiServerMCPClient({name: params})

            self._mcp_clients[name] = single_client

            # 🔥 关键：只调用一次 get_tools()，因为每次调用都会创建新的 stdio 会话
            raw_tools = await single_client.get_tools()

            annotated_tools = [
                self._attach_server_metadata(tool, name)
                for tool in raw_tools
            ]

            # 移除旧的工具（如果存在）
            self._mcp_tools = [t for t in self._mcp_tools if getattr(t, 'server_name', getattr(t, 'metadata', {}).get('server_name')) != name]
            self._mcp_tools.extend(annotated_tools)

            logger.info(f"MCP服务器连接成功: {name} (工具: {len(annotated_tools)}个)")

            self._health_monitor._update_status(
                name,
                ServerStatus.HEALTHY,
                latency_ms=0
            )
            return True

        except Exception as e:
            logger.warning(f"MCP服务器连接失败: {name} - {e}")
            await self._disconnect_server(name)

            self._health_monitor._update_status(
                name,
                ServerStatus.UNREACHABLE,
                error=str(e)
            )
            return False

    async def _disconnect_server(self, name: str):
        """断开单个服务器连接"""
        # 清理工具列表
        self._mcp_tools = [t for t in self._mcp_tools if getattr(t, 'server_name', getattr(t, 'metadata', {}).get('server_name')) != name]

        if name in self._mcp_clients:
            client = self._mcp_clients[name]
            try:
                if hasattr(client, "aclose"):
                    await client.aclose()
                elif hasattr(client, "close"):
                    c = client.close()
                    if asyncio.iscoroutine(c):
                        await c
            except Exception as e:
                # 处理可能的 TaskGroup 错误或其他异常
                error_msg = str(e)
                if "TaskGroup" in error_msg or "ExceptionGroup" in type(e).__name__:
                    logger.warning(f"[MCP] 关闭服务器 {name} 时捕获 TaskGroup 错误 (已忽略): {e}")
                else:
                    logger.warning(f"[MCP] 关闭服务器 {name} 连接失败: {e}")
            finally:
                if name in self._mcp_clients:
                    del self._mcp_clients[name]

    # ------------------------------------------------------------------
    # 连接初始化
    # ------------------------------------------------------------------
    async def initialize_connections(self) -> None:
        """
        初始化所有 MCP 服务器连接

        此方法在应用启动时调用一次，建立所有已配置的 MCP 连接。
        整个应用生命周期内保持连接活跃。
        """
        # 快速检查，避免不必要的锁等待
        if self._initialized:
            logger.info("[MCP] 连接已初始化，跳过重复初始化")
            return

        async with self._lock:
            # 双重检查
            if self._initialized:
                return

            # 注册 atexit 清理
            self._register_cleanup()

            if not self.config_file.exists():
                logger.info(f"[MCP] 配置文件不存在: {self.config_file}")
                self._initialized = True
                return

            # 加载配置
            config = load_mcp_config(self.config_file)
            servers = config.get("mcpServers", {})

            # 解析服务器配置
            for server_name, server_config_dict in servers.items():
                try:
                    server_config = MCPServerConfig(**server_config_dict)
                    self._server_configs[server_name] = server_config

                    if not server_config.enabled:
                        self._health_monitor.mark_server_stopped(server_name)
                    else:
                        # 健康状态由 health_check_all() 通过 send_ping() 更新
                        self._health_monitor.register_server(
                            server_name,
                            lambda: True,
                            initial_status=ServerStatus.UNKNOWN
                        )

                except Exception as e:
                    logger.error(f"[MCP] 解析服务器配置 {server_name} 失败: {e}")

            # 初始化连接
            if LANGCHAIN_MCP_AVAILABLE and self._server_configs:
                server_params = self._build_server_params()

                if server_params:
                    for name, params in server_params.items():
                        await self._initialize_single_server(name, params)

                    logger.info(f"[MCP] 工具加载完成: {len(self._mcp_tools)} 个")

            self._initialized = True
            logger.info(f"[MCP] 连接初始化完成，已加载 {len(self._mcp_clients)} 个服务器")

    async def _initialize_single_server(self, name: str, params: Dict[str, Any]) -> bool:
        """
        初始化单个服务器连接

        Returns:
            是否成功初始化
        """
        try:
            # 🔥 防止重复初始化：检查是否已存在客户端
            if name in self._mcp_clients:
                logger.debug(f"[MCP] 服务器 {name} 的客户端已存在，跳过初始化")
                return True

            logger.info(f"[MCP] 正在连接服务器 {name}...")

            # 创建 MultiServerMCPClient
            # 注意：每次创建 MultiServerMCPClient 都会启动新的 npx 子进程
            single_client = MultiServerMCPClient({name: params})
            self._mcp_clients[name] = single_client

            # 🔥 关键：get_tools() 会创建新的 stdio 会话，导致启动 npx 进程
            # 进度条（如 0/15 → 100%）就是在这里产生的
            logger.debug(f"[MCP] 正在获取服务器 {name} 的工具列表...")
            raw_tools = await single_client.get_tools()

            # 🔥 修复工具 schema（解决 langchain-mcp-adapters 参数丢失问题）
            fixed_tools = [self._fix_tool_schema(tool) for tool in raw_tools]

            # 为每个工具附加服务器元数据
            annotated_tools = [
                self._attach_server_metadata(tool, name)
                for tool in fixed_tools
            ]

            self._mcp_tools.extend(annotated_tools)

            # 创建持久 ping 会话用于健康检查
            await self._create_ping_session(name, params)

            # 更新健康状态
            self._health_monitor._update_status(
                name,
                ServerStatus.HEALTHY,
                latency_ms=0
            )

            # 重置重启计数
            self._restart_counts[name] = 0

            logger.info(f"[MCP] 服务器连接成功: {name} (工具: {len(annotated_tools)} 个)")
            return True

        except Exception as e:
            logger.warning(f"[MCP] 服务器连接失败: {name} - {e}")

            # 清理失败的连接
            if name in self._mcp_clients:
                del self._mcp_clients[name]

            # 清理可能残留的 ping 会话
            await self._close_ping_session(name)

            self._health_monitor._update_status(
                name,
                ServerStatus.UNREACHABLE,
                error=str(e)
            )
            return False

    # ------------------------------------------------------------------
    # 服务器管理方法
    # ------------------------------------------------------------------
    async def refresh_server(self, server_name: str) -> bool:
        """
        刷新指定服务器（重新连接）

        Args:
            server_name: 服务器名称

        Returns:
            是否成功刷新

        警告：此操作会终止现有 npx 进程并启动新的进程，可能需要重新下载 npm 包
        """
        if server_name not in self._server_configs:
            logger.warning(f"[MCP] 服务器 {server_name} 不存在")
            return False

        # 🔥 警告日志：此操作会启动新的 npx 进程
        logger.warning(f"[MCP] 正在刷新服务器 {server_name}，这将启动新的 npx 进程")

        # 关闭旧连接（不删除配置）
        await self._cleanup_server_resources(server_name)

        # 重新初始化
        server_params = self._build_server_params()
        if server_name in server_params:
            return await self._initialize_single_server(server_name, server_params[server_name])

        return False

    async def add_server(self, server_name: str, config: MCPServerConfig) -> bool:
        """
        新增服务器

        Args:
            server_name: 服务器名称
            config: 服务器配置

        Returns:
            是否成功添加
        """
        if server_name in self._server_configs:
            logger.warning(f"[MCP] 服务器 {server_name} 已存在")
            return False

        self._server_configs[server_name] = config

        if config.enabled:
            server_params = self._build_server_params()
            if server_name in server_params:
                return await self._initialize_single_server(server_name, server_params[server_name])

        return True

    async def remove_server(self, server_name: str) -> bool:
        """
        移除服务器

        Args:
            server_name: 服务器名称

        Returns:
            是否成功移除
        """
        return await self._remove_server(server_name)

    async def _cleanup_server_resources(self, server_name: str) -> None:
        """
        清理服务器资源（不删除配置）

        关闭客户端连接、终止子进程、移除工具
        """
        try:
            # 关闭客户端连接
            if server_name in self._mcp_clients:
                try:
                    client = self._mcp_clients[server_name]
                    if client is None:
                        logger.warning(f"[MCP] 服务器 {server_name} 的客户端为 None")
                    else:
                        if hasattr(client, "aclose"):
                            await client.aclose()
                        elif hasattr(client, "close"):
                            c = client.close()
                            if asyncio.iscoroutine(c):
                                await c
                except Exception as e:
                    logger.warning(f"[MCP] 关闭服务器 {server_name} 客户端失败: {e}")

                # 无论关闭成功与否，都从字典中移除
                if server_name in self._mcp_clients:
                    del self._mcp_clients[server_name]

            # 关闭 ping 会话
            try:
                await self._close_ping_session(server_name)
            except Exception as e:
                logger.warning(f"[MCP] 关闭服务器 {server_name} ping 会话失败: {e}")

            # 移除工具
            try:
                self._mcp_tools = [
                    tool for tool in self._mcp_tools
                    if getattr(tool, "metadata", {}).get("server_name") != server_name
                ]
            except Exception as e:
                logger.warning(f"[MCP] 移除服务器 {server_name} 工具失败: {e}")

            logger.debug(f"[MCP] 服务器 {server_name} 资源已清理")

        except Exception as e:
            logger.warning(f"[MCP] 清理服务器 {server_name} 资源失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())

    async def _remove_server(self, server_name: str) -> bool:
        """内部方法：移除服务器并清理资源（包括配置）"""
        try:
            # 清理资源
            await self._cleanup_server_resources(server_name)

            # 移除配置
            if server_name in self._server_configs:
                del self._server_configs[server_name]

            logger.info(f"[MCP] 服务器 {server_name} 已移除")
            return True

        except Exception as e:
            logger.error(f"[MCP] 移除服务器 {server_name} 失败: {e}")
            return False

    async def restart_server(self, server_name: str) -> bool:
        """
        重启指定服务器

        Args:
            server_name: 服务器名称

        Returns:
            是否成功重启
        """
        if not self._can_restart_server(server_name):
            return False

        logger.info(f"[MCP] 正在重启服务器 {server_name}...")

        # 记录重启
        self._record_restart(server_name)

        # 刷新服务器
        success = await self.refresh_server(server_name)

        if success:
            logger.info(f"[MCP] 服务器 {server_name} 重启成功")
        else:
            logger.error(f"[MCP] 服务器 {server_name} 重启失败")

        return success

    # ------------------------------------------------------------------
    # 健康检查
    # ------------------------------------------------------------------
    async def health_check_all(self) -> Dict[str, ServerStatus]:
        """
        基于 MCP 协议 ping 对所有服务器执行健康检查。

        对每个已启用的服务器调用 send_ping()：
        - ping 成功 → HEALTHY
        - ping 失败或无会话 → 回退检查客户端实例 → UNREACHABLE

        Returns:
            {server_name: status} 字典
        """
        results = {}

        for server_name in list(self._server_configs.keys()):
            config = self._server_configs.get(server_name)

            if config is None:
                continue

            if not config.enabled:
                results[server_name] = ServerStatus.STOPPED
                continue

            is_alive = await self._check_server_alive(server_name)

            if is_alive:
                results[server_name] = ServerStatus.HEALTHY
                self._health_monitor._update_status(
                    server_name,
                    ServerStatus.HEALTHY,
                    latency_ms=0
                )
            else:
                results[server_name] = ServerStatus.UNREACHABLE
                self._health_monitor._update_status(
                    server_name,
                    ServerStatus.UNREACHABLE,
                    error="ping 失败，服务器不可达"
                )

        return results

    async def _check_server_alive(self, server_name: str) -> bool:
        """
        检查服务器是否存活（基于 MCP 协议 ping）。

        检查优先级：
        1. send_ping() — 如果存在持久 ping 会话，直接 ping 验证
        2. 回退检查 — 客户端实例是否存在（适用于 HTTP 类型或 ping 会话未建立的场景）
        """
        if server_name not in self._server_configs:
            return False

        config = self._server_configs.get(server_name)
        if config is None:
            return False

        # 优先使用 MCP 协议 ping
        if server_name in self._ping_sessions:
            return await self._ping_server(server_name)

        # 回退：检查客户端实例是否存在
        return server_name in self._mcp_clients

    # ------------------------------------------------------------------
    # 工具加载
    # ------------------------------------------------------------------
    def create_loader(self, selected_tool_ids: List[str], include_local: bool = False) -> Callable[[], Iterable]:
        """返回同步 loader，兼容 registry 的调用方式。"""
        return lambda: self.load_tools(selected_tool_ids, include_local=include_local)

    async def get_tools(self, selected_tool_ids: List[str]) -> List[Any]:
        """异步获取 MCP 工具列表。"""
        # 不再检查 _initialized，因为连接在应用启动时已建立
        return self.load_tools(selected_tool_ids)

    def load_tools(self, selected_tool_ids: List[str], include_local: bool = True) -> List[Any]:
        """
        加载工具列表

        合并本地工具和从 MCP 服务器加载的工具

        注意：此方法只返回缓存的工具列表，不会创建新的 MCP 连接
        """
        # 本地工具
        local_tools = load_local_mcp_tools() if include_local else []

        # MCP 服务器工具（从缓存读取）
        raw_tools = local_tools + self._mcp_tools
        all_tools = [self._unwrap_runnable_binding(t) for t in raw_tools]

        # 🔥 调试日志：帮助追踪工具加载
        logger.debug(
            f"[MCP] load_tools: 本地工具={len(local_tools)}, "
            f"缓存MCP工具={len(self._mcp_tools)}, "
            f"筛选条件={selected_tool_ids or '无'}"
        )

        if not selected_tool_ids:
            return all_tools

        # 过滤选择的工具
        selected_tools = []
        for tool in all_tools:
            tool_name = getattr(tool, 'name', '')
            if tool_name in selected_tool_ids or f"local:{tool_name}" in selected_tool_ids:
                selected_tools.append(tool)

        if not selected_tools:
            logger.warning(f"[MCP] 工具选择无匹配: selected_tool_ids={selected_tool_ids}, 返回空列表")
        return selected_tools

    def list_available_tools(self) -> List[Dict[str, Any]]:
        """列出所有可用工具的元数据。"""
        result = []
        seen_ids = set()
        

        # 本地工具
        local_tools = load_local_mcp_tools()
        for tool in local_tools:
            tool_name = getattr(tool, 'name', 'unknown')
            tool_desc = getattr(tool, 'description', '')
            
            tool_id = f"local:{tool_name}"
            if tool_id in seen_ids:
                continue
            seen_ids.add(tool_id)
            

            result.append({
                "id": tool_id,
                "name": tool_name,
                "description": tool_desc,
                "serverName": "local",
                "serverId": "local",
                "status": "healthy",
                "available": True,
            })

        # MCP 服务器工具
        for tool in self._mcp_tools:
            tool_name = getattr(tool, 'name', 'unknown')
            tool_desc = getattr(tool, 'description', '')

            server_name = (
                getattr(tool, 'server_name', None) or
                getattr(tool, 'server', None) or
                getattr(tool, '_server_name', None) or
                "mcp"
            )

            metadata = getattr(tool, 'metadata', {}) or {}
            if isinstance(metadata, dict):
                server_name = metadata.get('server_name', server_name)
            
            tool_id = f"{server_name}:{tool_name}"
            if tool_id in seen_ids:
                continue
            seen_ids.add(tool_id)
            

            result.append({
                "id": tool_id,
                "name": tool_name,
                "description": tool_desc,
                "serverName": server_name,
                "serverId": server_name,
                "status": "healthy",
                "available": True,
            })

        logger.info(f"[MCP] list_available_tools: 本地工具 {len(local_tools)} 个, 外部 MCP 工具 {len(self._mcp_tools)} 个 (去重后)")

        return result

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    def get_server_status(self, name: str) -> ServerStatus:
        """获取服务器状态。"""
        return self._health_monitor.get_server_status(name)

    def get_all_server_status(self) -> Dict[str, Dict[str, Any]]:
        """获取所有服务器状态。"""
        return self._health_monitor.get_all_server_status()

    async def toggle_server(self, server_name: str, enabled: bool) -> bool:
        """
        切换服务器启用状态，并实时更新连接。

        使用锁保护配置读写，避免与 reload_config 等操作产生竞态条件。
        """
        # 锁保护：只保护配置读写，不阻塞耗时操作
        async with self._lock:
            if server_name not in self._server_configs:
                logger.warning(f"[MCP] 服务器 {server_name} 不存在")
                return False

            self._server_configs[server_name].enabled = enabled

            if enabled:
                self._health_monitor.register_server(
                    server_name,
                    lambda: True,
                    initial_status=ServerStatus.UNKNOWN
                )
            else:
                self._health_monitor.mark_server_stopped(server_name)

        # 连接操作在锁外执行，避免阻塞其他服务器的操作
        try:
            if enabled:
                await self._connect_server(server_name)
            else:
                await self._disconnect_server(server_name)
            return True
        except Exception as e:
            logger.error(f"[MCP] 服务器 {server_name} 连接操作失败: {e}")
            return False

    async def reload_config(self) -> None:
        """
        手动重新加载配置并重新初始化连接

        注意：此操作会关闭所有现有连接并重新建立
        """
        logger.warning("[MCP] 正在重载配置，这将重启所有 MCP 服务器")
        async with self._lock:
            for name, client in self._mcp_clients.items():
                try:
                    if hasattr(client, "aclose"):
                        await client.aclose()
                    elif hasattr(client, "close"):
                        c = client.close()
                        if asyncio.iscoroutine(c):
                            await c
                except Exception as e:
                    logger.warning(f"[MCP] 重载时关闭服务器 {name} 失败: {e}")

            # 关闭所有 ping 会话
            for server_name in list(self._ping_sessions.keys()):
                await self._close_ping_session(server_name)

            self._mcp_clients.clear()
            self._mcp_tools.clear()
            self._server_configs.clear()
            self._restart_counts.clear()
            self._last_restart_time.clear()

            self._initialized = False

        await self.initialize_connections()
        logger.info("[MCP] 配置重载完成")

    # ------------------------------------------------------------------
    # 资源清理
    # ------------------------------------------------------------------
    def _register_cleanup(self) -> None:
        """注册 atexit 清理函数。

        原实现用 asyncio.get_event_loop()（Python 3.12+ 已弃用）+ is_running()
        检查存在反逻辑 bug：在主线程退出阶段通常没有 running loop，但原代码会
        在 is_running() 为 True 时新建 loop（这条件永远不会触发）。直接用
        ``asyncio.run()`` 创建一次性 loop 是 atexit 场景下的标准模式。
        """
        if self._cleanup_registered:
            return

        def _cleanup_mcp_resources():
            """进程退出时清理 MCP 子进程"""
            try:
                loader = get_mcp_loader_factory()
                if loader:
                    # atexit 阶段没有 running loop；asyncio.run 创建临时 loop
                    # 执行 close() 后自动关闭，符合 Python 3.9+ 推荐模式
                    asyncio.run(loader.close())
                logger.info("[MCP] atexit 清理完成")
            except Exception as e:
                logger.warning(f"[MCP] atexit 清理失败: {e}")

        atexit.register(_cleanup_mcp_resources)
        self._cleanup_registered = True
        logger.info("[MCP] 已注册 atexit 清理函数")

    async def close(self) -> None:
        """
        关闭所有 MCP 连接并清理资源

        清理步骤：
        1. 停止健康检查任务
        2. 关闭所有 ping 会话
        3. 关闭所有 MCP 客户端连接
        4. 清空工具和配置缓存
        """
        logger.info("[MCP] 开始清理资源...")

        # 停止健康检查任务（如果有）
        # atexit 场景下 asyncio.run() 会创建临时 loop，此时 _health_check_task 可能
        # 绑定到原主 loop，跨 loop cancel/await 会抛 RuntimeError，需防御
        if self._health_check_task and not self._health_check_task.done():
            try:
                self._health_check_task.cancel()
                try:
                    await self._health_check_task
                except asyncio.CancelledError:
                    pass
                except RuntimeError as re:
                    if "bound to a different loop" in str(re):
                        logger.warning(f"[MCP] 健康检查任务跨 loop，跳过 await: {re}")
                    else:
                        raise
            except Exception as e:
                logger.warning(f"[MCP] 健康检查任务清理失败: {e}")
            logger.info("[MCP] 健康检查任务已停止")

        # 关闭所有 ping 会话
        for server_name in list(self._ping_sessions.keys()):
            await self._close_ping_session(server_name)

        # 关闭所有客户端连接
        for name, client in list(self._mcp_clients.items()):
            try:
                if hasattr(client, "aclose"):
                    await client.aclose()
                elif hasattr(client, "close"):
                    c = client.close()
                    if asyncio.iscoroutine(c):
                        await c
            except Exception as e:
                logger.warning(f"[MCP] 关闭服务器 {name} 连接失败: {e}")

        # 清空缓存
        self._mcp_clients.clear()
        self._mcp_tools.clear()
        self._server_configs.clear()
        self._ping_sessions.clear()
        self._restart_counts.clear()
        self._last_restart_time.clear()
        self._initialized = False

        logger.info("[MCP] 已关闭所有连接并清理资源")

    # ------------------------------------------------------------------
    # 上下文管理器支持
    # ------------------------------------------------------------------
    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.initialize_connections()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.close()
        return False

    def __enter__(self):
        """同步上下文管理器已弃用。

        MCP 加载器在 FastAPI lifespan 中已通过 __aenter__/__aexit__ 完成异步初始化。
        保留同步版本会导致嵌套事件循环风险（asyncio.run inside running loop）。
        如需在同步上下文中使用，请改用 app.core.async_utils.run_async()。
        """
        raise NotImplementedError(
            "MCPToolLoaderFactory 同步上下文已弃用 — 请使用 'async with' 或 run_async()。"
            "初始化已在 FastAPI lifespan 中通过异步上下文完成。"
        )

    def __exit__(self, exc_type, exc_val, exc_tb):
        """同步上下文管理器已弃用 — 见 __enter__ 文档。"""
        raise NotImplementedError(
            "MCPToolLoaderFactory 同步上下文已弃用 — 请使用 'async with' 或 run_async()。"
        )

    def close_all(self):
        """同步关闭已弃用 — 请改用 await self.close() 或 run_async(self.close())。"""
        raise NotImplementedError(
            "MCPToolLoaderFactory.close_all() 已弃用 — 请使用 'await self.close()' 或 run_async()。"
        )


# 全局单例
_global_loader_factory: Optional[MCPToolLoaderFactory] = None


def get_mcp_loader_factory() -> MCPToolLoaderFactory:
    """获取 MCP 加载工厂全局单例"""
    global _global_loader_factory
    if _global_loader_factory is None:
        _global_loader_factory = MCPToolLoaderFactory()
    return _global_loader_factory
