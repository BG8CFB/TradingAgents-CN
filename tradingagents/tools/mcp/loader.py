# pyright: reportMissingImports=false
"""
MCP 工具加载器 - 应用级基础设施版本

基于官方 langchain-mcp-adapters 实现，支持 stdio 和 SSE 两种传输模式。
参考文档: https://docs.langchain.com/oss/python/langchain/mcp

核心设计原则：
1. 应用级生命周期管理：在应用启动时建立连接，关闭时清理
2. 连接复用：所有任务共享同一个 MCP 连接池
3. 子进程跟踪：使用 psutil 跟踪所有子进程，确保正确清理
4. 健康检查：定期检查服务器状态，自动重启失败的进程
5. 配置手动重载：配置变更不自动触发重载，需手动调用
"""
import asyncio
import atexit
import logging
import os
import signal
import time
from datetime import datetime
from tradingagents.utils.time_utils import now_utc, now_config_tz, format_date_short, format_date_compact, format_iso
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, TYPE_CHECKING

from tradingagents.tools.mcp.config_utils import (
    DEFAULT_CONFIG_FILE,
    MCPServerConfig,
    MCPServerType,
    get_config_path,
    load_mcp_config,
)
from tradingagents.tools.mcp.health_monitor import HealthMonitor, ServerStatus

logger = logging.getLogger(__name__)

# 检查 langchain-mcp-adapters 是否可用
try:
    from langchain_mcp_adapters.client import MultiServerMCPClient
    LANGCHAIN_MCP_AVAILABLE = True
except ImportError:
    MultiServerMCPClient = None  # type: ignore
    LANGCHAIN_MCP_AVAILABLE = False
    logger.warning("langchain-mcp-adapters 未安装，外部 MCP 服务器不可用")

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

# 检查 psutil 是否可用（用于子进程跟踪）
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logger.warning("psutil 未安装，子进程跟踪功能受限")

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
    从本地 MCP 服务器加载工具并转换为 LangChain 工具格式。

    这些是内置的本地工具，不依赖外部 MCP 服务器。

    Args:
        toolkit: 工具配置字典

    Returns:
        LangChain 工具列表
    """
    start_time = now_utc()
    logger.info("[MCP Loader] 开始加载本地 MCP 工具...")

    try:
        try:
            from tradingagents.tools.mcp.tools import finance
            HAS_FINANCE_TOOLS = True
        except Exception as e:
            logger.warning(f"⚠️ Finance tools module import failed: {e}")
            HAS_FINANCE_TOOLS = False
            finance = None

        # 设置工具配置
        config = toolkit or {}

        tools = []

        if LANGCHAIN_TOOLS_AVAILABLE:
            from langchain_core.tools import tool as lc_tool

            # Add Finance Tools (including merged Core tools)
            if HAS_FINANCE_TOOLS and finance:
                finance_funcs = [
                    # 核心统一工具 (已合并去重)
                    finance.get_stock_data,         # 统一行情
                    finance.get_stock_news,         # 统一新闻
                    finance.get_stock_fundamentals, # 统一基本面
                    finance.get_stock_sentiment,    # 统一情绪
                    finance.get_china_market_overview, # 市场概览

                    # Finance 特色工具
                    finance.get_stock_data_minutes,
                    finance.get_macro_econ,
                    finance.get_money_flow,
                    finance.get_margin_trade,
                    finance.get_fund_data,
                    finance.get_fund_manager_by_name,
                    finance.get_index_data,
                    finance.get_csi_index_constituents,
                    finance.get_convertible_bond,
                    finance.get_block_trade,
                    finance.get_dragon_tiger_inst,
                    finance.get_finance_news,
                    finance.get_hot_news_7x24,
                    finance.get_current_timestamp
                ]
                for func in finance_funcs:
                    try:
                        tools.append(lc_tool(func))
                    except Exception as e:
                        logger.error(f"Failed to create langchain tool for {func.__name__}: {e}")

        execution_time = (now_utc() - start_time).total_seconds()
        logger.info(f"✅ [MCP Loader] 加载完成，共 {len(tools)} 个本地工具，耗时 {execution_time:.2f}秒")

        return tools

    except Exception as e:
        logger.error(f"❌ [MCP Loader] 加载本地 MCP 工具失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return []


def get_all_tools_mcp(toolkit: Optional[Dict] = None) -> List[Any]:
    """获取所有 MCP 格式的工具（同步接口）。"""
    return load_local_mcp_tools(toolkit)


class MCPToolLoaderFactory:
    """
    MCP 工具加载工厂 - 应用级基础设施版本

    核心设计原则：
    1. 应用级生命周期管理：在应用启动时建立连接，关闭时清理
    2. 连接复用：所有任务共享同一个 MCP 连接池
    3. 子进程跟踪：使用 psutil 跟踪所有子进程
    4. 健康检查：定期检查服务器状态，自动重启失败的进程

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

        # 子进程跟踪：{server_name: [pid1, pid2, ...]}
        self._tracked_pids: Dict[str, List[int]] = {}

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
        将所有参数定义（名称、类型、是否必需、描述）整合到工具描述中，
        确保 LLM 能够获得完整的工具信息。
        """
        tool_name = getattr(tool, 'name', 'unknown')
        original_desc = getattr(tool, 'description', '')
        args_schema = getattr(tool, 'args_schema', None)

        # 没有参数的工具直接返回
        if not args_schema:
            return tool

        # 提取 schema 定义
        try:
            schema_dict = args_schema.schema()
        except Exception:
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

            required_mark = "✅ 必需" if is_required else "⚪ 可选"
            param_lines.append(f"  - `{param_name}` ({param_type}) [{required_mark}]: {param_desc}")

        # 整合到工具描述
        enhanced_desc = f"""{original_desc}

