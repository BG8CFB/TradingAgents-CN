"""初始 state 构造（字段与旧 Propagator.create_initial_state 完全一致，纯 dict）"""

from typing import Any, Dict, Optional

from app.utils.logging_init import get_logger

logger = get_logger("orchestrator.state")


def create_initial_state(
    company_name: str,
    trade_date: str,
    task_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """创建流水线初始状态"""
    from app.llm.core.types import Message, Role

    task_description = f"请对股票 {company_name} 进行全面分析，交易日期：{trade_date}"

    state: Dict[str, Any] = {
        "messages": [Message(role=Role.USER, content=task_description)],
        "company_of_interest": company_name,
        "trade_date": str(trade_date),
        "task_id": task_id,
        "user_id": user_id or "",  # 任务发起者（token 用量统计归属）
        "investment_debate_state": {
            "history": "",
            "current_response": "",
            "count": 0,
            "current_round_index": 0,
            "max_rounds": 2,
            "rounds": [],
            "bull_report_content": "",
            "bear_report_content": "",
            "bull_history": "",
            "bear_history": "",
            "judge_decision": "",
        },
        "risk_debate_state": {
            "history": "",
            "current_risky_response": "",
            "current_safe_response": "",
            "current_neutral_response": "",
            "count": 0,
            "latest_speaker": "",
            "risky_history": "",
            "safe_history": "",
            "neutral_history": "",
            "judge_decision": "",
            "rounds": [],
            "current_round_index": 0,
            "max_rounds": 3,
            "risky_report_content": "",
            "safe_report_content": "",
            "neutral_report_content": "",
        },
        "reports": {},
        # Trader / Judge / Summary 输出字段（与旧 AgentState 一致）
        "trader_investment_plan": "",
        "investment_plan": "",
        "final_trade_decision": "",
    }

    # 动态初始化前端配置的智能体报告字段
    try:
        from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory

        for agent in DynamicAnalystFactory.get_all_agents():
            slug = agent.get("slug", "")
            if not slug:
                continue
            internal_key = slug.replace("-analyst", "").replace("-", "_")
            report_key = f"{internal_key}_report"
            if report_key not in state:
                state[report_key] = ""
    except Exception as e:  # noqa: BLE001
        logger.warning(f"⚠️ 动态初始化智能体字段失败: {e}")

    return state
