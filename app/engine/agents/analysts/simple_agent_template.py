"""
第一阶段智能体模板

重构版本：核心工具调用循环委托给 AgentExecutor，修复所有 P0-P2 问题：
- P0: bind_tools 只在循环外调用一次
- P0: 集成 LoopDetector 的 6 维循环检测
- P1: Token 预算控制 + 自动上下文压缩
- P1: 工具结果截断 + 结构化错误处理
- P1: 白名单无效时严格报错而非静默回退
- P2: 速率限制异常优雅降级
- P2: 预注入数据保留但优化
- P2: max_tool_calls 从 20 降到 12
"""

import json
from typing import Any, Optional
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from typing import Dict, List
from app.utils.logging_init import get_logger

logger = get_logger("simple_agent_template")


def format_tool_result(tool_result: Any) -> str:
    """将工具调用结果转换为字符串格式（向后兼容）"""
    if tool_result is None:
        return ""
    elif isinstance(tool_result, dict):
        return json.dumps(tool_result, ensure_ascii=False, indent=2)
    elif isinstance(tool_result, list):
        return json.dumps(tool_result, ensure_ascii=False, indent=2)
    else:
        return str(tool_result)


def _get_us_company_name(ticker: str) -> str:
    """动态获取美股公司名称，降级使用缓存"""
    try:
        import yfinance as yf
        if yf is not None:
            stock = yf.Ticker(ticker.upper())
            info = stock.info
            name = info.get("shortName") or info.get("longName")
            if name:
                return name
    except Exception:
        pass
    from app.utils.stock_utils import StockUtils
    return StockUtils.US_STOCK_NAMES.get(ticker.upper(), f"美股{ticker}")


# === 自动数据注入：工具参数映射 ===
# 格式: tool_name → {参数名: inject_context 字段名 或 Callable[[dict], str]}
# inject_context 提供: ticker, trade_date, company_name
# 值为字符串时从 context_values 查找；值为 callable 时动态计算


def _resolve_market_type(ctx: dict) -> str:
    """根据 ticker 动态推导 market_type"""
    from app.utils.stock_utils import StockUtils, StockMarket
    market = StockUtils.identify_stock_market(ctx.get("ticker", ""))
    if market == StockMarket.HONG_KONG:
        return "hk"
    elif market == StockMarket.US:
        return "us"
    return "cn"


_INJECT_TOOL_ARGS_MAP: Dict[str, Dict[str, Any]] = {
    "get_stock_data": {"stock_code": "ticker"},
    "get_stock_data_minutes": {"stock_code": "ticker", "market_type": _resolve_market_type},
    "get_index_data": {"stock_code": "ticker"},
    "get_stock_news": {"stock_code": "ticker"},
    "get_stock_fundamentals": {"stock_code": "ticker", "current_date": "trade_date"},
    "get_company_performance_unified": {"stock_code": "ticker"},
    "get_stock_sentiment": {"stock_code": "ticker", "current_date": "trade_date"},
    "get_dragon_tiger_inst": {"ts_code": "ticker", "trade_date": "trade_date_compact"},
    "get_block_trade": {"code": "ticker"},
    "get_money_flow": {"ts_code": "ticker", "query_type": "stock"},
    "get_margin_trade": {"data_type": "margin", "ts_code": "ticker"},
    "get_china_market_overview": {"date": "trade_date"},
    "get_finance_news": {"query": "company_name"},
    "get_hot_news_7x24": {},
    "get_current_timestamp": {},
}


