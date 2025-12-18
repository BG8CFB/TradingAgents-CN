import json
from langchain_core.messages import HumanMessage, SystemMessage
from tradingagents.utils.logging_init import get_logger

logger = get_logger("default")

def create_summary_agent(llm):
    """
    创建结构化总结智能体，负责生成前端展示所需的 JSON 数据
    """
    def summary_node(state):
        logger.info("📊 [Summary Agent] 开始生成结构化总结数据...")
        
        # 1. 收集所有上下文信息
        company_name = state.get("company_of_interest", "Unknown")
        
        # 🔥 动态发现所有 *_report 字段，自动支持新添加的分析师报告
        all_reports = {}
        for key in state.keys():
            if key.endswith("_report") and state[key]:
                all_reports[key] = state[key]
        
        # 核心报告（兼容旧代码）
        market_report = state.get("market_report", "")
        news_report = state.get("news_report", "")
        fundamentals_report = state.get("fundamentals_report", "")
        sentiment_report = state.get("sentiment_report", "")
        
        # 交易计划与最终决策
        trader_plan = state.get("trader_investment_plan", "")
        final_decision = state.get("final_trade_decision", "")
        
        # 辩论历史
        risk_debate_history = state.get("risk_debate_state", {}).get("history", "")
        
        # 2. 构建 Prompt
        system_prompt = f"""您是专门负责为前端交易仪表盘生成结构化数据的"数据总结智能体"。
您的任务是阅读所有的分析报告、交易计划和风险辩论结果，提取关键指标，并输出严格的 JSON 格式数据。

⚠️ 严格要求：
1. **只输出纯 JSON**，不要包含 markdown 代码块（如 ```json ... ```），不要包含任何解释性文字。
2. **真实性检查**：如果输入的分析报告（analysis reports）内容为空，或者包含明显的"工具调用失败"、"获取数据失败"等错误信息，请务必在 `risk_assessment.description` 中如实说明“数据获取失败，无法生成报告”，并将 `model_confidence` 设为 0。**严禁在缺乏数据的情况下编造数值或建议**。
3. **数值类型**必须是数字（int/float），不要用字符串。
4. **纯文本输出**：`analysis_summary` 和 `investment_recommendation` 字段必须是纯文本，**严禁使用 Markdown 格式**（如 **加粗**、## 标题等），确保前端显示整洁。

JSON 结构定义如下：
{{
    "key_indicators": {{
        "entry_price": "入场价格描述 (string)",
        "target_price": "目标价格描述 (string)",
        "stop_loss": "止损价格描述 (string)",
        "support_level": "支撑位 (string)",
        "resistance_level": "阻力位 (string)"
    }},
    "model_confidence": 0-100之间的整数 (int),
    "risk_assessment": {{
        "level": "High/Medium/Low (string)",
        "score": 0-10之间的评分 (float),
        "description": "简短的风险描述 (string)"
    }},
    "analysis_summary": "200字以内的分析摘要，纯文本格式，简明扼要地总结核心逻辑和多空观点 (string)。如果无数据，请填'数据获取失败'。",
    "investment_recommendation": "200字以内的投资建议，纯文本格式，给出明确的操作指令（买入/卖出/观望）和核心理由 (string)。如果无数据，请填'无建议'。",
    "analysis_reference": [
        {{
            "title": "参考来源标题 (string)",
            "url": "如有链接则填，无则留空 (string)",
            "summary": "关键信息摘要 (string)"
        }}
    ],
    "final_signal": "Buy/Sell/Hold (string)"
}}

数据源参考：
- 交易员计划：{trader_plan}
- 最终决策：{final_decision}
- 市场报告片段：{market_report[:500]}...
- 风险辩论片段：{risk_debate_history[-1000:] if risk_debate_history else ""}...
"""

        user_prompt = f"请为 {company_name} 生成结构化总结数据。"

        # 3. 调用 LLM
        try:
            response = llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt)
            ])
            
            content = response.content.strip()
            
            # 清理可能的 markdown 标记
            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            # 解析 JSON
            structured_data = json.loads(content)
            logger.info(f"✅ [Summary Agent] 成功生成结构化数据: {list(structured_data.keys())}")
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ [Summary Agent] JSON 解析失败: {e}")
            logger.error(f"   原始内容: {content}")
            # 回退默认值
            structured_data = {
                "key_indicators": {"entry_price": "N/A", "target_price": "N/A", "stop_loss": "N/A"},
                "model_confidence": 50,
                "risk_assessment": {"level": "Medium", "score": 5.0, "description": "解析失败，使用默认值"},
                "analysis_reference": [],
                "final_signal": "Hold"
            }
        except Exception as e:
            logger.error(f"❌ [Summary Agent] 生成失败: {e}", exc_info=True)
            # 即使失败也要返回空字典，防止图执行中断
            structured_data = {
                "key_indicators": {"entry_price": "N/A", "target_price": "N/A", "stop_loss": "N/A"},
                "model_confidence": 0,
                "risk_assessment": {"level": "Low", "score": 0.0, "description": "生成失败"},
                "analysis_summary": "系统错误：无法生成分析摘要",
                "investment_recommendation": "暂无建议",
                "analysis_reference": [],
                "final_signal": "Hold"
            }

        return {"structured_summary": structured_data}

    return summary_node
