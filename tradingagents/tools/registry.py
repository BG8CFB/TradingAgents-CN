import asyncio
import concurrent.futures
import logging
import warnings
from typing import Callable, Iterable, List, Optional

from langchain_core.tools import StructuredTool

from tradingagents.tools.manager import (
    create_project_news_tools,
    create_project_market_tools,
    create_project_fundamentals_tools,
    create_project_sentiment_tools,
    create_project_china_market_tools
)

logger = logging.getLogger(__name__)

# MCP 工具加载标志
_USE_MCP_TOOLS = True  # 默认使用 MCP 工具


def _tool_names(tools: Iterable) -> set:
    return {
        getattr(t, "name", None)
        for t in tools
        if getattr(t, "name", None)
    }


def _run_coroutine_sync(coro):
    """
    在同步环境中安全运行协程，避免事件循环冲突。

    根据2024年最佳实践：
    1. 检测是否已有运行中的事件循环
    2. 如果没有，直接使用 asyncio.run()
    3. 如果有，使用独立线程运行协程，避免事件循环冲突
    
    🔥 修复 S2: 使用线程锁防止并发竞争
    """
    import threading
    
    # 线程锁，防止多个协程同时创建新事件循环
    _coroutine_lock = threading.Lock()
    
    try:
        loop = asyncio.get_running_loop()
        # 已经有运行中的事件循环，使用线程安全的方式
        result_container = []
        exception_container = []

        def run_in_new_loop():
            with _coroutine_lock:  # 🔥 加锁防止并发创建事件循环
                try:
                    # 创建新的事件循环（在新线程中）
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        result = new_loop.run_until_complete(coro)
                        result_container.append(result)
                    finally:
                        new_loop.close()
                        asyncio.set_event_loop(None)  # 🔥 清理线程本地事件循环
                except Exception as e:
                    exception_container.append(e)

        thread = threading.Thread(target=run_in_new_loop, daemon=True)
        thread.start()
        thread.join(timeout=120)  # 2分钟超时

        if exception_container:
            raise exception_container[0]
        if result_container:
            return result_container[0]
        raise TimeoutError("Async operation timed out after 120 seconds")

    except RuntimeError:
        # 没有运行中的事件循环，直接运行
        return asyncio.run(coro)


def _wrap_async_tool(tool):
    """
    将仅支持异步调用的 StructuredTool 包装为同步可用的工具，防止
    LangGraph 同步执行路径触发 NotImplementedError。
    """
    try:
        is_async_tool = bool(getattr(tool, "coroutine", False))
    except Exception:
        is_async_tool = False

    if not is_async_tool:
        return tool

    name = getattr(tool, "name", None) or getattr(tool, "__name__", "async_tool")
    description = getattr(tool, "description", "") or getattr(tool, "__doc__", "") or ""
    args_schema = getattr(tool, "args_schema", None)
    metadata = getattr(tool, "metadata", None)
    server_name = getattr(tool, "server_name", None) or getattr(tool, "_server_name", None)

    def _sync_wrapper(**kwargs):
        async def _call():
            if hasattr(tool, "ainvoke"):
                return await tool.ainvoke(kwargs)
            if hasattr(tool, "_arun"):
                return await tool._arun(**kwargs)
            if hasattr(tool, "arun"):
                return await tool.arun(**kwargs)
            raise NotImplementedError("Async tool missing ainvoke/_arun")

        return _run_coroutine_sync(_call())

    wrapped = StructuredTool.from_function(
        func=_sync_wrapper,
        name=name,
        description=description,
        args_schema=args_schema,
    )

    # 透传元数据，保持服务器标识等信息
    if metadata:
        try:
            wrapped.metadata = metadata
        except Exception:
            pass
    for attr in ("server_name", "_server_name"):
        if server_name:
            try:
                setattr(wrapped, attr, server_name)
            except Exception:
                continue

    return wrapped


