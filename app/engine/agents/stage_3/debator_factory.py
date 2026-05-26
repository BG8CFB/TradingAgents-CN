"""
Stage 3 风险辩手工厂 — 将 risky/safe/neutral 三方辩手的公共逻辑参数化。

用法:
    from app.engine.agents.stage_3.debator_factory import create_debator

    risky_node = create_debator(llm, side="risky")
    safe_node   = create_debator(llm, side="safe")
    neutral_node = create_debator(llm, side="neutral")

原文件 aggressive_debator.py / conservative_debator.py / neutral_debator.py
改为薄包装以保持向后兼容。
"""

import os
import time
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.utils.logging_init import get_logger
from app.engine.agents.utils.agent_config import (
    build_stage3_report_path,
    load_agent_config,
    resolve_company_name,
)

logger = get_logger("default")

# Stage 3 内部报告 key — 防止同轮泄漏
_STAGE3_REPORT_KEYS = frozenset({"risky_analyst", "safe_analyst", "neutral_analyst"})

# ── 辩手配置表 ──────────────────────────────────────────────────────────────

_SIDE_CONFIG = {
    "risky": {
        "slug": "risky-analyst",
        "emoji": "🔥",
        "label": "激进风险分析师",
        "tag": "激进派",
        "round_key": "risky",
        "opponents": ["safe", "neutral"],
        "opponent_labels": {"safe": "保守派", "neutral": "中性派"},
        "report_state_key": "risky_report_content",
        "history_key": "risky_history",
        "current_response_key": "current_risky_response",
        "report_key": "risky_analyst",
        "speaker": "Risky Analyst",
        "filter_keyword": "激进",
        "file_header": "# {company_name} ({ticker}) 激进风险分析报告",
        "file_slug": "risky_analyst",
        "section_initial": "## 初始观点：激进策略",
        "section_debate": "## 第 {round} 轮辩论：激进派反驳",
        "trigger_initial": (
            "当前阶段：Round 0 初始观点陈述。\n"
            "请基于交易员计划和基础报告，阐述你的激进投资观点。"
            "指出计划中过于保守的地方，强调潜在的高增长机会。"
        ),
        "trigger_debate": (
            "当前阶段：Round {round} 辩论。\n"
            "请阅读上方对手（保守派和中性派）在上一轮的观点。"
            "请直接反驳他们的担忧，坚持你的高风险高回报逻辑。"
        ),
    },
    "safe": {
        "slug": "safe-analyst",
        "emoji": "🛡️",
        "label": "保守风险分析师",
        "tag": "保守派",
        "round_key": "safe",
        "opponents": ["risky", "neutral"],
        "opponent_labels": {"risky": "激进派", "neutral": "中性派"},
        "report_state_key": "safe_report_content",
        "history_key": "safe_history",
        "current_response_key": "current_safe_response",
        "report_key": "safe_analyst",
        "speaker": "Safe Analyst",
        "filter_keyword": "保守",
        "file_header": "# {company_name} ({ticker}) 保守风险分析报告",
        "file_slug": "safe_analyst",
        "section_initial": "## 初始观点：保守策略",
        "section_debate": "## 第 {round} 轮辩论：保守派反驳",
        "trigger_initial": (
            "当前阶段：Round 0 初始观点陈述。\n"
            "请基于交易员计划和基础报告，阐述你的保守投资观点。"
            "指出计划中忽视的风险，强调本金安全的重要性。"
        ),
        "trigger_debate": (
            "当前阶段：Round {round} 辩论。\n"
            "请阅读上方对手（激进派和中性派）在上一轮的观点。"
            "请直接反驳他们的乐观假设，坚持你的风险控制逻辑。"
        ),
    },
    "neutral": {
        "slug": "neutral-analyst",
        "emoji": "⚖️",
        "label": "中性风险分析师",
        "tag": "中性派",
        "round_key": "neutral",
        "opponents": ["risky", "safe"],
        "opponent_labels": {"risky": "激进派", "safe": "保守派"},
        "report_state_key": "neutral_report_content",
        "history_key": "neutral_history",
        "current_response_key": "current_neutral_response",
        "report_key": "neutral_analyst",
        "speaker": "Neutral Analyst",
        "filter_keyword": "中性",
        "file_header": "# {company_name} ({ticker}) 中性风险分析报告",
        "file_slug": "neutral_analyst",
        "section_initial": "## 初始观点：中性策略",
        "section_debate": "## 第 {round} 轮辩论：中性派观点",
        "trigger_initial": (
            "当前阶段：Round 0 初始观点陈述。\n"
            "请基于交易员计划和基础报告，阐述你的中性投资观点。"
            "平衡风险与收益，提出折中建议。"
        ),
        "trigger_debate": (
            "当前阶段：Round {round} 辩论。\n"
            "请阅读上方对手（激进派和保守派）在上一轮的观点。"
            "请调和双方矛盾，提出更合理的平衡方案。"
        ),
    },
}


