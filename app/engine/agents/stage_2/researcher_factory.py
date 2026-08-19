"""
Stage 2 研究员工厂 — 将 bull/bear 辩手的公共逻辑参数化。

用法:
    from app.engine.agents.stage_2.researcher_factory import create_researcher

    bull_node = create_researcher(llm, memory, side="bull")
    bear_node = create_researcher(llm, memory, side="bear")

原文件 bull_researcher.py / bear_researcher.py 改为薄包装以保持向后兼容。
"""

import re
import time
from typing import Literal

from app.llm.core.types import Message, Role
from app.utils.logging_init import get_logger
from app.engine.agents.utils.agent_config import load_agent_config, resolve_company_name
from app.engine.orchestrator.invoker import run_agent_turn

logger = get_logger("default")

# Stage 2 内部报告 key — 防止同轮泄漏
_STAGE2_REPORT_KEYS = frozenset({"bull_researcher", "bear_researcher"})

# ── 辩手配置表 ──────────────────────────────────────────────────────────────

_SIDE_CONFIG = {
    "bull": {
        "slug": "bull-researcher",
        "emoji": "🐂",
        "label": "多头",
        "counterpart": "bear",
        "counterpart_label": "看跌分析师",
        "self_role_label": "核心论点",
        "counterpart_role_label": "对手（看跌分析师）",
        "round_key": "bull",
        "report_state_key": "bull_report_content",
        "history_key": "bull_history",
        "report_file_title": "看涨投资分析报告",
        "report_file_prefix": "看涨分析报告",
        "report_key": "bull_researcher",
        "speaker": "Bull Researcher",
        "argument_tag": "多头分析师",
        "section_initial": "## 初始报告：核心投资论点",
        "section_debate": "## 第 {round} 轮辩论报告：针对空方观点的反驳与辩护",
        "trigger_initial": (
            "请基于提供的基础报告，撰写你的【初始分析报告】。"
            "重点阐述核心投资论点，构建完整的逻辑框架。"
            "本阶段暂不需要反驳对手（因为辩论尚未开始）。"
        ),
        "file_header": "# {company_name} ({ticker}) 看涨投资分析报告",
    },
    "bear": {
        "slug": "bear-researcher",
        "emoji": "🐻",
        "label": "空头",
        "counterpart": "bull",
        "counterpart_label": "看涨分析师",
        "self_role_label": "风险警示",
        "counterpart_role_label": "对手（看涨分析师）",
        "round_key": "bear",
        "report_state_key": "bear_report_content",
        "history_key": "bear_history",
        "report_file_title": "看跌投资风险报告",
        "report_file_prefix": "看跌分析报告",
        "report_key": "bear_researcher",
        "speaker": "Bear Researcher",
        "argument_tag": "空头分析师",
        "section_initial": "## 初始报告：核心风险警示",
        "section_debate": "## 第 {round} 轮辩论报告：针对多方观点的质疑与反驳",
        "trigger_initial": (
            "请基于提供的基础报告，撰写你的【初始分析报告】。"
            "重点阐述核心风险警示，构建完整的逻辑框架。"
            "本阶段暂不需要反驳对手（因为辩论尚未开始）。"
        ),
        "file_header": "# {company_name} ({ticker}) 看跌投资风险报告",
    },
}