def _inject_tool_data(
    agent_name: str,
    inject_tools: List[Any],
    inject_context: Dict[str, str],
    messages: List,
) -> None:
    """
    自动调用内置工具获取数据，并将结果注入到消息上下文中。

    通过在 messages 列表中插入 AIMessage(tool_calls) + ToolMessage(content) 对，
    模拟工具已执行的结果，使 LLM 在第一轮就能看到预加载数据。
    """
    ticker = inject_context.get("ticker", "")
    trade_date = inject_context.get("trade_date", "")
    trade_date_compact = trade_date.replace("-", "") if trade_date and "-" in trade_date else trade_date

    context_values = {
        "ticker": ticker,
        "trade_date": trade_date,
        "trade_date_compact": trade_date_compact,
        "company_name": inject_context.get("company_name", ""),
    }

    injected_count = 0
    for tool in inject_tools:
        tool_name = getattr(tool, "name", None)
        if not tool_name:
            continue

        args_map = _INJECT_TOOL_ARGS_MAP.get(tool_name)
        if args_map is None:
            logger.debug(f"🔄 [{agent_name}] 跳过未注册的注入工具: {tool_name}")
            continue

        tool_args = {}
        for arg_name, source in args_map.items():
            if isinstance(source, str) and not source:
                continue
            if callable(source):
                val = source(context_values)
                if val:
                    tool_args[arg_name] = val
            elif isinstance(source, str) and not source.startswith("ticker") and not source.startswith("trade_date") and source != "date":
                tool_args[arg_name] = source
            else:
                val = context_values.get(source, "")
                if val:
                    tool_args[arg_name] = val

        needs_ticker = any(
            v in ("ticker",)
            for v in args_map.values()
            if isinstance(v, str) and v.startswith("ticker")
        )
        if needs_ticker and not ticker:
            logger.debug(f"🔄 [{agent_name}] 跳过 {tool_name}: 缺少 ticker")
            continue

        try:
            import uuid
            call_id = f"pre_{uuid.uuid4().hex[:8]}_{tool_name}"
            logger.info(f"💉 [{agent_name}] 预加载数据: {tool_name}({tool_args})")

            result = tool.invoke(tool_args)
            result_str = format_tool_result(result)

            messages.append(AIMessage(
                content="",
                tool_calls=[{"name": tool_name, "args": tool_args, "id": call_id}]
            ))
            messages.append(ToolMessage(
                content=result_str,
                tool_call_id=call_id,
                name=tool_name,
            ))

            injected_count += 1
            logger.info(f"✅ [{agent_name}] 预加载成功: {tool_name} ({len(result_str)} 字符)")
        except Exception as e:
            logger.warning(f"⚠️ [{agent_name}] 预加载失败: {tool_name}, 错误: {e}")
            continue

    if injected_count > 0:
        logger.info(f"💉 [{agent_name}] 共预加载 {injected_count} 个工具数据到上下文")


