from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
import time
import json
import os

# 导入统一日志系统
from tradingagents.utils.logging_init import get_logger
logger = get_logger("default")


def create_neutral_debator(llm):
    def neutral_node(state) -> dict:
        logger.debug(f"⚖️ [DEBUG] ===== 中性风险分析师节点开始 =====")
        
        risk_debate_state = state["risk_debate_state"]
        
        # 初始化多轮状态
        rounds = risk_debate_state.get("rounds", [])
        current_round_index = risk_debate_state.get("current_round_index", 0)
        max_rounds = risk_debate_state.get("max_rounds", 3)
        neutral_report_content = risk_debate_state.get("neutral_report_content", "")
        
        # 1. 获取所有基础报告 (Stage 1 & Stage 2)
        all_reports = {}
        if "reports" in state and isinstance(state["reports"], dict):
            all_reports.update(state["reports"])
            
        # 兼容性补充
        for key, value in state.items():
            if key.endswith("_report") and value and key not in all_reports:
                all_reports[key] = value

        # 获取交易员计划 (Target)
        trader_decision = state.get("trader_investment_plan")
        if not trader_decision:
             trader_decision = state.get("investment_plan", "")
             if not trader_decision:
                 trader_decision = all_reports.get("research_team_decision", "（未找到交易员计划）")
        
        # 2. 获取股票信息
        ticker = state.get('company_of_interest', 'Unknown')
        from tradingagents.utils.stock_utils import StockUtils
        market_info = StockUtils.get_market_info(ticker)
        
        # 获取公司名称 (复用 Stage 2 逻辑)
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

        logger.info(f"⚖️ [中性风险分析师] 当前轮次: {current_round_index}/{max_rounds}, 股票: {company_name}")

        # 3. 构建 System Prompt
        from tradingagents.agents.utils.generic_agent import load_agent_config
        base_prompt = load_agent_config("neutral-analyst")
        
        if not base_prompt:
             error_msg = "❌ 未找到 neutral-analyst 智能体配置，请检查 phase3_agents_config.yaml 文件。"
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

        # 4. 注入基础报告
        # 过滤掉自己生成的累积报告
        for key, content in all_reports.items():
            if content and "neutral_report" not in key: 
                display_name = key.replace("_report", "").replace("_", " ").title() + "报告"
                messages.append(HumanMessage(content=f"=== 参考资料：{display_name} ===\n{content}"))

        # 注入交易员计划 (靶子)
        messages.append(HumanMessage(content=f"=== 交易员原始投资计划 (本次辩论焦点) ===\n{trader_decision}"))

        # 5. 注入历史辩论 (Round 0 to N-1)
        # 关键：只看过去，不看现在 -> 实现并行逻辑
        if current_round_index > 0:
            logger.info(f"⚖️ [中性风险分析师] 注入历史辩论上下文 (Rounds 0 to {current_round_index-1})")
            for i in range(current_round_index):
                if i < len(rounds):
                    round_data = rounds[i]
                    
                    # 自己的历史观点
                    if "neutral" in round_data:
                        prefix = "【回顾】这是我在【初始阶段】的观点：" if i == 0 else f"【回顾】这是我在【辩论第 {i} 轮】的观点："
                        messages.append(AIMessage(content=f"{prefix}\n{round_data['neutral']}"))
                    
                    # 对手的历史观点 (激进派)
                    if "risky" in round_data:
                        prefix = "【回顾】激进派在【初始阶段】的观点：" if i == 0 else f"【回顾】激进派在【辩论第 {i} 轮】的观点："
                        messages.append(HumanMessage(content=f"{prefix}\n{round_data['risky']}"))
                        
                    # 对手的历史观点 (保守派)
                    if "safe" in round_data:
                        prefix = "【回顾】保守派在【初始阶段】的观点：" if i == 0 else f"【回顾】保守派在【辩论第 {i} 轮】的观点："
                        messages.append(HumanMessage(content=f"{prefix}\n{round_data['safe']}"))

        # 6. 构建 Trigger Message
        if current_round_index == 0:
            trigger_msg = "当前阶段：Round 0 初始观点陈述。\n请基于交易员计划和基础报告，阐述你的中性投资观点。平衡风险与收益，提出折中建议。"
            argument_prefix = "# 【中性派 - 初始观点】"
        else:
            trigger_msg = f"当前阶段：Round {current_round_index} 辩论。\n请阅读上方对手（激进派和保守派）在上一轮的观点。请调和双方矛盾，提出更合理的平衡方案。"
            argument_prefix = f"# 【中性派 - 第 {current_round_index} 轮辩论】"

        messages.append(HumanMessage(content=trigger_msg))

        # 7. 执行推理
        response = llm.invoke(messages)
        content = response.content
        
        # 清洗内容
        lines = content.strip().split('\n')
        cleaned_lines = []
        for line in lines:
            if line.strip().startswith("# ") and "中性" in line: continue
            cleaned_lines.append(line)
        content = '\n'.join(cleaned_lines).strip()

        # 8. 更新状态
        if current_round_index >= len(rounds):
            rounds.append({})
        
        rounds[current_round_index]["neutral"] = content
        
        # 累积报告
        section_title = "## 初始观点：中性策略" if current_round_index == 0 else f"## 第 {current_round_index} 轮辩论：中性派观点"
        if section_title not in neutral_report_content:
            neutral_report_content += f"\n\n{section_title}\n\n{content}"

        # 9. 保存文件
        try:
            filename = "中性风险分析报告.md"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(f"# {company_name} ({ticker}) 中性风险分析报告\n\n")
                f.write(f"> 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write(neutral_report_content)
            logger.info(f"⚖️ [中性风险分析师] 已更新报告文件: {filename}")
        except Exception as e:
            logger.error(f"⚖️ [ERROR] 保存报告文件失败: {e}")

        # 构造返回状态
        # 必须保留原有状态的所有字段，避免丢失历史数据
        new_risk_debate_state = risk_debate_state.copy()
        new_risk_debate_state.update({
            "rounds": rounds,
            "neutral_report_content": neutral_report_content,
            "neutral_history": risk_debate_state.get("neutral_history", "") + f"\n{argument_prefix}\n{content}",
            "history": risk_debate_state.get("history", "") + f"\n{argument_prefix}\n{content}",
            "current_neutral_response": content,
            "count": risk_debate_state.get("count", 0) + 1,
            "latest_speaker": "Neutral Analyst"
        })

        return {
            "risk_debate_state": new_risk_debate_state,
            "reports": {
                "neutral_analyst": neutral_report_content
            }
        }

    return neutral_node