def _load_mcp_tools(loader: Callable[[], Iterable] | None, existing_names: set | None = None) -> List:
    """
    预留的 MCP 工具加载入口；目前返回空列表或 loader 结果。
    """
    if not loader:
        return []
    try:
        tools = list(loader())
        if existing_names:
            filtered = []
            for t in tools:
                t_name = getattr(t, "name", None)
                if t_name and t_name in existing_names:
                    logger.warning(f"[工具注册] MCP 工具名称冲突，已跳过: {t_name}")
                    continue
                filtered.append(t)
            tools = filtered

        logger.info(f"[工具注册] MCP 工具加载成功: {len(tools)} 个")
        return tools
    except Exception as exc:
        logger.warning(f"[工具注册] MCP 工具加载失败: {exc}")
        return []


def get_news_toolset(
    toolkit,
    enable_mcp: bool = False,
    mcp_tool_loader: Callable[[], Iterable] | None = None,
) -> List:
    """统一新闻分析工具集装配。"""
    tools: List = []

    project_tools = create_project_news_tools(toolkit)
    logger.info(f"[工具注册] 项目新闻工具: {len(project_tools)} 个")
    tools.extend(project_tools)

    if enable_mcp:
        mcp_tools = _load_mcp_tools(mcp_tool_loader, existing_names=_tool_names(project_tools))
        logger.info(f"[工具注册] MCP 工具: {len(mcp_tools)} 个")
        tools.extend(mcp_tools)

    return tools

def get_market_toolset(
    toolkit,
    enable_mcp: bool = False,
    mcp_tool_loader: Callable[[], Iterable] | None = None,
) -> List:
    """统一市场数据工具集装配。"""
    tools: List = []

    project_tools = create_project_market_tools(toolkit)
    logger.info(f"[工具注册] 项目市场数据工具: {len(project_tools)} 个")
    tools.extend(project_tools)

    if enable_mcp:
        mcp_tools = _load_mcp_tools(mcp_tool_loader, existing_names=_tool_names(project_tools))
        tools.extend(mcp_tools)

    return tools

def get_fundamentals_toolset(
    toolkit,
    enable_mcp: bool = False,
    mcp_tool_loader: Callable[[], Iterable] | None = None,
) -> List:
    """统一基本面分析工具集装配。"""
    tools: List = []

    project_tools = create_project_fundamentals_tools(toolkit)
    logger.info(f"[工具注册] 项目基本面工具: {len(project_tools)} 个")
    tools.extend(project_tools)

    if enable_mcp:
        mcp_tools = _load_mcp_tools(mcp_tool_loader, existing_names=_tool_names(project_tools))
        tools.extend(mcp_tools)

    return tools

def get_sentiment_toolset(
    toolkit,
    enable_mcp: bool = False,
    mcp_tool_loader: Callable[[], Iterable] | None = None,
) -> List:
    """统一情绪分析工具集装配。"""
    tools: List = []

    project_tools = create_project_sentiment_tools(toolkit)
    logger.info(f"[工具注册] 项目情绪分析工具: {len(project_tools)} 个")
    tools.extend(project_tools)

    if enable_mcp:
        mcp_tools = _load_mcp_tools(mcp_tool_loader, existing_names=_tool_names(project_tools))
        tools.extend(mcp_tools)

    return tools

def get_china_market_toolset(
    toolkit,
    enable_mcp: bool = False,
    mcp_tool_loader: Callable[[], Iterable] | None = None,
) -> List:
    """中国市场特定工具集装配。"""
    tools: List = []

    project_tools = list(create_project_china_market_tools(toolkit))
    market_tools = list(create_project_market_tools(toolkit))

    # 基于 name 去重，避免重复注册同名工具
    existing_names = _tool_names(project_tools)
    for tool in market_tools:
        t_name = getattr(tool, "name", None)
        if t_name and t_name in existing_names:
            logger.info(f"[工具注册] 跳过重复的市场工具: {t_name}")
            continue
        project_tools.append(tool)
        if t_name:
            existing_names.add(t_name)

    logger.info(f"[工具注册] 项目中国市场工具: {len(project_tools)} 个 (已去重)")
    tools.extend(project_tools)

    if enable_mcp:
        mcp_tools = _load_mcp_tools(mcp_tool_loader, existing_names=_tool_names(project_tools))
        tools.extend(mcp_tools)

    return tools

