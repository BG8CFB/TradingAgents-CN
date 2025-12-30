import json
import os
import yaml
from datetime import datetime
from typing import List, Dict, Any, Optional

from langchain_core.messages import AIMessage, ToolMessage, BaseMessage, SystemMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import Runnable

from tradingagents.utils.logging_init import get_logger
from tradingagents.utils.stock_utils import StockUtils
from tradingagents.utils.time_utils import now_utc

logger = get_logger("agents.generic")

def load_agent_config(slug: str) -> str:
    """从YAML配置加载智能体角色定义"""
    try:
        # 优先读取 phase1_agents_config.yaml
        # 优先从环境变量读取配置目录
        env_dir = os.getenv("AGENT_CONFIG_DIR")
        agents_dirs = []

        if env_dir and os.path.exists(env_dir):
            agents_dirs.append(env_dir)
        else:
            current_dir = os.path.dirname(os.path.abspath(__file__))

            # 1. 优先检查项目根目录下的 config/agents
            # tradingagents/agents/utils -> tradingagents/agents -> tradingagents -> root
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
            config_agents_dir = os.path.join(project_root, "config", "agents")
            if os.path.exists(config_agents_dir):
                agents_dirs.append(config_agents_dir)

        # 定义可能的配置文件列表
        config_files = ["phase1_agents_config.yaml", "phase2_agents_config.yaml", "phase3_agents_config.yaml"]

        for agents_dir in agents_dirs:
            for config_file in config_files:
                yaml_path = os.path.join(agents_dir, config_file)
                if not os.path.exists(yaml_path):
                    continue

                with open(yaml_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)

                # 检查 customModes
                for agent in config.get('customModes', []):
                    if agent.get('slug') == slug:
                        return agent.get('roleDefinition', '')

                # 检查 agents (如果配置结构不同)
                for agent in config.get('agents', []):
                    if agent.get('slug') == slug:
                        return agent.get('roleDefinition', '')

        logger.warning(f"在配置中未找到智能体: {slug}")
        return ""
    except Exception as e:
        logger.error(f"加载配置文件失败: {e}")
        return ""