def create_researcher(llm, memory, side: Literal["bull", "bear"] = "bull"):
    """
    创建 Stage 2 研究员节点（看涨/看跌辩手）。

    Args:
        llm: LangChain LLM 实例
        memory: 金融记忆实例（目前未在辩手逻辑中使用，保留接口兼容）
        side: "bull" 或 "bear"

    Returns:
        可注册到 LangGraph 的节点函数
    """
    if side not in _SIDE_CONFIG:
        raise ValueError(f"未知的辩手方向: {side!r}，期望 'bull' 或 'bear'")

    cfg = _SIDE_CONFIG[side]
    counter_cfg = _SIDE_CONFIG[cfg["counterpart"]]
    emoji = cfg["emoji"]
    label = cfg["label"]

    async def researcher_node(state) -> dict:
        logger.debug(f"{emoji} [DEBUG] ===== {label}研究员节点开始 =====")

        investment_debate_state = state.get("investment_debate_state", {})

        try:
            # 初始化多轮状态（rounds 单一数据源，轮次/报告经派生视图读取）
            from app.engine.orchestrator.state import (
                current_round_index as calc_round_index,
                investment_report_content as view_report,
            )

            current_round_index = calc_round_index(investment_debate_state, 2)
            max_rounds = investment_debate_state.get("max_rounds", 2)
            rounds = investment_debate_state.get("rounds", [])

            # ── 1. 获取所有第一阶段基础报告 ──────────────────────────────
            from app.engine.prompts.builder import collect_reports, report_display_names

            all_reports = collect_reports(state, exclude_ids=_STAGE2_REPORT_KEYS)

            display_names = report_display_names()

            # ── 2. 获取股票信息 ─────────────────────────────────────────
            ticker = state.get("company_of_interest", "Unknown")
            from app.utils.stock_utils import StockUtils
            market_info = StockUtils.get_market_info(ticker)

            company_name = await resolve_company_name(ticker, market_info)
            currency = market_info["currency_name"]
            currency_symbol = market_info["currency_symbol"]

            logger.info(
                f"{emoji} [{label}研究员] 当前轮次: "
                f"{current_round_index}/{max_rounds}, 股票: {company_name}"
            )

            # ── 3. 构建 System Prompt ──────────────────────────────────
            base_prompt = load_agent_config(cfg["slug"])
            if not base_prompt:
                error_msg = (
                    f"❌ 未找到 {cfg['slug']} 智能体配置，"
                    "请检查 phase2_agents_config.yaml 文件。"
                )
                logger.error(error_msg)
                raise ValueError(error_msg)

            from app.engine.prompts.builder import (
                build_recall_rounds,
                build_researcher_trigger,
                context_prefix as build_context_prefix,
                inject_report_messages,
            )

            system = build_context_prefix(ticker, company_name, currency, currency_symbol) + "\n\n" + base_prompt
            messages = []

            # ── 4. 注入 Stage 1 报告（<report> 边界符包裹，防止 prompt 注入）──
            messages.extend(
                inject_report_messages(
                    all_reports, display_names,
                    header_template="这是【{name}】：",
                )
            )

            # ── 4.5 历史记忆注入（写读对称：反思写入的相似情景经验） ──
            from app.engine.agents.utils.memory import fetch_memory_brief

            memory_brief = await fetch_memory_brief(
                memory, "\n\n".join(r for r in all_reports.values() if r)
            )
            if memory_brief and not memory_brief.startswith("暂无"):
                messages.append(
                    Message(role=Role.USER, content=f"=== 历史交易反思（类似情景） ===\n{memory_brief}")
                )

            # ── 5. 注入辩论历史上下文 ──────────────────────────────────
            if current_round_index > 0:
                logger.info(
                    f"{emoji} [{label}研究员] 注入历史辩论上下文 "
                    f"(Rounds 0 to {current_round_index - 1})"
                )
                messages.extend(
                    build_recall_rounds(
                        rounds, current_round_index,
                        self_key=cfg["round_key"],
                        self_prefix_fmt=f"【回顾】这是我在【{{phase}}】建立的{cfg['self_role_label']}：",
                        opponents=[(
                            counter_cfg["round_key"],
                            f"【回顾】这是{cfg['counterpart_role_label']}在【{{phase}}】提出的观点：",
                        )],
                    )
                )

            # ── 6. 轮次触发指令 ────────────────────────────────────────
            has_counter_latest = bool(
                current_round_index > 0
                and current_round_index - 1 < len(rounds)
                and counter_cfg["round_key"] in rounds[current_round_index - 1]
            )
            trigger_msg = build_researcher_trigger(
                cfg["trigger_initial"], current_round_index, max_rounds,
                counter_latest=has_counter_latest,
            )

            # ── 7. 执行推理（统一会话循环：压缩/截断恢复/fallback/事件流）──
            content = await run_agent_turn(
                llm, messages, trigger_msg,
                system=system,
                task_id=state.get("task_id") or "",
                agent_key=f"researcher_{side}",
                phase="research",
                user_id=state.get("user_id") or "",
                event_sink=state.get("_event_sink"),
            )

            # H-2: 空响应降级 — LLM 返回空内容时使用占位文本
            if not content.strip():
                content = f"⚠️ {label}研究员本轮未能生成有效内容（LLM 返回空响应）。"
                logger.warning(f"{emoji} [{label}研究员] LLM 返回空响应，使用占位文本")

            # 清洗内容：去除一级标题和含"分析报告"的二级标题
            lines = content.strip().split("\n")
            cleaned_lines = [
                line for line in lines
                if not (
                    line.strip().startswith("# ")
                    or (line.strip().startswith("## ") and "分析报告" in line)
                )
            ]
            content = "\n".join(cleaned_lines).strip()

            # ── 8. 更新状态（rounds 单一数据源，报告内容派生）─────────
            from app.engine.orchestrator.state import append_round

            new_investment_debate_state = dict(investment_debate_state)
            append_round(new_investment_debate_state, cfg["round_key"], content, 2)
            report_content = view_report(new_investment_debate_state, side)

            # ── 9. 保存报告文件 ────────────────────────────────────────
            try:
                from app.core.config import settings
                import os
                report_dir = os.path.join(settings.runtime_dir, "results")
                os.makedirs(report_dir, exist_ok=True)
                safe_name = re.sub(r'[\\/:*?"<>|]', "_", company_name or "unknown")
                filename = os.path.join(
                    report_dir, f"{cfg['report_file_prefix']}_{safe_name}.md"
                )
                tmp_filename = filename + ".tmp"
                with open(tmp_filename, "w", encoding="utf-8") as f:
                    f.write(
                        cfg["file_header"].format(
                            company_name=company_name, ticker=ticker
                        )
                        + "\n\n"
                    )
                    f.write(f"> 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"> 货币单位：{currency}\n\n")
                    f.write(report_content)
                os.replace(tmp_filename, filename)
                logger.info(f"{emoji} [{label}研究员] 已更新报告文件: {filename}")
            except Exception as e:
                logger.error(f"{emoji} [ERROR] 保存报告文件失败: {e}")

            # ── 10. 状态返回（history/current_response 等由 export_legacy_state 派生）──

            return {
                "investment_debate_state": new_investment_debate_state,
                "reports": {cfg["report_key"]: report_content},
            }

        except Exception as e:
            logger.error(
                f"{emoji} ❌ [{label}研究员] 节点执行异常: {e}", exc_info=True
            )
            error_content = f"❌ {label}研究员节点执行失败：{e}"
            new_investment_debate_state = dict(investment_debate_state)
            new_investment_debate_state.update({
                "current_response": error_content,
                "latest_speaker": cfg["speaker"],
            })
            return {
                "investment_debate_state": new_investment_debate_state,
                "reports": {cfg["report_key"]: error_content},
            }

    return researcher_node
