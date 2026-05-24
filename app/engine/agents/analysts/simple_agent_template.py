"""
第一阶段智能体模板

核心工具调用循环委托给 AgentExecutor：
- bind_tools 只在循环外调用一次
- 集成 LoopDetector 的 6 维循环检测
- Token 预算控制 + 自动上下文压缩
- 内置工具预注入（基于 BuiltinToolSpec）+ 不可用工具通知
"""

import json
from datetime import timedelta
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


def _resolve_inject_args(
    spec, context: Dict[str, str],
) -> Dict[str, Any]:
    """
    从 BuiltinToolSpec.inject_args 解析出实际调用参数。

    inject_args 值类型：
    - "ticker" / "trade_date" → context 查找
    - "trade_date_compact" → 去横线的日期
    - "start_date_30d" / "start_date_90d" → 自动计算
    - callable → 动态调用
    - 其他字面量 → 直接使用
    """
    from app.utils.time_utils import now_utc

    args = {}
    for arg_name, source in spec.inject_args.items():
        if callable(source):
            val = source(context)
            if val:
                args[arg_name] = val
        elif isinstance(source, str):
            if source.startswith("start_date_"):
                days = int(source.replace("start_date_", "").replace("d", ""))
                args[arg_name] = (now_utc() - timedelta(days=days)).strftime('%Y-%m-%d')
            elif source == "trade_date_compact":
                val = context.get("trade_date", "").replace("-", "")
                if val:
                    args[arg_name] = val
            elif source in ("ticker",):
                val = context.get("ticker", "")
                if val:
                    args[arg_name] = val
            elif source == "trade_date":
                val = context.get("trade_date", "")
                if val:
                    args[arg_name] = val
            elif source == "company_name":
                val = context.get("company_name", "")
                if val:
                    args[arg_name] = val
            else:
                args[arg_name] = source
        elif isinstance(source, int):
            args[arg_name] = source
    return args


def _inject_tool_data(
    agent_name: str,
    inject_tools: List[Any],
    unavailable_tool_ids: List[str],
    inject_context: Dict[str, str],
    messages: List,
) -> None:
    """
    自动调用内置工具获取数据，并将结果注入到消息上下文中。

    通过在 messages 列表中插入 AIMessage(tool_calls) + ToolMessage(content) 对，
    模拟工具已执行的结果，使 LLM 在第一轮就能看到预加载数据。

    不可用工具注入"未就绪"通知。
    """
    from app.engine.tools.builtin.registry import get_spec_by_id

    ticker = inject_context.get("ticker", "")
    trade_date = inject_context.get("trade_date", "")

    context_values = {
        "ticker": ticker,
        "trade_date": trade_date,
        "company_name": inject_context.get("company_name", ""),
    }

    injected_count = 0
    total_chars = 0

    # 收集可用工具的中文名
    injectable_names = []
    for tool in inject_tools:
        tool_name = getattr(tool, "name", None)
        if tool_name:
            spec = get_spec_by_id(tool_name)
            if spec:
                injectable_names.append(spec.display_name)

    # 收集不可用工具的中文名
    unavailable_names = []
    for tid in unavailable_tool_ids:
        spec = get_spec_by_id(tid)
        if spec:
            unavailable_names.append(spec.display_name)

    # ── 注入前导说明（合并可用和不可用状态） ──

    status_parts = []
    if injectable_names:
        status_parts.append(f"已就绪（{len(injectable_names)}个）：{', '.join(injectable_names)}")
    if unavailable_names:
        status_parts.append(
            f"未就绪（{len(unavailable_names)}个）：{', '.join(unavailable_names)}\n"
            "→ 这些数据当前不可用，禁止编造或推测其内容。"
            "若分析依赖这些数据，请在报告中标注「XX数据未就绪」。"
        )

    if status_parts:
        messages.append(SystemMessage(
            content=(
                f"【数据预加载状态】\n\n"
                + "\n\n".join(status_parts) + "\n\n"
                "已就绪的数据已在上下文中，直接使用即可，无需重新获取。"
            )
        ))

    # ── 注入可用工具数据 ──

    for tool in inject_tools:
        tool_name = getattr(tool, "name", None)
        if not tool_name:
            continue

        spec = get_spec_by_id(tool_name)
        if not spec:
            logger.debug(f"🔄 [{agent_name}] 跳过未注册的注入工具: {tool_name}")
            continue

        tool_args = _resolve_inject_args(spec, context_values)

        needs_ticker = any(
            isinstance(v, str) and v == "ticker"
            for v in spec.inject_args.values()
        )
        if needs_ticker and not ticker:
            logger.debug(f"🔄 [{agent_name}] 跳过 {tool_name}: 缺少 ticker")
            continue

        try:
            import uuid
            call_id = f"pre_{uuid.uuid4().hex[:8]}_{tool_name}"
            logger.info(f"💉 [{agent_name}] 预加载数据: {spec.display_name}({tool_args})")

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
            total_chars += len(result_str)
            logger.info(f"✅ [{agent_name}] 预加载成功: {spec.display_name} ({len(result_str)} 字符)")
        except Exception as e:
            logger.warning(f"⚠️ [{agent_name}] 预加载失败: {spec.display_name}, 错误: {e}")
            continue

    if injected_count > 0:
        logger.info(f"💉 [{agent_name}] 共预加载 {injected_count} 个工具数据, 总计 {total_chars} 字符")


