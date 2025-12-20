import time
import json
import os

# 导入统一日志系统
from tradingagents.utils.logging_init import get_logger
logger = get_logger("default")

from langchain_core.messages import HumanMessage, SystemMessage

def create_research_manager(llm, memory):
    def research_manager_node(state) -> dict:
        logger.debug(f"👔 [DEBUG] ===== 研究经理 (Research Manager) 节点开始 =====")
        
        investment_debate_state = state["investment_debate_state"]

        # 1. 动态获取所有第一阶段基础报告
        all_reports = {}
        
        # 优先从 reports 字典获取（这是最可靠的源，由 reducer 合并）
        if "reports" in state and isinstance(state["reports"], dict):
            all_reports.update(state["reports"])
            
        # 兼容性补充：检查顶层 state 中的 _report 字段
        # 以防某些旧代码没有写入 reports 字典
        for key, value in state.items():
            if key.endswith("_report") and value and key not in all_reports:
                all_reports[key] = value
        
        # 获取报告显示名称映射
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
        
        # 2. 获取累积的辩论报告 (Markdown)
        bull_report = investment_debate_state.get("bull_report_content", "（无看涨报告）")
        bear_report = investment_debate_state.get("bear_report_content", "（无看跌报告）")
        
        # 3. 获取股票信息
        ticker = state.get('company_of_interest', 'Unknown')
        from tradingagents.utils.stock_utils import StockUtils
        market_info = StockUtils.get_market_info(ticker)
        
        # 获取公司名称
        def _get_company_name(ticker_code: str, market_info_dict: dict) -> str:
            """根据股票代码获取公司名称"""
            try:
                if market_info_dict['is_china']:
                    from tradingagents.dataflows.interface import get_china_stock_info_unified
                    stock_info = get_china_stock_info_unified(ticker_code)
                    if stock_info and "股票名称:" in stock_info:
                        name = stock_info.split("股票名称:")[1].split("\n")[0].strip()
                        return name
                    else:
                        # 降级方案
                        try:
                            from tradingagents.dataflows.data_source_manager import get_china_stock_info_unified as get_info_dict
                            info_dict = get_info_dict(ticker_code)
                            if info_dict and info_dict.get('name'):
                                name = info_dict['name']
                                return name
                        except Exception:
                            pass
                elif market_info_dict['is_hk']:
                    try:
                        from tradingagents.dataflows.providers.hk.improved_hk import get_hk_company_name_improved
                        name = get_hk_company_name_improved(ticker_code)
                        return name
                    except Exception:
                        clean_ticker = ticker_code.replace('.HK', '').replace('.hk', '')
                        return f"港股{clean_ticker}"
                elif market_info_dict['is_us']:
                    us_stock_names = {
                        'AAPL': '苹果公司', 'TSLA': '特斯拉', 'NVDA': '英伟达',
                        'MSFT': '微软', 'GOOGL': '谷歌', 'AMZN': '亚马逊',
                        'META': 'Meta', 'NFLX': '奈飞'
                    }
                    return us_stock_names.get(ticker_code.upper(), f"美股{ticker_code}")
            except Exception as e:
                logger.error(f"❌ [研究经理] 获取公司名称失败: {e}")
            return f"股票代码{ticker_code}"

        company_name = _get_company_name(ticker, market_info)
        currency = market_info['currency_name']

        # 4. 构建 Prompt
        from tradingagents.agents.utils.generic_agent import load_agent_config
        base_prompt = load_agent_config("research-manager")
        
        if base_prompt:
            # 动态构建环境上下文（KV 格式）
            context_prefix = f"""
股票代码：{ticker}
公司名称：{company_name}
价格单位：{currency}
通用规则：请始终使用公司名称而不是股票代码来称呼这家公司
"""
            # 将动态上下文拼接到配置指令前
            system_prompt = context_prefix + "\n" + base_prompt

        if not base_prompt:
             error_msg = "❌ 未找到 research-manager 智能体配置，请检查 phase2_agents_config.yaml 文件。"
             logger.error(error_msg)
             raise ValueError(error_msg)

        messages = [SystemMessage(content=system_prompt)]

        # 动态注入所有第一阶段报告
        for key, content in all_reports.items():
            if content:
                # 使用映射获取显示名称，如果没有则格式化 key
                display_name = report_display_names.get(key, key.replace("_report", "").replace("_", " ").title() + "报告")
                messages.append(HumanMessage(content=f"=== 基础资料：{display_name} ===\n{content}"))

        user_content = f"""
=== 看涨分析报告 (Bull Case) ===
{bull_report}

=== 看跌分析报告 (Bear Case) ===
{bear_report}
"""
        
        messages.append(HumanMessage(content=user_content))
        
        logger.info(f"👔 [Research Manager] 开始生成最终裁决报告...")
        
        # 4. 执行推理
        response = llm.invoke(messages)
        final_content = response.content
        
        # 5. 保存报告文件
        try:
            filename = "投资裁决报告.md"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(f"# {company_name} ({ticker}) 投资裁决报告\n\n")
                f.write(f"> 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"> 决策人：研究部主管\n\n")
                f.write(final_content)
            logger.info(f"👔 [Research Manager] 已生成裁决报告: {filename}")
        except Exception as e:
            logger.error(f"👔 [ERROR] 保存裁决报告失败: {e}")

        # 6. 更新状态
        new_investment_debate_state = {
            "judge_decision": final_content,
            "history": investment_debate_state.get("history", ""),
            "bear_history": investment_debate_state.get("bear_history", ""),
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": final_content,
            "count": investment_debate_state["count"],
            # 传递累积报告
            "rounds": investment_debate_state.get("rounds", []),
            "bull_report_content": bull_report,
            "bear_report_content": bear_report,
            "current_round_index": investment_debate_state.get("current_round_index", 0),
        }
        
        return {
            "investment_debate_state": new_investment_debate_state,
            "investment_plan": final_content,
            # 显式保存为报告，供前端展示
            "reports": {
                "research_team_decision": final_content
            }
        }

    return research_manager_node