def create_simple_agent(
    name: str,
    slug: str,
    llm: Any,
    tools: List[Any],
    system_prompt: str,
    max_tool_calls: int = 12,
    llm_provider: str = "default",
    inject_tools: Optional[List[Any]] = None,
):
    """
    创建简单智能体节点函数

    重构版本：核心循环委托给 AgentExecutor，修复所有已知问题。

    Args:
        name: 智能体名称
        slug: 智能体标识符
        llm: LLM 实例
        tools: 工具列表
        system_prompt: 系统提示词
        max_tool_calls: 最大工具调用次数（默认 12，从 20 降低）
        llm_provider: LLM 提供商名称（用于速率限制）
        inject_tools: 需要自动预加载数据的内置工具列表

    Returns:
        节点函数（可以直接添加到 LangGraph）
    """

    def simple_agent_node(state: Dict[str, Any]) -> Dict[str, Any]:
        """
        简单智能体节点函数

        流程：
        1. 获取上下文信息
        2. 构建系统提示词和消息列表
        3. 委托给 AgentExecutor 执行
        4. 返回更新后的 state
        """
        logger.info(f"🤖 [{name}] 开始分析")

        # === 进度追踪 ===
        from app.engine.agents.analysts.dynamic_analyst import ProgressManager, DynamicAnalystFactory

        icon = DynamicAnalystFactory._get_analyst_icon(
            slug, name, agent_config=DynamicAnalystFactory.get_agent_config(slug)
        )
        display_name = f"{icon} {name}"
        task_id = state.get("task_id")
        ProgressManager.node_start(display_name, task_id=task_id)

        try:
            # === 步骤1：获取上下文信息 ===
            ticker = state.get("company_of_interest", "")
            trade_date = state.get("trade_date", "")

            from app.utils.stock_utils import StockUtils
            market_info = StockUtils.get_market_info(ticker)

            company_name = ticker
            try:
                if market_info["is_china"]:
                    from app.data.reader import get_stock_info as _get_stock_info_cn
                    stock_info = _get_stock_info_cn("CN", ticker)
                    if "股票名称:" in stock_info:
                        company_name = stock_info.split("股票名称:")[1].split("\n")[0].strip()
                elif market_info["is_hk"]:
                    from app.data.providers.hk.improved_hk import get_hk_company_name_improved
                    company_name = get_hk_company_name_improved(ticker)
                elif market_info["is_us"]:
                    company_name = _get_us_company_name(ticker)
            except Exception as e:
                logger.warning(f"⚠️ [{name}] 获取公司名称失败: {e}")

            # === 步骤2：构建系统提示词 ===
            context_prefix = f"""
股票代码：{ticker}
公司名称：{company_name}
分析日期：{trade_date}
"""
            full_system_prompt = context_prefix + "\n\n" + system_prompt

            # === 步骤3：构建初始消息并委托给 AgentExecutor ===
            messages = [SystemMessage(content=full_system_prompt)]
            task_message = f"请对股票 {company_name} ({ticker}) 进行全面分析，交易日期：{trade_date}"
            messages.append(HumanMessage(content=task_message))

            # 获取速率限制器（可选）
            rate_limiter = None
            try:
                from app.utils.llm_rate_limiter import get_rate_limiter
                rate_limiter = get_rate_limiter()
            except Exception:
                pass

            from app.engine.agents.executors import AgentExecutor

            executor = AgentExecutor(
                llm=llm,
                tools=tools,
                max_iterations=max_tool_calls,
                system_prompt=full_system_prompt,
                rate_limiter=rate_limiter,
                llm_provider=llm_provider,
                inject_tools=inject_tools,
                inject_context={
                    "ticker": ticker,
                    "trade_date": trade_date,
                    "company_name": company_name,
                },
            )

            result = executor.execute(messages)

            final_report = result.final_report

            if result.loop_detected:
                logger.warning(
                    f"⚠️ [{name}] 检测到工具调用循环 ({result.loop_type}), "
                    f"在第 {result.iterations} 次迭代时强制停止"
                )
            elif result.forced_stop:
                logger.warning(
                    f"⚠️ [{name}] 达到最大迭代次数 ({result.iterations}), 强制总结"
                )
            else:
                logger.info(
                    f"✅ [{name}] 分析完成: {result.iterations} 迭代, "
                    f"{result.tool_calls_executed} 工具调用"
                )

            # === 步骤4：更新 state 并返回 ===
            internal_key = slug.replace("-analyst", "").replace("-", "_")
            report_key = f"{internal_key}_report"

            logger.info(f"✅ [{name}] 报告长度: {len(final_report)} 字符")

            ProgressManager.node_end(display_name, task_id=task_id)

            final_message = AIMessage(content=final_report) if final_report else None

            return {
                "messages": [final_message] if final_message else [],
                report_key: final_report,
                # 只返回当前报告，让 LangGraph reducer 负责合并，避免指数级膨胀
                "reports": {
                    report_key: final_report,
                }
            }
        except Exception as e:
            task_id = state.get("task_id")
            ProgressManager.node_end(display_name, task_id=task_id)
            logger.error(f"❌ [{name}] 分析过程中发生异常: {e}", exc_info=True)

            internal_key = slug.replace("-analyst", "").replace("-", "_")
            report_key = f"{internal_key}_report"
            error_report = f"❌ 分析失败：{str(e)}"

            return {
                report_key: error_report,
                "messages": [AIMessage(content=error_report)],
                # 只返回当前报告，让 LangGraph reducer 负责合并，避免指数级膨胀
                "reports": {
                    report_key: error_report,
                }
            }

    return simple_agent_node
