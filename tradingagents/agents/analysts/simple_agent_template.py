"""
第一阶段智能体模板

参考阶段2-4的简单实现模式：
- 手动构建消息列表
- 直接 llm.invoke(messages)
- 手动控制工具调用循环
- 完全可控的执行流程
- 🔥 防止工具调用陷入死循环：连续同一工具超过3次触发总结
- 🔥 S11 修复：添加 LLM 调用速率限制
"""

import json
from typing import Any
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from typing import Dict, Any, List
from tradingagents.utils.logging_init import get_logger

logger = get_logger("simple_agent_template")

# 🔥 S11: 导入速率限制器
try:
    from tradingagents.utils.llm_rate_limiter import get_rate_limiter
    _RATE_LIMITER_AVAILABLE = True
except ImportError:
    _RATE_LIMITER_AVAILABLE = False
    logger.warning("⚠️ LLM 速率限制器不可用，将不进行速率限制")


def format_tool_result(tool_result: Any) -> str:
    """
    将工具调用结果转换为字符串格式
    
    处理规则：
    - None: 转换为空字符串
    - dict: 转换为格式化的 JSON 字符串
    - list: 转换为格式化的 JSON 字符串
    - 其他类型: 转换为字符串表示
    
    Args:
        tool_result: 工具调用的返回值
        
    Returns:
        字符串格式的结果
    """
    if tool_result is None:
        return ""
    elif isinstance(tool_result, dict):
        return json.dumps(tool_result, ensure_ascii=False, indent=2)
    elif isinstance(tool_result, list):
        return json.dumps(tool_result, ensure_ascii=False, indent=2)
    else:
        return str(tool_result)