def create_debator(llm, side: Literal["risky", "safe", "neutral"] = "risky"):
    """
    创建 Stage 3 风险辩论节点。

    Args:
        llm: LangChain LLM 实例
        side: "risky"、"safe" 或 "neutral"

    Returns:
        可注册到 LangGraph 的节点函数
    """
    if side not in _SIDE_CONFIG:
        raise ValueError(f"未知的辩手方向: {side!r}，期望 'risky'、'safe' 或 'neutral'")

    cfg = _SIDE_CONFIG[side]
    emoji = cfg["emoji"]
    label = cfg["label"]

    # 预计算对手配置引用
    opponent_cfgs = {opp: _SIDE_CONFIG[opp] for opp in cfg["opponents"]}

    def debator_node(state) -> dict:
        logger.debug(f"{emoji} [DEBUG] ===== {label}节点开始 =====")

        risk_debate_state = state.get("risk_debate_state", {})

        # 初始化多轮状态
        rounds = risk_debate_state.get("rounds", [])
        current_round_index = risk_debate_state.get("current_round_index", 0)
        max_rounds = risk_debate_state.get("max_rounds", 3)
        report_content = risk_debate_state.get(cfg["report_state_key"], "")

        # ── 1. 获取所有基础报告 ──────────────────────────────────
        all_reports = {}
        if "reports" in state and isinstance(state["reports"], dict):
            all_reports.update(state["reports"])
        for key, value in state.items():
            if key.endswith("_report") and value and key not in all_reports:
                all_reports[key] = value

        # 获取交易员计划
        trader_decision = state.get("trader_investment_plan")
        if not trader_decision:
            trader_decision = state.get("investment_plan", "")
            if not trader_decision:
                trader_decision = all_reports.get(
                    "research_team_decision", "（未找到交易员计划）"
                )

        # ── 2. 获取股票信息 ─────────────────────────────────────
        ticker = state.get("company_of_interest", "Unknown")
        from app.utils.stock_utils import StockUtils
        market_info = StockUtils.get_market_info(ticker)

        company_name = resolve_company_name(ticker, market_info)
        currency = market_info["currency_name"]

        logger.info(
            f"{emoji} [{label}] 当前轮次: "
            f"{current_round_index}/{max_rounds}, 股票: {company_name}"
        )

        # ── 3. 构建 System Prompt ──────────────────────────────
        base_prompt = load_agent_config(cfg["slug"])
        if not base_prompt:
            error_msg = (
                f"❌ 未找到 {cfg['slug']} 智能体配置，"
                "请检查 phase3_agents_config.yaml 文件。"
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

        context_prefix = (
            f"股票代码：{ticker}\n"
            f"公司名称：{company_name}\n"
            f"价格单位：{currency}\n"
            "通用规则：请始终使用公司名称而不是股票代码来称呼这家公司\n"
        )
        system_prompt = context_prefix + "\n\n" + base_prompt
        messages = [SystemMessage(content=system_prompt)]

        # ── 4. 注入基础报告 ─────────────────────────────────────
        for key, content in all_reports.items():
            if content and key not in _STAGE3_REPORT_KEYS:
                display_name = (
                    key.replace("_report", "").replace("_", " ").title() + "报告"
                )
                messages.append(
                    HumanMessage(
                        content=f"=== 参考资料：{display_name} ===\n{content}"
                    )
                )

        # 注入交易员计划
        messages.append(
            HumanMessage(
                content=f"=== 交易员原始投资计划 (本次辩论焦点) ===\n{trader_decision}"
            )
        )

        # ── 5. 注入历史辩论 ─────────────────────────────────────
        if current_round_index > 0:
            logger.info(
                f"{emoji} [{label}] 注入历史辩论上下文 "
                f"(Rounds 0 to {current_round_index - 1})"
            )
            for i in range(current_round_index):
                if i >= len(rounds):
                    continue
                round_data = rounds[i]

                # 自己的历史观点 (AIMessage)
                self_content = round_data.get(cfg["round_key"])
                if self_content:
                    phase = "初始阶段" if i == 0 else f"辩论第 {i} 轮"
                    prefix = f"【回顾】这是我在【{phase}】的观点："
                    messages.append(AIMessage(content=f"{prefix}\n{self_content}"))

                # 对手的历史观点 (HumanMessage)
                for opp_key, opp_cfg in opponent_cfgs.items():
                    opp_content = round_data.get(opp_cfg["round_key"])
                    if opp_content:
                        opp_label = cfg["opponent_labels"][opp_key]
                        phase = "初始阶段" if i == 0 else f"辩论第 {i} 轮"
                        prefix = f"【回顾】{opp_label}在【{phase}】的观点："
                        messages.append(
                            HumanMessage(content=f"{prefix}\n{opp_content}")
                        )

        # ── 6. 构建 Trigger Message ────────────────────────────
        if current_round_index == 0:
            trigger_msg = cfg["trigger_initial"]
        else:
            trigger_msg = cfg["trigger_debate"].format(round=current_round_index)

        messages.append(HumanMessage(content=trigger_msg))

        # ── 7. 执行推理 ─────────────────────────────────────────
        response = llm.invoke(messages)
        content = response.content

        # 清洗内容：去除包含辩手关键字的一级标题
        keyword = cfg["filter_keyword"]
        lines = content.strip().split("\n")
        cleaned_lines = [
            line for line in lines
            if not (line.strip().startswith("# ") and keyword in line)
        ]
        content = "\n".join(cleaned_lines).strip()

        # ── 8. 更新状态 ─────────────────────────────────────────
        if current_round_index >= len(rounds):
            rounds.append({})

        rounds[current_round_index][cfg["round_key"]] = content

        # 累积报告
        if current_round_index == 0:
            section_title = cfg["section_initial"]
        else:
            section_title = cfg["section_debate"].format(round=current_round_index)

        if section_title not in report_content:
            report_content += f"\n\n{section_title}\n\n{content}"

        # ── 9. 保存文件 ─────────────────────────────────────────
        try:
            filename = build_stage3_report_path(
                state.get("task_id"),
                ticker,
                cfg["file_slug"],
            )
            tmp_filename = filename + ".tmp"
            with open(tmp_filename, "w", encoding="utf-8") as f:
                f.write(
                    cfg["file_header"].format(
                        company_name=company_name, ticker=ticker
                    )
                    + "\n\n"
                )
                f.write(f"> 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write(report_content)
            os.replace(tmp_filename, filename)
            logger.info(f"{emoji} [{label}] 已更新报告文件: {filename}")
        except Exception as e:
            logger.error(f"{emoji} [ERROR] 保存报告文件失败: {e}")

        # ── 10. 构造返回状态 ────────────────────────────────────
        if current_round_index == 0:
            argument_prefix = f"# 【{cfg['tag']} - 初始观点】"
        else:
            argument_prefix = f"# 【{cfg['tag']} - 第 {current_round_index} 轮辩论】"

        argument = f"{argument_prefix}\n{content}"

        new_risk_debate_state = dict(risk_debate_state)
        new_risk_debate_state.update({
            "rounds": rounds,
            cfg["report_state_key"]: report_content,
            cfg["history_key"]: (
                risk_debate_state.get(cfg["history_key"], "") + f"\n{argument}"
            ),
            "history": risk_debate_state.get("history", "") + f"\n{argument}",
            cfg["current_response_key"]: content,
            "count": risk_debate_state.get("count", 0) + 1,
            "current_round_index": (risk_debate_state.get("count", 0) + 1) // 3,
            "latest_speaker": cfg["speaker"],
        })

        return {
            "risk_debate_state": new_risk_debate_state,
            "reports": {cfg["report_key"]: report_content},
        }

    return debator_node