def create_simple_agent(
    name: str,
    slug: str,
    llm: Any,
    tools: List[Any],
    system_prompt: str,
    max_tool_calls: int = 12,
    llm_provider: str = "default",
    inject_tools: Optional[List[Any]] = None,
    unavailable_tools: Optional[List[str]] = None,
):
    """
    创建简单智能体节点函数

    Args:
        name: 智能体名称
        slug: 智能体标识符
        llm: LLM 实例
        tools: 可调用工具列表（MCP/Skill）
        system_prompt: 系统提示词
        max_tool_calls: 最大工具调用次数
        llm_provider: LLM 提供商名称
        inject_tools: 需要预加载数据的内置工具列表
        unavailable_tools: 不可用工具的 tool_id 列表（注入"未就绪"通知）

    Returns:
        节点函数
    """

    def simple_agent_node(state: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"🤖 [{name}] 开始分析")

        from app.engine.agents.analysts.dynamic_analyst import ProgressManager, DynamicAnalystFactory

        icon = DynamicAnalystFactory._get_analyst_icon(
            slug, name, agent_config=DynamicAnalystFactory.get_agent_config(slug)
        )
        display_name = f"{icon} {name}"
        task_id = state.get("task_id")
        ProgressManager.node_start(display_name, task_id=task_id)

        try:
            # === 获取上下文信息 ===
            ticker = state.get("company_of_interest", "")
            trade_date = state.get("trade_date", "")

            from app.utils.stock_utils import StockUtils
            from app.utils.time_utils import now_utc
            market_info = StockUtils.get_market_info(ticker)

            company_name = ticker
            try:
                if market_info["is_china"]:
                    import asyncio
                    from app.data.core.interface import DataInterface
                    di = DataInterface.get_instance()
                    result = asyncio.run(di.read("CN", "basic_info", symbol=ticker))
                    data = result.get("data")
                    if data:
                        doc = data[0] if isinstance(data, list) and data else data
                        if doc.get("name"):
                            company_name = doc["name"]
                elif market_info["is_hk"]:
                    import asyncio
                    from app.data.core.interface import DataInterface
                    clean_ticker = ticker.replace(".HK", "").replace(".hk", "").zfill(5)
                    di = DataInterface.get_instance()
                    result = asyncio.run(di.read("HK", "basic_info", symbol=clean_ticker))
                    data = result.get("data")
                    if data:
                        doc = data[0] if isinstance(data, list) and data else data
                        n = doc.get("name_zh") or doc.get("name_en") or doc.get("name")
                        if n:
                            company_name = n
                    else:
                        company_name = f"港股{clean_ticker}"
                elif market_info["is_us"]:
                    company_name = _get_us_company_name(ticker)
            except Exception as e:
                logger.warning(f"⚠️ [{name}] 获取公司名称失败: {e}")

            # === 构建系统提示词 ===
            current_time = now_utc().strftime('%Y-%m-%d %H:%M:%S UTC')
            context_prefix = f"""
股票代码：{ticker}
公司名称：{company_name}
分析日期：{trade_date}
当前时间：{current_time}
"""
            full_system_prompt = context_prefix + "\n\n" + system_prompt

            # === 构建初始消息 ===
            messages = [SystemMessage(content=full_system_prompt)]
            task_message = f"请对股票 {company_name} ({ticker}) 进行全面分析，交易日期：{trade_date}"
            messages.append(HumanMessage(content=task_message))

            # 获取速率限制器
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
                unavailable_tools=unavailable_tools or [],
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

            internal_key = slug.replace("-analyst", "").replace("-", "_")
            report_key = f"{internal_key}_report"

            logger.info(f"✅ [{name}] 报告长度: {len(final_report)} 字符")

            ProgressManager.node_end(display_name, task_id=task_id)

            final_message = AIMessage(content=final_report) if final_report else None

            return {
                "messages": [final_message] if final_message else [],
                report_key: final_report,
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
                "reports": {
                    report_key: error_report,
                }
            }

    return simple_agent_node
