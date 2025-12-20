import functools
import time
import json

# 导入统一日志系统
from tradingagents.utils.logging_init import get_logger
logger = get_logger("default")


def create_trader(llm, memory):
    def trader_node(state, name):
        # 使用安全读取，确保缺失字段不会导致整个流程中断
        company_name = state.get("company_of_interest", "")
        
        # 🔥 动态发现所有 *_report 字段，自动支持新添加的分析师报告
        all_reports = {}
        for key in state.keys():
            if key.endswith("_report") and state[key]:
                all_reports[key] = state[key]

        # 使用统一的股票类型检测
        from tradingagents.utils.stock_utils import StockUtils
        market_info = StockUtils.get_market_info(company_name)
        
        # 根据股票类型确定货币单位
        currency = market_info['currency_name']
        currency_symbol = market_info['currency_symbol']
        is_china = market_info['is_china']
        is_hk = market_info['is_hk']
        is_us = market_info['is_us']

        logger.debug(f"💰 [DEBUG] ===== 交易员节点开始 (Stage 2) =====")
        logger.debug(f"💰 [DEBUG] 交易员检测股票类型: {company_name} -> {market_info['market_name']}, 货币: {currency}")
        logger.debug(f"💰 [DEBUG] 货币符号: {currency_symbol}")
        logger.debug(f"💰 [DEBUG] 市场详情: 中国A股={is_china}, 港股={is_hk}, 美股={is_us}")
        
        # 🔥 使用所有动态发现的报告构建 curr_situation
        curr_situation = "\n\n".join([content for content in all_reports.values() if content])

        # 检查memory是否可用
        if memory is not None:
            logger.warning(f"⚠️ [DEBUG] memory可用，获取历史记忆")
            past_memories = memory.get_memories(curr_situation, n_matches=2)
            past_memory_str = ""
            for i, rec in enumerate(past_memories, 1):
                past_memory_str += rec["recommendation"] + "\n\n"
        else:
            logger.warning(f"⚠️ [DEBUG] memory为None，跳过历史记忆检索")
            past_memories = []
            past_memory_str = "暂无历史记忆数据可参考。"

        # 获取研究团队辩论历史及最终裁决
        investment_debate_state = state.get("investment_debate_state", {})
        debate_history = investment_debate_state.get("history", "暂无辩论历史")
        judge_decision = investment_debate_state.get("judge_decision", "暂无研究部主管裁决")
        
        # 🔥 构建所有报告的格式化字符串（用于 prompt）
        # 从配置文件动态获取报告显示名称
        report_display_names = {}
        try:
            from tradingagents.agents.analysts.dynamic_analyst import DynamicAnalystFactory
            for agent in DynamicAnalystFactory.get_all_agents():
                slug = agent.get('slug', '')
                name = agent.get('name', '')
                if slug and name:
                    internal_key = slug.replace("-analyst", "").replace("-", "_")
                    report_key = f"{internal_key}_report"
                    report_display_names[report_key] = f"{name}报告"
        except Exception as e:
            logger.warning(f"⚠️ 无法从配置文件加载报告显示名称: {e}")
        
        all_reports_formatted = ""
        for key, content in all_reports.items():
            if content:
                display_name = report_display_names.get(key, key.replace("_report", "").replace("_", " ").title() + "报告")
                all_reports_formatted += f"\n### {display_name}\n{content}\n"
        
        # 构建纯数据上下文
        context_content = f"""
=== 基础分析报告 ===
{all_reports_formatted if all_reports_formatted else "（暂无分析师报告）"}

=== 研究团队辩论记录 (Bull vs Bear) ===
{debate_history}

=== 研究部主管最终裁决 ===
{judge_decision}

=== 历史交易反思 (类似情景) ===
{past_memory_str}
"""

        context = {
            "role": "user",
            "content": context_content,
        }

        # 加载基础Prompt
        from tradingagents.agents.utils.generic_agent import load_agent_config
        base_prompt = load_agent_config("trader")
        if not base_prompt:
             # Fallback if config is missing
             base_prompt = "您是一位专业的交易员。"
             logger.warning("⚠️ 未找到 trader 智能体配置，使用默认简易 Prompt。")

        # 动态环境信息注入（仅事实陈述）
        system_context = f"""
【环境信息】
- 标的代码：{company_name}
- 市场类型：{market_info['market_name']}
- 计价货币：{currency} ({currency_symbol})
- 当前时间：{time.strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        full_system_prompt = base_prompt + "\n\n" + system_context

        messages = [
            {
                "role": "system",
                "content": full_system_prompt,
            },
            context,
        ]

        logger.debug(f"💰 [DEBUG] 准备调用LLM，系统提示包含货币: {currency}")
        
        result = llm.invoke(messages)

        logger.debug(f"💰 [DEBUG] LLM调用完成")
        logger.debug(f"💰 [DEBUG] 交易员回复长度: {len(result.content)}")
        logger.debug(f"💰 [DEBUG] ===== 交易员节点结束 =====")

        return {
            "messages": [result],
            "trader_investment_plan": result.content,
            "sender": name,
        }

    return functools.partial(trader_node, name="Trader")
