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

from app.llm.core.types import Message, Role

import logging
from app.engine.orchestrator.invoker import run_node_turn
from app.engine.agents.utils.agent_config import (
    build_stage3_report_path,
    load_agent_config,
    resolve_company_name,
)

logger = logging.getLogger("default")

# 消费集声明化（P3 §4.6）：基础报告 = 工作流 stage.inputs 的 analyst_reports 槽、
# 交易员计划 = trader_plan field 槽（executor 阶段开始快照；黑名单动态收集已退役）


def _stage_inputs(state) -> dict:
    """本阶段输入槽快照（analyst_reports / trader_plan）"""
    return state.get("_stage_inputs") or {}


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
        "trigger_debate_stance": "请直接反驳他们的担忧，坚持你的高风险高回报逻辑。",
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
        "trigger_debate_stance": "请直接反驳他们的乐观假设，坚持你的风险控制逻辑。",
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
        "trigger_debate_stance": "请调和双方矛盾，提出更合理的平衡方案。",
    },
}


def create_debator(llm, side: Literal["risky", "safe", "neutral"] = "risky", *, group=None):
    """
    创建 Stage 3 风险辩论节点。

    Args:
        llm: LLM 客户端实例
        side: "risky"、"safe" 或 "neutral"
        group: 辩论组拓扑上下文（P4-a N 方泛化，orchestrator.workflow.debate.DebateGroup）。
            缺省 None = 内置三方行为（per_turn=3 / risk_debate_state / risk 视图）；
            传入时 per_turn = len(sides)、state_key / 报告视图 / 对手集合按组拓扑驱动，
            内置对手的文案仍查本表（与缺省路径逐字一致）

    Returns:
        节点执行函数
    """
    if side not in _SIDE_CONFIG:
        raise ValueError(f"未知的辩手方向: {side!r}，期望 'risky'、'safe' 或 'neutral'")

    cfg = _SIDE_CONFIG[side]
    emoji = cfg["emoji"]
    label = cfg["label"]

    # 组拓扑参数（group 缺省 = 内置三方硬编码值，两条路径行为等价）
    state_key = group.state_key if group is not None else "risk_debate_state"
    per_turn = group.per_turn if group is not None else 3

    # 对手元数据（固定侧序）：内置侧查表（措辞逐字一致），自定义侧用组内显示标签
    if group is not None:
        opponent_pairs = group.opponents_of(cfg["round_key"])
    else:
        opponent_pairs = [(opp, _SIDE_CONFIG[opp]["tag"]) for opp in cfg["opponents"]]

    def _opp_tag(opp_key: str, fallback_label: str) -> str:
        return _SIDE_CONFIG[opp_key]["tag"] if opp_key in _SIDE_CONFIG else fallback_label

    # 历史注入对手列表 + 触发语对手名单（「和」连接，内置三方文案逐字一致）
    opponents = [
        (opp_key, f"【回顾】{_opp_tag(opp_key, opp_label)}在【{{phase}}】的观点：")
        for opp_key, opp_label in opponent_pairs
    ]
    opp_names = "和".join(_opp_tag(k, lbl) for k, lbl in opponent_pairs)

    async def debator_node(state) -> dict:
        logger.debug(f"{emoji} [DEBUG] ===== {label}节点开始 =====")

        risk_debate_state = state.get(state_key, {})
        # 预取降级返回所需的基础值（在 try 外部，确保 except 也能安全使用）
        from app.engine.orchestrator.state import (
            append_round,
            current_round_index as calc_round_index,
        )

        if group is not None:
            view_report = group.report_view
        else:
            from app.engine.orchestrator.state import risk_report_content as view_report

        current_round_index = calc_round_index(risk_debate_state, per_turn)

        try:
            # 初始化多轮状态（rounds 单一数据源，报告经派生视图读取）
            max_rounds = risk_debate_state.get("max_rounds", 3)
            rounds = risk_debate_state.get("rounds", [])

            # ── 1. 获取基础报告与交易员计划（stage.inputs 声明化消费）────
            from app.engine.prompts.builder import (
                build_recall_rounds,
                context_prefix as build_context_prefix,
                inject_report_messages,
            )

            inputs_snapshot = _stage_inputs(state)
            all_reports = inputs_snapshot.get("analyst_reports") or {}
            trader_decision = inputs_snapshot.get("trader_plan") or "（未找到交易员计划）"

            # ── 2. 获取股票信息 ─────────────────────────────────────
            ticker = state.get("company_of_interest", "Unknown")
            from app.utils.stock_utils import StockUtils

            market_info = StockUtils.get_market_info(ticker)

            company_name = await resolve_company_name(ticker, market_info)
            currency = market_info["currency_name"]

            logger.info(f"{emoji} [{label}] 当前轮次: {current_round_index}/{max_rounds}, 股票: {company_name}")

            # ── 3. 构建 System Prompt ──────────────────────────────
            base_prompt = load_agent_config(cfg["slug"])
            if not base_prompt:
                error_msg = f"❌ 未找到 {cfg['slug']} 智能体配置，请检查 agent_specs 智能体库（DB）。"
                logger.error(error_msg)
                raise ValueError(error_msg)

            system = build_context_prefix(ticker, company_name, currency) + "\n\n" + base_prompt
            messages = inject_report_messages(
                all_reports,
                {},
                header_template="=== 参考资料：{name} ===",
            )

            # 注入交易员计划
            messages.append(
                Message(
                    role=Role.USER,
                    content=f"=== 交易员原始投资计划 (本次辩论焦点) ===\n<report>\n{trader_decision}\n</report>",
                )
            )

            # ── 5. 注入历史辩论 ─────────────────────────────────────
            if current_round_index > 0:
                logger.info(f"{emoji} [{label}] 注入历史辩论上下文 (Rounds 0 to {current_round_index - 1})")
                messages.extend(
                    build_recall_rounds(
                        rounds,
                        current_round_index,
                        self_key=cfg["round_key"],
                        self_prefix_fmt="【回顾】这是我在【{phase}】的观点：",
                        opponents=opponents,
                    )
                )

            # ── 6. 构建 Trigger Message（对手名单动态构造，N 方泛化）──
            if current_round_index == 0:
                trigger_msg = cfg["trigger_initial"]
            else:
                trigger_msg = (
                    f"当前阶段：Round {current_round_index} 辩论。\n"
                    f"请阅读上方对手（{opp_names}）在上一轮的观点。" + cfg["trigger_debate_stance"]
                )

            # ── 7. 执行推理（统一会话循环 + submit_report 提交协议）──
            #    debater 工具白名单 = 仅 submit_report；提交内容落 rounds[side]
            submission = await run_node_turn(
                llm,
                messages,
                trigger_msg,
                system=system,
                node_type="debater",
                task_id=state.get("task_id") or "",
                agent_key=f"risk_debater_{side}",
                phase=group.event_phase if group is not None else "risk",
                user_id=state.get("user_id") or "",
                event_sink=state.get("_event_sink"),
            )
            content = submission.content

            # H-2: 空响应降级 — LLM 返回空内容时使用占位文本
            if not content.strip():
                content = f"⚠️ {label}本轮未能生成有效内容（LLM 返回空响应）。"
                logger.warning(f"{emoji} [{label}] LLM 返回空响应，使用占位文本")

            # 清洗内容：去除包含辩手关键字的一级标题
            keyword = cfg["filter_keyword"]
            lines = content.strip().split("\n")
            cleaned_lines = [line for line in lines if not (line.strip().startswith("# ") and keyword in line)]
            content = "\n".join(cleaned_lines).strip()

            # ── 8. 更新状态（rounds 单一数据源，报告内容派生）─────────
            new_risk_debate_state = dict(risk_debate_state)
            append_round(new_risk_debate_state, cfg["round_key"], content, per_turn)
            report_content = view_report(new_risk_debate_state, side)

            # ── 9. 保存文件 ─────────────────────────────────────────
            try:
                filename = build_stage3_report_path(
                    state.get("task_id"),
                    ticker,
                    cfg["file_slug"],
                )
                tmp_filename = filename + ".tmp"
                with open(tmp_filename, "w", encoding="utf-8") as f:
                    f.write(cfg["file_header"].format(company_name=company_name, ticker=ticker) + "\n\n")
                    f.write(f"> 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                    f.write(report_content)
                os.replace(tmp_filename, filename)
                logger.info(f"{emoji} [{label}] 已更新报告文件: {filename}")
            except Exception as e:
                logger.error(f"{emoji} [ERROR] 保存报告文件失败: {e}")

            # ── 10. 构造返回状态（history/current_* 等由 export_legacy_state 派生）──
            new_risk_debate_state["latest_speaker"] = cfg["speaker"]

            return {
                state_key: new_risk_debate_state,
                "reports": {cfg["report_key"]: report_content},
            }

        except Exception:
            logger.error(
                f"{emoji} [{label}] 节点执行异常，降级返回以保持流程继续",
                exc_info=True,
            )
            # 降级状态：count 仍递增（append_round 内完成），降级内容也入 rounds，
            # 报告/历史由派生视图统一重建
            fallback_content = f"⚠️ {label}节点本轮执行异常，未能生成有效辩论内容。"
            new_risk_debate_state = dict(risk_debate_state)
            append_round(new_risk_debate_state, cfg["round_key"], fallback_content, per_turn)
            new_risk_debate_state["latest_speaker"] = cfg["speaker"]
            return {
                state_key: new_risk_debate_state,
                "reports": {cfg["report_key"]: fallback_content},
            }

    return debator_node