def create_simple_agent(
    name: str,
    slug: str,
    llm: Any,
    tools: List[Any],
    system_prompt: str,
    max_tool_calls: int = 20,
    llm_provider: str = "default",
):
    """
    创建简单智能体节点函数
    
    核心理念（参考阶段2-4）：
    1. 手动构建消息列表（System + Human + AI history + Tool results）
    2. llm.invoke(messages)
    3. 检查是否有工具调用
    4. 如果有，执行工具并继续
    5. 如果没有，完成并返回报告
    
    🔥 防止循环机制：
    - 最大工具调用次数：20次（硬编码）
    - 连续同一工具调用检测：如果同一工具连续调用超过3次，触发总结
    
    🔥 S11 修复：添加 LLM 调用速率限制
    
    Args:
        name: 智能体名称
        slug: 智能体标识符
        llm: LLM 实例
        tools: 工具列表
        system_prompt: 系统提示词
        max_tool_calls: 最大工具调用次数（固定为20）
        llm_provider: LLM 提供商名称（用于速率限制）
    
    Returns:
        节点函数（可以直接添加到 LangGraph）
    """
    
    # 🔥 S11: 获取速率限制器
    rate_limiter = None
    if _RATE_LIMITER_AVAILABLE:
        try:
            rate_limiter = get_rate_limiter()
        except Exception as e:
            logger.warning(f"⚠️ 获取速率限制器失败: {e}")
    
    def _invoke_with_rate_limit(llm_instance, messages):
        """带速率限制的 LLM 调用"""
        if rate_limiter:
            return rate_limiter.rate_limited_call(
                llm_provider,
                llm_instance.invoke,
                messages
            )
        return llm_instance.invoke(messages)
    
    def simple_agent_node(state: Dict[str, Any]) -> Dict[str, Any]:
        """
        简单智能体节点函数
        
        流程（完全参考阶段2的 bull_researcher）：
        1. 构建系统提示词（包含公司名称、日期等上下文）
        2. 构建消息列表
        3. 循环：LLM 调用 → 工具执行 → LLM 调用 → ...
        4. 返回更新后的 state
        """
        logger.info(f"🤖 [{name}] 开始分析")
        
        # === 进度追踪 ===
        from tradingagents.agents.analysts.dynamic_analyst import ProgressManager
        from tradingagents.agents.analysts.simple_agent_factory import SimpleAgentFactory

        icon = SimpleAgentFactory._get_analyst_icon(slug, name)
        display_name = f"{icon} {name}"
        ProgressManager.node_start(display_name)
        
        try:
            # === 步骤1：获取上下文信息（参考 bull_researcher.py 第50-97行） ===
            ticker = state.get("company_of_interest", "")
            trade_date = state.get("trade_date", "")
        
            # 获取公司名称
            from tradingagents.utils.stock_utils import StockUtils
            market_info = StockUtils.get_market_info(ticker)
            
            company_name = ticker  # 默认
            try:
                if market_info["is_china"]:
                    from tradingagents.dataflows.interface import get_china_stock_info_unified
                    stock_info = get_china_stock_info_unified(ticker)
                    if "股票名称:" in stock_info:
                        company_name = stock_info.split("股票名称:")[1].split("\n")[0].strip()
                elif market_info["is_hk"]:
                    from tradingagents.dataflows.providers.hk.improved_hk import get_hk_company_name_improved
                    company_name = get_hk_company_name_improved(ticker)
                elif market_info["is_us"]:
                    us_stock_names = {
                        "AAPL": "苹果公司", "TSLA": "特斯拉", "NVDA": "英伟达",
                        "MSFT": "微软", "GOOGL": "谷歌", "AMZN": "亚马逊",
                        "META": "Meta", "NFLX": "奈飞",
                    }
                    company_name = us_stock_names.get(ticker.upper(), f"美股{ticker}")
            except Exception as e:
                logger.warning(f"⚠️ [{name}] 获取公司名称失败: {e}")
            
            # 构建上下文前缀（参考 bull_researcher.py 第110-118行）
            context_prefix = f"""
股票代码：{ticker}
公司名称：{company_name}
分析日期：{trade_date}
"""
            
            # 构建完整系统提示词
            full_system_prompt = context_prefix + "\n\n" + system_prompt
            
            # === 步骤2：构建初始消息列表（参考 bull_researcher.py 第120行） ===
            messages = [SystemMessage(content=full_system_prompt)]
            
            # 添加任务描述
            task_message = f"请对股票 {company_name} ({ticker}) 进行全面分析，交易日期：{trade_date}"
            messages.append(HumanMessage(content=task_message))
            
            # === 步骤3：LLM + 工具调用循环（参考 GenericAgent，但简化） ===
            tool_call_count = 0
            final_report = ""
            
            # 🔥 防止循环机制：记录连续调用同一工具的次数
            last_tool_name = None
            consecutive_same_tool_count = 0
            MAX_CONSECUTIVE_SAME_TOOL = 3  # 连续同一工具最大调用次数
            
            logger.info(f"🔧 [{name}] 开始分析循环，最大工具调用次数: {max_tool_calls}")
            
            while tool_call_count < max_tool_calls:
                # 调用 LLM
                logger.debug(f"🧠 [{name}] 第 {tool_call_count + 1} 次 LLM 调用")
                
                try:
                    # 绑定工具到 LLM
                    llm_with_tools = llm.bind_tools(tools)
                    # 🔥 S11: 使用速率限制的调用
                    response = _invoke_with_rate_limit(llm_with_tools, messages)
                    logger.debug(f"✅ [{name}] LLM 调用成功，响应类型: {type(response).__name__}")
                except Exception as e:
                    logger.error(f"❌ [{name}] LLM 调用失败: {e}", exc_info=True)
                    # LLM 调用失败，使用当前最后的消息作为报告
                    last_ai_message = [msg for msg in messages if isinstance(msg, AIMessage)][-1] if messages else None
                    if last_ai_message:
                        final_report = last_ai_message.content
                        logger.warning(f"⚠️ [{name}] LLM 调用失败，使用最后一条消息作为报告")
                    else:
                        final_report = f"❌ 分析失败：LLM 调用异常 - {str(e)}"
                    break
                
                # 检查是否有工具调用
                if hasattr(response, "tool_calls") and response.tool_calls:
                    logger.info(f"🔧 [{name}] 检测到 {len(response.tool_calls)} 个工具调用")
                    
                    # 🔥 循环检测：检查所有工具调用，生成工具调用签名
                    # 修复 S1: 之前只检查第一个工具，现在检查所有工具的组合
                    current_tool_signature = []
                    for tc in response.tool_calls:
                        if isinstance(tc, dict):
                            tc_name = tc.get("name", "")
                        else:
                            tc_name = getattr(tc, "name", "")
                        if tc_name:
                            current_tool_signature.append(tc_name)
                    
                    # 将工具调用列表转为排序后的字符串作为签名
                    current_tool_name = ",".join(sorted(current_tool_signature)) if current_tool_signature else None
                    
                    # 检查连续调用同一工具组合
                    if current_tool_name == last_tool_name and current_tool_name:
                        consecutive_same_tool_count += 1
                        logger.warning(f"⚠️ [{name}] 连续调用相同工具组合 [{current_tool_name}] 第 {consecutive_same_tool_count} 次")
                        
                        # 🔥 触发总结机制：连续相同工具组合超过3次
                        if consecutive_same_tool_count >= MAX_CONSECUTIVE_SAME_TOOL:
                            logger.warning(f"🚨 [{name}] 检测到工具调用死循环！连续调用 [{current_tool_name}] 超过 {MAX_CONSECUTIVE_SAME_TOOL} 次，触发总结机制")
                            
                            # 先添加 AI 响应到消息历史（即使触发总结也要保留）
                            messages.append(response)
                            
                            # 添加强制总结指令
                            force_summary_prompt = HumanMessage(
                                content=f"""
🚨【系统紧急指令】🚨

检测到工具调用可能陷入循环（连续调用 {current_tool_name} 超过 {MAX_CONSECUTIVE_SAME_TOOL} 次）。

请立即停止调用任何工具，基于已获取的所有工具结果，生成最终分析报告。

不要再调用任何工具！直接输出完整的分析报告内容。
"""
                            )
                            messages.append(force_summary_prompt)
                            
                            # 最后一次 LLM 调用（不绑定工具，强制生成报告）
                            try:
                                # 🔥 S11: 使用速率限制的调用
                                final_response = _invoke_with_rate_limit(llm, messages)
                                final_report = final_response.content
                                messages.append(final_response)
                                logger.info(f"✅ [{name}] 强制总结完成，报告长度: {len(final_report)} 字符")
                            except Exception as e:
                                logger.error(f"❌ [{name}] 强制总结失败: {e}", exc_info=True)
                                # 使用最后一条 AI 消息作为报告
                                last_ai_message = [msg for msg in messages if isinstance(msg, AIMessage)][-1] if messages else None
                                if last_ai_message:
                                    final_report = last_ai_message.content
                                else:
                                    final_report = f"❌ 分析失败：工具调用陷入循环，且强制总结失败"
                            break
                    else:
                        # 工具切换或首次调用，重置计数器
                        if current_tool_name:
                            if current_tool_name != last_tool_name:
                                # 工具切换了，重置计数器为1
                                consecutive_same_tool_count = 1
                                last_tool_name = current_tool_name
                            else:
                                # 首次调用该工具（last_tool_name 为 None）
                                consecutive_same_tool_count = 1
                                last_tool_name = current_tool_name
                
                # 执行工具调用（只有在未触发总结机制时才执行）
                if not final_report:
                    # 先添加 AI 响应到消息历史
                    messages.append(response)
                    
                    # 执行所有工具调用
                    for tool_call in response.tool_calls:
                        # 解析工具调用信息
                        if isinstance(tool_call, dict):
                            tool_name = tool_call.get("name", "")
                            tool_args = tool_call.get("args", {})
                            tool_call_id = tool_call.get("id", "")
                        else:
                            tool_name = getattr(tool_call, "name", "")
                            tool_args = getattr(tool_call, "args", {})
                            tool_call_id = getattr(tool_call, "id", "")
                        
                        logger.info(f"🔧 [{name}] 调用工具: {tool_name}")
                        
                        # 查找工具
                        tool = None
                        for t in tools:
                            if getattr(t, "name", None) == tool_name:
                                tool = t
                                break
                        
                        if tool:
                            try:
                                # 执行工具
                                tool_result = tool.invoke(tool_args)
                                
                                # 🔥 使用统一的工具结果格式化函数
                                result_str = format_tool_result(tool_result)
                                
                                # 将工具结果添加到消息历史
                                messages.append(ToolMessage(
                                    content=result_str,
                                    tool_call_id=tool_call_id,
                                    name=tool_name
                                ))
                                
                                tool_call_count += 1
                                logger.info(f"✅ [{name}] 工具 {tool_name} 执行成功 (第{tool_call_count}次)")
                                
                            except Exception as e:
                                logger.error(f"❌ [{name}] 工具 {tool_name} 执行失败: {e}", exc_info=True)
                                # 添加错误消息
                                error_msg = f"工具调用失败: {str(e)}"
                                messages.append(ToolMessage(
                                    content=error_msg,
                                    tool_call_id=tool_call_id,
                                    name=tool_name
                                ))
                                tool_call_count += 1
                                logger.warning(f"⚠️ [{name}] 工具 {tool_name} 执行失败，继续尝试")
                        else:
                            logger.warning(f"⚠️ [{name}] 工具 {tool_name} 未找到")
                            tool_call_count += 1
                            # 添加工具未找到的消息
                            messages.append(ToolMessage(
                                content=f"工具 {tool_name} 未找到",
                                tool_call_id=tool_call_id,
                                name=tool_name
                            ))
                else:
                    # 没有工具调用，说明已完成
                    logger.info(f"✅ [{name}] 分析完成（未检测到工具调用）")
                    final_report = response.content
                    messages.append(response)
                    break
            
            # 如果达到最大工具调用次数还没有完成，强制使用最后一条消息作为报告
            if not final_report:
                last_ai_message = [msg for msg in messages if isinstance(msg, AIMessage)][-1] if messages else None
                if last_ai_message:
                    final_report = last_ai_message.content
                    logger.warning(f"⚠️ [{name}] 达到最大工具调用次数 ({max_tool_calls})，使用最后一条消息作为报告")
                else:
                    final_report = "❌ 分析未完成：没有生成任何报告"
                    logger.error(f"❌ [{name}] 分析未完成：没有生成任何报告")
            
            # === 步骤4：更新 state 并返回（参考 bull_researcher.py 第261-267行） ===
            internal_key = slug.replace("-analyst", "").replace("-", "_")
            report_key = f"{internal_key}_report"
            
            logger.info(f"✅ [{name}] 分析完成，报告长度: {len(final_report)} 字符")
            
            # 进度追踪：节点执行完成
            ProgressManager.node_end(display_name)
            
            # 🔥 只返回报告内容，不返回完整消息历史，避免 token 溢出
            # 参考 dynamic_analyst.py 中 analyst_subgraph_node 的实现
            final_message = AIMessage(content=final_report) if final_report else None
            
            return {
                **state,  # 保留所有原有字段
                "messages": [final_message] if final_message else [],  # 🔥 只返回最后一条消息（报告）
                report_key: final_report,  # 添加报告
                "reports": {
                    **state.get("reports", {}),
                    report_key: final_report  # 合并到 reports 字典
                }
            }
        except Exception as e:
            # 确保进度追踪在异常时也能结束
            ProgressManager.node_end(display_name)
            logger.error(f"❌ [{name}] 分析过程中发生异常: {e}", exc_info=True)
            
            # 返回错误报告
            internal_key = slug.replace("-analyst", "").replace("-", "_")
            report_key = f"{internal_key}_report"
            error_report = f"❌ 分析失败：{str(e)}"
            
            return {
                **state,
                report_key: error_report,
                "reports": {
                    **state.get("reports", {}),
                    report_key: error_report
                }
            }
    
    return simple_agent_node