def get_all_tools(
    toolkit,
    enable_mcp: bool = False,
    mcp_tool_loader: Callable[[], Iterable] | None = None,
    use_mcp_format: bool = True,
) -> List:
    """
    统一获取全量工具集，供所有分析师使用。
    
    Args:
        toolkit: 工具配置
        enable_mcp: 是否启用外部 MCP 工具
        mcp_tool_loader: 外部 MCP 工具加载器
        use_mcp_format: 是否使用 MCP 格式的本地工具（推荐）
    
    Returns:
        工具列表
    """
    all_tools: List = []
    tool_map = {}
    
    def _merge_tools(tools: List, source: str = "unknown"):
        """
        合并工具到 tool_map，处理重复工具
        
        🔥 修复 S6: 记录工具覆盖行为，而不是静默覆盖
        """
        for t in tools:
            t_name = getattr(t, "name", None)
            if t_name:
                if t_name in tool_map:
                    # 🔥 记录覆盖行为
                    old_source = getattr(tool_map[t_name], "_source", "unknown")
                    logger.warning(
                        f"[工具注册] 工具名称冲突: '{t_name}' "
                        f"(来源: {source}) 覆盖了 (来源: {old_source})"
                    )
                # 标记工具来源
                try:
                    t._source = source
                except AttributeError:
                    pass  # 某些工具对象不允许设置属性
                tool_map[t_name] = t
            else:
                all_tools.append(t)

    # 优先使用 MCP 格式的本地工具
    if use_mcp_format and _USE_MCP_TOOLS:
        try:
            from tradingagents.tools.mcp import load_local_mcp_tools
            
            # 转换 toolkit 为字典格式
            if isinstance(toolkit, dict):
                toolkit_config = toolkit
            elif hasattr(toolkit, 'config'):
                toolkit_config = toolkit.config
            else:
                toolkit_config = {}
            
            mcp_local_tools = load_local_mcp_tools(toolkit_config)
            _merge_tools(mcp_local_tools, source="mcp_local")
            logger.info(f"[工具注册] MCP 格式本地工具加载完成: {len(mcp_local_tools)} 个")
        except Exception as e:
            logger.warning(f"[工具注册] MCP 格式工具加载失败，回退到旧格式: {e}")
            use_mcp_format = False
    
    # 如果 MCP 格式不可用，使用旧格式
    if not use_mcp_format or not tool_map:
        warnings.warn(
            "使用旧格式工具，建议迁移到 MCP 格式。"
            "参考: tradingagents/tools/mcp/",
            DeprecationWarning,
            stacklevel=2
        )
        
        _merge_tools(create_project_news_tools(toolkit), source="news")
        _merge_tools(create_project_market_tools(toolkit), source="market")
        _merge_tools(create_project_fundamentals_tools(toolkit), source="fundamentals")
        _merge_tools(create_project_sentiment_tools(toolkit), source="sentiment")
        _merge_tools(create_project_china_market_tools(toolkit), source="china_market")
        
        logger.info(f"[工具注册] 旧格式项目工具加载完成: {len(tool_map)} 个 (已去重)")

    # 将 map 转回 list
    unique_project_tools = list(tool_map.values())
    all_tools.extend(unique_project_tools)
    
    # 加载外部 MCP 工具 (如果启用)
    if enable_mcp:
        mcp_tools = _load_mcp_tools(mcp_tool_loader, existing_names=set(tool_map.keys()))
        all_tools.extend(mcp_tools)
        logger.info(f"[工具注册] 外部 MCP 工具追加完成: {len(mcp_tools)} 个")

    # 确保所有工具在同步执行路径下可用，避免 async StructuredTool 抛出错误
    return [_wrap_async_tool(t) for t in all_tools]


def get_all_tools_mcp(toolkit_config: Optional[dict] = None) -> List:
    """
    获取所有 MCP 格式的工具（新接口）。
    
    这是推荐的工具获取方式，返回标准 MCP 格式的工具。
    
    Args:
        toolkit_config: 工具配置字典
    
    Returns:
        MCP 格式的工具列表
    """
    try:
        from tradingagents.tools.mcp import load_local_mcp_tools
        return load_local_mcp_tools(toolkit_config)
    except Exception as e:
        logger.error(f"[工具注册] MCP 工具加载失败: {e}")
        return []