📋 参数说明:
{chr(10).join(param_lines)}"""

        try:
            tool.description = enhanced_desc.strip()
        except Exception:
            pass

        return tool

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
        except Exception:
            pass

        tool_obj = tool
        try:
            tool_classes = tuple(
                cls for cls in (BaseTool, StructuredTool) if cls is not None  # type: ignore[arg-type]
            )
            if tool_classes and isinstance(base, tool_classes):
                tool_obj = base
        except Exception:
            pass

        # 附加 metadata
        metadata: Dict[str, Any] = {}
        for candidate in (getattr(tool, "metadata", None), getattr(base, "metadata", None)):
            if isinstance(candidate, dict):
                metadata.update(candidate)
        if metadata:
            try:
                existing = getattr(tool_obj, "metadata", {}) or {}
                if isinstance(existing, dict):
                    metadata = {**existing, **metadata}
                setattr(tool_obj, "metadata", metadata)
            except Exception:
                pass

        try:
            if not getattr(tool_obj, "name", None):
                setattr(tool_obj, "name", name)
        except Exception:
            pass

        return tool_obj

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
        except Exception:
            pass

        metadata.setdefault("server_name", server_name)
        metadata.setdefault("server_id", server_name)

        try:
            if hasattr(tool, "with_config"):
                return tool.with_config({"metadata": metadata})
        except Exception as e:
            logger.debug(f"[MCP] with_config 附加元数据失败: {e}")

        try:
            setattr(tool, "metadata", metadata)
        except Exception:
            pass

        for attr in ("server_name", "_server_name"):
            try:
                setattr(tool, attr, server_name)
            except Exception:
                continue

        return tool

    # ------------------------------------------------------------------
    # 子进程跟踪（使用 psutil）
    # ------------------------------------------------------------------
    def _track_subprocess_for_server(self, server_name: str, command: str) -> None:
        """
        跟踪指定服务器的子进程

        通过查找匹配命令行参数的进程来跟踪 MultiServerMCPClient 创建的子进程。

        注意：
        - 子进程跟踪失败不影响服务器可用性
        - 对于需要下载包的 npx 命令，等待时间需要更长
        - 跟踪失败只会记录警告，不会导致服务器初始化失败
        """
        if not PSUTIL_AVAILABLE:
            logger.warning(f"[MCP] psutil 不可用，无法跟踪服务器 {server_name} 的子进程")
            return

        try:
            # 等待子进程启动
            # 对于需要下载包的 npx 命令，可能需要更长时间
            # 这里等待 8 秒，给子进程足够的启动时间
            wait_time = 8.0
            logger.debug(f"[MCP] 等待 {wait_time} 秒以跟踪服务器 {server_name} 的子进程...")
            time.sleep(wait_time)

            # 获取当前进程的所有子进程
            current_process = psutil.Process()
            children = current_process.children(recursive=True)

            # 构建匹配关键词：命令名和常见参数
            match_keywords = [command]
            # 添加命令的不带路径版本
            match_keywords.append(command.split("/")[-1])
            match_keywords.append(command.split("\\")[-1])
            # 对于 npx 命令，添加包名
            if "npx" in command.lower():
                parts = command.split()
                for part in parts:
                    if part.startswith("@") or "/" in part:
                        match_keywords.append(part)

            # 查找匹配的进程
            matched_pids = []
            for child in children:
                try:
                    cmdline_parts = child.cmdline()
                    if not cmdline_parts:
                        continue
                    cmdline_str = " ".join(cmdline_parts).lower()
                    command_lower = command.lower()

                    # 更灵活的匹配逻辑
                    is_match = (
                        command_lower in cmdline_str or
                        any(kw.lower() in cmdline_str for kw in match_keywords) or
                        any(kw.lower() in " ".join(cmdline_parts).lower()
                            for kw in match_keywords)
                    )

                    if is_match:
                        matched_pids.append(child.pid)
                        logger.debug(f"[MCP] 跟踪子进程: {server_name} -> PID {child.pid}, 命令: {cmdline_parts[:2]}")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            if matched_pids:
                self._tracked_pids[server_name] = matched_pids
                logger.info(f"[MCP] 已跟踪服务器 {server_name} 的 {len(matched_pids)} 个子进程")
            else:
                # 子进程跟踪失败只记录警告，不影响服务器可用性
                logger.warning(
                    f"[MCP] 未找到服务器 {server_name} 的子进程 "
                    f"(命令: {command})，但这不影响服务器功能"
                )

        except Exception as e:
            # 子进程跟踪失败只记录警告，不影响服务器可用性
            logger.warning(f"[MCP] 跟踪服务器 {server_name} 子进程失败: {e}，但这不影响服务器功能")

    def _terminate_server_subprocesses(self, server_name: str) -> None:
        """终止指定服务器的所有子进程"""
        if server_name not in self._tracked_pids:
            return

        pids = self._tracked_pids[server_name]
        if not pids:
            return

        logger.info(f"[MCP] 正在终止服务器 {server_name} 的 {len(pids)} 个子进程...")

        for pid in pids:
            try:
                if PSUTIL_AVAILABLE:
                    try:
                        process = psutil.Process(pid)
                        if process.is_running():
                            process.terminate()
                        logger.debug(f"[MCP] 已终止子进程: PID {pid}")
                    except psutil.NoSuchProcess:
                        logger.debug(f"[MCP] 子进程已不存在: PID {pid}")
                    except psutil.AccessDenied:
                        logger.warning(f"[MCP] 无权限终止子进程: PID {pid}")
                else:
                    # 降级方案：使用 os.kill
                    try:
                        os.kill(pid, signal.SIGTERM)
                        logger.debug(f"[MCP] 已终止子进程: PID {pid}")
                    except ProcessLookupError:
                        logger.debug(f"[MCP] 子进程已不存在: PID {pid}")
            except Exception as e:
                logger.warning(f"[MCP] 终止子进程失败 (PID {pid}): {e}")

        del self._tracked_pids[server_name]

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
                server_params[name] = {
                    "command": config.command,
                    "args": config.args or [],
                    "env": {**os.environ, **config.env} if config.env else None,
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
            server_param = {
                "command": config.command,
                "args": config.args or [],
                "env": {**os.environ, **config.env} if config.env else None,
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
        """连接单个服务器"""
        if not LANGCHAIN_MCP_AVAILABLE:
            return False

        try:
            # 防止重复连接
            if name in self._mcp_clients:
                await self._disconnect_server(name)

            params = self._build_single_server_param(name)
            if not params:
                return False

            logger.info(f"[MCP] 正在连接服务器 {name}...")
            single_client = MultiServerMCPClient({name: params})

            self._mcp_clients[name] = single_client

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
            logger.info(f"[MCP] 正在连接服务器 {name}...")

            # 创建 MultiServerMCPClient
            single_client = MultiServerMCPClient({name: params})
            self._mcp_clients[name] = single_client

            # 获取工具列表
            raw_tools = await single_client.get_tools()

            # 🔥 修复工具 schema（解决 langchain-mcp-adapters 参数丢失问题）
            fixed_tools = [self._fix_tool_schema(tool) for tool in raw_tools]

            # 为每个工具附加服务器元数据
            annotated_tools = [
                self._attach_server_metadata(tool, name)
                for tool in fixed_tools
            ]

            self._mcp_tools.extend(annotated_tools)

            # 跟踪子进程
            if params.get("transport") == "stdio" and params.get("command"):
                self._track_subprocess_for_server(name, params["command"])

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

            # 清理可能残留的子进程跟踪记录
            if name in self._tracked_pids:
                del self._tracked_pids[name]

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
        """
        if server_name not in self._server_configs:
            logger.warning(f"[MCP] 服务器 {server_name} 不存在")
            return False

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

            # 终止子进程
            try:
                self._terminate_server_subprocesses(server_name)
            except Exception as e:
                logger.warning(f"[MCP] 终止服务器 {server_name} 子进程失败: {e}")

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
        对所有服务器执行健康检查

        注意：此方法只检查和记录状态，不触发任何自动操作。
        重启应由外部手动触发或由独立的恢复任务处理。

        Returns:
            {server_name: status} 字典
        """
        results = {}

        for server_name in list(self._server_configs.keys()):
            config = self._server_configs.get(server_name)

            # 跳过配置无效的服务器
            if config is None:
                logger.warning(f"[MCP] 服务器 {server_name} 配置为 None，跳过健康检查")
                continue

            if not config.enabled:
                results[server_name] = ServerStatus.STOPPED
                continue

            # 检查进程是否存活
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
                    error="进程未运行"
                )

        return results

    async def _check_server_alive(self, server_name: str) -> bool:
        """
        检查服务器是否存活

        核心原则：只要客户端连接存在就认为存活，不管子进程状态。
        子进程跟踪失败不影响服务器可用性判断。

        Returns:
            是否存活
        """
        # 检查配置是否存在
        if server_name not in self._server_configs:
            return False

        config = self._server_configs.get(server_name)
        if config is None:
            return False

        # 对于非 stdio 类型，假设存活（远程服务器自行管理）
        if not config.is_stdio():
            return True

        # 对于 stdio 类型，核心判断：客户端连接是否存在
        if server_name in self._mcp_clients:
            # 客户端连接存在，认为服务器存活
            # 注意：子进程跟踪失败不影响此判断
            return True

        # 客户端连接不存在，说明服务器确实未运行
        # （不检查子进程，因为子进程跟踪可能失败）
        return False

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
        """
        # 本地工具
        local_tools = load_local_mcp_tools() if include_local else []

        # MCP 服务器工具
        raw_tools = local_tools + self._mcp_tools
        all_tools = [self._unwrap_runnable_binding(t) for t in raw_tools]

        if not selected_tool_ids:
            return all_tools

        # 过滤选择的工具
        selected_tools = []
        for tool in all_tools:
            tool_name = getattr(tool, 'name', '')
            if tool_name in selected_tool_ids or f"local:{tool_name}" in selected_tool_ids:
                selected_tools.append(tool)

        return selected_tools if selected_tools else all_tools

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
        """
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
            # 尝试连接
            await self._connect_server(server_name)
        else:
            self._health_monitor.mark_server_stopped(server_name)
            # 断开连接
            await self._disconnect_server(server_name)

        return True

    async def reload_config(self) -> None:
        """
        手动重新加载配置并重新初始化连接

        注意：此操作会关闭所有现有连接并重新建立
        """
        async with self._lock:
            # 关闭现有连接
            # 注意：这里不能直接调用 self.close()，因为它会销毁 exit_stack
            # 我们只需要重新初始化连接，不需要销毁整个 stack

            # 手动关闭现有客户端
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

            self._mcp_clients.clear()
            self._mcp_tools.clear()
            self._server_configs.clear()

            # 清理子进程跟踪信息
            for server_name in list(self._tracked_pids.keys()):
                self._terminate_server_subprocesses(server_name)
            self._tracked_pids.clear()
            self._restart_counts.clear()
            self._last_restart_time.clear()

            # 重置状态
            self._initialized = False

        # 重新初始化 (会获取锁)
        await self.initialize_connections()

        logger.info("[MCP] 配置重载完成")

    # ------------------------------------------------------------------
    # 资源清理
    # ------------------------------------------------------------------
    def _register_cleanup(self) -> None:
        """注册 atexit 清理函数"""
        if self._cleanup_registered:
            return

        def cleanup_subprocesses():
            """清理所有子进程"""
            logger.info("[MCP] atexit 清理子进程...")
            for server_name in list(self._tracked_pids.keys()):
                self._terminate_server_subprocesses(server_name)

        atexit.register(cleanup_subprocesses)
        self._cleanup_registered = True
        logger.info("[MCP] 已注册 atexit 清理函数")

    async def close(self) -> None:
        """
        关闭所有 MCP 连接并清理资源

        清理步骤：
        1. 停止健康检查任务
        2. 关闭所有 MCP 客户端连接
        3. 终止所有子进程
        4. 清空工具和配置缓存
        """
        logger.info("[MCP] 开始清理资源...")

        # 停止健康检查任务（如果有）
        if self._health_check_task and not self._health_check_task.done():
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            logger.info("[MCP] 健康检查任务已停止")

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

        # 终止所有子进程
        for server_name in list(self._tracked_pids.keys()):
            self._terminate_server_subprocesses(server_name)

        # 清空缓存
        self._mcp_clients.clear()
        self._mcp_tools.clear()
        self._server_configs.clear()
        self._tracked_pids.clear()
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
        """同步上下文管理器入口（用于兼容）"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                import threading
                result_future = concurrent.futures.Future()

                def run_init():
                    loop.call_soon_threadsafe(
                        lambda: asyncio.ensure_future(self.initialize_connections()).add_done_callback(
                            lambda f: result_future.set_result(f.result())
                        )
                    )
                    return result_future.result(timeout=30)

                thread = threading.Thread(target=run_init, daemon=True)
                thread.start()
                thread.join(timeout=30)
            else:
                asyncio.run(self.initialize_connections())
        except Exception as e:
            logger.warning(f"同步上下文管理器初始化失败: {e}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """同步上下文管理器出口"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.close())
            else:
                asyncio.run(self.close())
        except Exception as e:
            logger.warning(f"同步上下文管理器清理失败: {e}")
        return False

    def close_all(self):
        """同步关闭所有连接。"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.close())
            else:
                asyncio.run(self.close())
        except Exception as e:
            logger.warning(f"同步关闭失败: {e}")


# 全局单例
_global_loader_factory: Optional[MCPToolLoaderFactory] = None


def get_mcp_loader_factory() -> MCPToolLoaderFactory:
    """获取 MCP 加载工厂全局单例"""
    global _global_loader_factory
    if _global_loader_factory is None:
        _global_loader_factory = MCPToolLoaderFactory()
    return _global_loader_factory