class GenericAgent:
    """
    通用智能体类，基于 LangChain 官方 ReAct Agent 架构。
    """
    def __init__(
        self,
        name: str,
        slug: str,
        llm: Any,
        tools: List[Any],
        system_message_template: str,
        use_tool_node: bool = False
    ):
        self.name = name
        self.slug = slug
        self.llm = llm
        self.tools = tools
        self.system_message_template = system_message_template

        # 初始化 Agent Executor
        self.agent_executor = None
        if tools:
            try:
                # 直接从 langgraph.prebuilt 导入，因为 GenericAgent 基于 LangGraph 构建
                from langgraph.prebuilt import create_react_agent

                # 🔥 修复：创建动态系统提示词函数
                # LangGraph 的 create_react_agent 会在每次调用时自动调用这个函数来生成系统提示词
                def create_dynamic_prompt(state):
                    """动态生成系统提示词"""
                    current_date = state.get("trade_date", "")
                    ticker = state.get("company_of_interest", "")

                    # 获取公司名称
                    try:
                        from tradingagents.utils.stock_utils import StockUtils
                        market_info = StockUtils.get_market_info(ticker)
                        company_name = self._get_company_name(ticker, market_info)
                    except Exception:
                        company_name = ticker

                    # 替换占位符
                    system_msg_content = self.system_message_template
                    system_msg_content = system_msg_content.replace("{current_date}", str(current_date))
                    system_msg_content = system_msg_content.replace("{ticker}", str(ticker))
                    system_msg_content = system_msg_content.replace("{company_name}", str(company_name))

                    # 补充上下文
                    context_info = (
                        f"\n\n当前上下文信息:\n"
                        f"当前日期: {current_date}\n"
                        f"股票代码: {ticker}\n"
                        f"公司名称: {company_name}\n"
                        f"请用中文回答。\n\n"
                        f"⚠️ 重要指令：\n"
                        f"1. 如果工具调用失败（返回错误信息），请在报告中如实记录失败原因，**严禁编造**虚假数据。\n"
                        f"2. 即使没有获取到完整数据，也请根据已知信息生成一份包含【错误说明】的报告。\n"
                        f"3. 你的报告将被用于最终汇总，请确保信息的真实性和准确性。\n"
                        f"4. **禁止死循环**：\n"
                        f"   - 每次调用工具前，请仔细检查上方对话历史。\n"
                        f"   - **严禁**使用完全相同的参数连续两次调用同一个工具。\n"
                        f"   - 如果连续 3 次尝试均未获得有效信息，请立即停止尝试。\n"
                        f"5. **最终输出**：必须包含具体的分析结论，不要只列出数据。"
                    )
                    system_msg_content += context_info

                    return system_msg_content

                # 使用官方 create_react_agent 创建标准执行器
                # 传递 prompt 函数，LangGraph 会自动将其包装为 SystemMessage
                self.agent_executor = create_react_agent(
                    model=llm,
                    tools=tools,
                    prompt=create_dynamic_prompt  # 🔥 添加动态提示词函数
                )
                logger.info(f"[{name}] ✅ LangGraph ReAct Agent Executor 初始化成功（支持动态系统提示词）")
            except Exception as e:
                logger.error(f"[{name}] ❌ Agent Executor 初始化失败: {e}")
                self.agent_executor = None
        else:
            logger.warning(f"[{name}] ⚠️ 未提供工具，Agent 将仅具备基础对话能力")

    def _get_company_name(self, ticker: str, market_info: dict) -> str:
        """根据股票代码获取公司名称"""
        try:
            if market_info["is_china"]:
                from tradingagents.dataflows.interface import get_china_stock_info_unified

                stock_info = get_china_stock_info_unified(ticker)
                if "股票名称:" in stock_info:
                    company_name = stock_info.split("股票名称:")[1].split("\n")[0].strip()
                    logger.debug(f"📊 [DEBUG] 从统一接口获取中国股票名称: {ticker} -> {company_name}")
                    return company_name
                return f"股票代码{ticker}"

            if market_info["is_hk"]:
                try:
                    from tradingagents.dataflows.providers.hk.improved_hk import get_hk_company_name_improved
                    company_name = get_hk_company_name_improved(ticker)
                    return company_name
                except Exception:
                    clean_ticker = ticker.replace(".HK", "").replace(".hk", "")
                    return f"港股{clean_ticker}"

            if market_info["is_us"]:
                us_stock_names = {
                    "AAPL": "苹果公司", "TSLA": "特斯拉", "NVDA": "英伟达",
                    "MSFT": "微软", "GOOGL": "谷歌", "AMZN": "亚马逊",
                    "META": "Meta", "NFLX": "奈飞",
                }
                return us_stock_names.get(ticker.upper(), f"美股{ticker}")

            return f"股票{ticker}"

        except Exception as exc:
            logger.error(f"❌ [DEBUG] 获取公司名称失败: {exc}")
            return f"股票{ticker}"

    def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        start_time = now_utc()

        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        session_id = state.get("session_id", "未知会话")

        logger.info(f"[{self.name}] 开始分析 {ticker}，日期: {current_date}，会话: {session_id}")

        # 获取市场信息和公司名称
        market_info = StockUtils.get_market_info(ticker)
        company_name = self._get_company_name(ticker, market_info)
        logger.info(f"[{self.name}] 公司名称: {company_name}")

        final_report = ""
        executed_tool_calls = 0

        # 🔥 修复：系统提示词现在由 create_dynamic_prompt 函数在初始化时处理
        # 这里只需要准备输入消息（不含 SystemMessage）

        # 构造输入消息列表
        input_messages = []

        # 1. 添加历史消息
        history_messages = list(state.get("messages", []))
        if history_messages:
            input_messages.extend(history_messages)
        else:
            # 如果没有历史消息，添加初始指令
            input_messages.append(HumanMessage(content=f"请分析 {company_name} ({ticker})，日期 {current_date}"))

        # 3. 执行 Agent
        if self.agent_executor:
            try:
                logger.info(f"[{self.name}] 🚀 启动 LangGraph ReAct Agent...")

                # 🔥 显式设置递归限制，防止模型陷入死循环
                # 恢复为全局默认的 100 步，避免复杂分析任务被过早中断
                # 捕获 RecursionError 需要在外部进行，但设置 limit 可以避免无限等待
                
                # 🔄 改用 stream 模式以捕获中间步骤，实现 Graceful Exit
                # 如果使用 invoke，一旦触发 RecursionError，中间产生的所有 ToolCalls 和思考都会丢失
                final_state = state.copy()  # 初始化为当前状态
                collected_messages = []     # 收集本轮执行产生的新消息
                
                # 使用 stream 模式执行
                # stream_mode="values" 会返回状态字典的更新
                iterator = self.agent_executor.stream(
                    {"messages": input_messages},
                    config={"recursion_limit": 50},
                    stream_mode="values"
                )
                
                for step_state in iterator:
                    # step_state 是当前完整状态（包含累积的 messages）
                    if "messages" in step_state:
                        # 更新最终状态
                        final_state = step_state
                        # 记录消息数量变化，用于调试
                        current_msg_count = len(step_state["messages"])
                        # logger.debug(f"[{self.name}] ⏳ 步骤更新，当前消息数: {current_msg_count}")

                result_state = final_state
                result_messages = result_state.get("messages", [])

                # --- 简化调试日志 ---
                executed_tool_calls = sum(1 for msg in result_messages if isinstance(msg, ToolMessage))

                if result_messages and isinstance(result_messages[-1], AIMessage):
                    final_report = result_messages[-1].content
                    logger.info(f"[{self.name}] ✅ Agent 执行完成，报告长度: {len(final_report)}")
                else:
                    logger.warning(f"[{self.name}] ⚠️ Agent 未返回 AIMessage，结果状态: {result_state.keys()}")
                    # 尝试从最后一条消息获取内容，即使它不是 AIMessage (虽然不太可能)
                    if result_messages:
                        final_report = str(result_messages[-1].content)
                    else:
                        final_report = "分析未生成有效内容。"

            except Exception as e:
                import traceback
                error_msg = str(e)
                logger.error(f"[{self.name}] 分析失败: {type(e).__name__} - {str(e)}")

                # --- Debug: 打印死循环时的最后几条消息 ---
                try:
                    debug_messages = final_state.get("messages", [])
                    if debug_messages:
                        logger.error(f"[{self.name}] 🔍 异常现场回溯 (最后 5 条消息):")
                        for i, msg in enumerate(debug_messages[-5:]):
                            content_preview = str(msg.content)[:500]
                            if isinstance(msg, ToolMessage):
                                logger.error(f"   {i+1}. [ToolMessage] {msg.name}: {content_preview}")
                            elif isinstance(msg, AIMessage):
                                tool_calls = getattr(msg, 'tool_calls', [])
                                logger.error(f"   {i+1}. [AIMessage] ToolCalls={tool_calls} Content={content_preview}")
                            else:
                                logger.error(f"   {i+1}. [{type(msg).__name__}] {content_preview}")
                except Exception as debug_err:
                    logger.error(f"[{self.name}] 无法打印调试信息: {debug_err}")
                # ----------------------------------------
                
                # 🛡️ 智能死循环恢复 (Graceful Exit)
                if "recursion limit" in error_msg.lower() or "need more steps" in error_msg.lower():
                     logger.warning(f"[{self.name}] 递归限制触发，正在生成总结报告...")
                     
                     try:
                         # 1. 获取目前为止收集到的所有消息（即使 invoke 失败，我们可能从之前的 stream 中拿不到，
                         #    但在 stream 循环内部抛出异常时，final_state 可能保留了最后一次成功的状态）
                         #    ⚠️ 注意：如果 stream 在第一次 yield 之前就挂了，final_state 还是初始值。
                         #    ⚠️ 如果是在中间挂了，final_state 应该是最近一次成功的 update。
                         
                         history_so_far = final_state.get("messages", [])
                         
                         # 2. 构造“强制总结”提示
                         force_summary_prompt = (
                             "\n\n🚨【系统紧急指令】🚨\n"
                             "由于任务执行步骤过多，系统已强制中断工具调用。\n"
                             "请忽略尚未完成的步骤。\n"
                             "请立即基于**以上所有对话历史**和**已获取的工具结果**，生成一份最终分析报告。\n"
                             "报告必须包含：\n"
                             "1. ⚠️ 在开头显著位置注明：'（由于步骤限制，部分分析可能未完成）'。\n"
                             "2. 已确认的事实和数据。\n"
                             "3. 基于现有信息的推断和结论。\n"
                             "4. 缺失信息的说明。\n"
                             "不要再试图调用任何工具！直接输出报告内容。"
                         )
                         
                         # 3. 再次调用 LLM (不带工具，纯对话模式)
                         recovery_messages = history_so_far + [HumanMessage(content=force_summary_prompt)]
                         
                         logger.info(f"[{self.name}] 🚑 正在请求 LLM 进行紧急总结...")
                         recovery_response = self.llm.invoke(recovery_messages)
                         final_report = recovery_response.content
                         
                         logger.info(f"[{self.name}] ✅ 紧急总结成功，报告长度: {len(final_report)}")
                         
                     except Exception as recovery_error:
                         logger.error(f"[{self.name}] 紧急总结失败: {recovery_error}")
                         final_report = f"# ⚠️ 分析中断\n\n由于任务过于复杂或工具调用陷入循环，智能体已达到最大执行步数限制，且无法生成总结。\n\n错误详情: {error_msg}"
                else:
                     logger.error(f"[{self.name}] 分析异常: {traceback.format_exc()}")
                     final_report = f"# ❌ 分析失败\n\n智能体执行过程中发生严重错误，无法完成分析。\n\n**错误详情**:\n```\n{error_msg}\n```\n\n请检查日志获取更多信息。"
        else:
             # 无工具模式：直接调用 LLM
             try:
                 logger.info(f"[{self.name}] 无工具模式，直接调用 LLM")
                 response = self.llm.invoke(input_messages)
                 final_report = response.content
             except Exception as e:
                 logger.error(f"[{self.name}] LLM 调用失败: {e}")
                 final_report = f"# ❌ 分析失败\n\nLLM 调用失败。\n\n**错误详情**:\n{str(e)}"

        total_time = (now_utc() - start_time).total_seconds()
        logger.info(f"[{self.name}] 完成，耗时 {total_time:.2f}s")

        # 构造返回字典
        internal_key = self.slug.replace("-analyst", "").replace("-", "_")
        report_key = f"{internal_key}_report"

        # 🔥 确保 final_report 始终有值，即使发生异常
        if not final_report:
            final_report = "# ⚠️ 无报告生成\n\n智能体未返回有效内容。"

        # 🔥 给 AIMessage 添加 name 属性，作为最终的兜底提取机制
        # LangGraph 会自动合并 messages，这样即使 reports 字典被覆盖，也能从历史消息中找回
        ai_msg = AIMessage(content=final_report, name=report_key)

        result = {
            "messages": [ai_msg],
            f"{internal_key}_tool_call_count": executed_tool_calls,
            "report": final_report
        }

        result[report_key] = final_report

        # 🔥 同时写入 reports 字典，支持动态添加的智能体（绕过 TypedDict 限制）
        result["reports"] = {report_key: final_report}

        logger.info(f"[{self.name}] 📝 报告已写入 state['{report_key}'] 和 state['reports'] (msg.name={report_key})")

        return result
