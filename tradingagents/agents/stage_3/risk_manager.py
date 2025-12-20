import time
import json
import os

# 导入统一日志系统
from tradingagents.utils.logging_init import get_logger
logger = get_logger("default")

from langchain_core.messages import HumanMessage, SystemMessage

def create_risk_manager(llm, memory):
    def risk_manager_node(state) -> dict:
        logger.debug(f"👔 [DEBUG] ===== 首席风控官 (Risk Manager) 节点开始 =====")
        
        risk_debate_state = state["risk_debate_state"]
        
        # 1. 获取所有基础报告
        all_reports = {}
        if "reports" in state and isinstance(state["reports"], dict):
            all_reports.update(state["reports"])
            
        for key, value in state.items():
            if key.endswith("_report") and value and key not in all_reports:
                all_reports[key] = value

        # 2. 获取累积的辩论报告 (Markdown)
        risky_report = risk_debate_state.get("risky_report_content", "（无激进报告）")
        safe_report = risk_debate_state.get("safe_report_content", "（无保守报告）")
        neutral_report = risk_debate_state.get("neutral_report_content", "（无中性报告）")
        
        # 获取交易员计划 (Target)
        trader_plan = state.get("trader_investment_plan")
        if not trader_plan:
             trader_plan = state.get("investment_plan", "")
             if not trader_plan:
                 trader_plan = all_reports.get("research_team_decision", "（未找到交易员计划）")

        # 3. 获取股票信息
        ticker = state.get('company_of_interest', 'Unknown')
        from tradingagents.utils.stock_utils import StockUtils
        market_info = StockUtils.get_market_info(ticker)
        
        # 获取公司名称
        def _get_company_name(ticker_code: str, market_info_dict: dict) -> str:
            try:
                if market_info_dict['is_china']:
                    from tradingagents.dataflows.interface import get_china_stock_info_unified
                    stock_info = get_china_stock_info_unified(ticker_code)
                    if stock_info and "股票名称:" in stock_info:
                        return stock_info.split("股票名称:")[1].split("\n")[0].strip()
                    try:
                        from tradingagents.dataflows.data_source_manager import get_china_stock_info_unified as get_info_dict
                        info = get_info_dict(ticker_code)
                        if info and info.get('name'): return info['name']
                    except: pass
                elif market_info_dict['is_hk']:
                    try:
                        from tradingagents.dataflows.providers.hk.improved_hk import get_hk_company_name_improved
                        return get_hk_company_name_improved(ticker_code)
                    except: return f"港股{ticker_code.replace('.HK','')}"
                elif market_info_dict['is_us']:
                    us_names = {'AAPL': '苹果', 'TSLA': '特斯拉', 'NVDA': '英伟达', 'MSFT': '微软', 'GOOGL': '谷歌'}
                    return us_names.get(ticker_code.upper(), f"美股{ticker_code}")
            except: pass
            return f"股票代码{ticker_code}"

        company_name = _get_company_name(ticker, market_info)
        currency = market_info['currency_name']

        # 4. 构建 Prompt
        from tradingagents.agents.utils.generic_agent import load_agent_config
        base_prompt = load_agent_config("risk-manager")
        
        if not base_prompt:
             error_msg = "❌ 未找到 risk-manager 智能体配置，请检查 phase3_agents_config.yaml 文件。"
             logger.error(error_msg)
             raise ValueError(error_msg)

        context_prefix = f"""
股票代码：{ticker}
公司名称：{company_name}
价格单位：{currency}
通用规则：请始终使用公司名称而不是股票代码来称呼这家公司
"""
        system_prompt = context_prefix + "\n\n" + base_prompt
        messages = [SystemMessage(content=system_prompt)]

        # 注入基础报告 (Stage 1)
        for key, content in all_reports.items():
            if content and "report" in key:
                # 排除掉 Stage 3 自己的报告，避免冗余，或者选择性包含
                if any(x in key for x in ["risky_", "safe_", "neutral_"]): continue
                display_name = key.replace("_report", "").replace("_", " ").title() + "报告"
                messages.append(HumanMessage(content=f"=== 基础资料：{display_name} ===\n{content}"))

        # 注入完整辩论卷宗
        user_content = f"""
=== 原始交易计划 ===
{trader_plan}

=== 激进风险分析报告 (Risky Case) ===
{risky_report}

=== 保守风险分析报告 (Safe Case) ===
{safe_report}

=== 中性风险分析报告 (Neutral Case) ===
{neutral_report}

请基于以上所有资料（基础报告 + 三方辩论 + 原始计划），生成一份【最终风控裁决报告】。
报告应包含以下章节：
1. **风控裁决摘要**：明确的投资评级（买入/持有/卖出/观望）和核心风控理由。
2. **风险-收益权衡**：评估激进派的机会主义与保守派的风险规避，结合中性派的平衡观点，说明最终决策的依据。
3. **关键风险提示**：列出必须要关注的尾部风险。
4. **最终执行指令**：给交易员的具体指令（如修正后的建仓比例、严格的止损位、对冲策略等）。

请直接生成报告内容。
"""
        messages.append(HumanMessage(content=user_content))
        
        logger.info(f"👔 [Risk Manager] 开始生成最终风控裁决报告...")
        
        # 5. 执行推理
        response = llm.invoke(messages)
        final_content = response.content
        
        # 6. 保存报告文件
        try:
            filename = "投资组合风控报告.md"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(f"# {company_name} ({ticker}) 投资组合风控裁决报告\n\n")
                f.write(f"> 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"> 决策人：首席风控官\n\n")
                f.write(final_content)
            logger.info(f"👔 [Risk Manager] 已生成裁决报告: {filename}")
        except Exception as e:
            logger.error(f"👔 [ERROR] 保存裁决报告失败: {e}")

        # 7. 更新状态
        new_risk_debate_state = {
            "judge_decision": final_content,
            "history": risk_debate_state.get("history", ""),
            "risky_history": risk_debate_state.get("risky_history", ""),
            "safe_history": risk_debate_state.get("safe_history", ""),
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "current_response": final_content,
            "count": risk_debate_state["count"],
            "rounds": risk_debate_state.get("rounds", []),
            "risky_report_content": risky_report,
            "safe_report_content": safe_report,
            "neutral_report_content": neutral_report,
            "current_round_index": risk_debate_state.get("current_round_index", 0),
        }
        
        return {
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": final_content,
            "reports": {
                "risk_manager_decision": final_content
            }
        }

    return risk_manager_node
