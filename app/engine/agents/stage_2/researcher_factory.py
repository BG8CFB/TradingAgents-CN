"""
Stage 2 研究员工厂 — 将 bull/bear 辩手的公共逻辑参数化。

用法:
    from app.engine.agents.stage_2.researcher_factory import create_researcher

    bull_node = create_researcher(llm, memory, side="bull")
    bear_node = create_researcher(llm, memory, side="bear")

原文件 bull_researcher.py / bear_researcher.py 改为薄包装以保持向后兼容。
"""

import os
import re
import time
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.utils.logging_init import get_logger
from app.engine.agents.utils.agent_config import load_agent_config, resolve_company_name

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


def _build_report_display_names() -> dict:
    """从 DynamicAnalystFactory 配置获取报告显示名称映射。"""
    names = {}
    try:
        from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory
        for agent in DynamicAnalystFactory.get_all_agents():
            slug = agent.get("slug", "")
            name = agent.get("name", "")
            if slug and name:
                internal_key = slug.replace("-analyst", "").replace("-", "_")
                report_key = f"{internal_key}_report"
                names[report_key] = f"{name}报告"
    except Exception as e:
        logger.warning(f"⚠️ 无法从配置文件加载报告显示名称: {e}")
    return names


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

    def researcher_node(state) -> dict:
        logger.debug(f"{emoji} [DEBUG] ===== {label}研究员节点开始 =====")

        investment_debate_state = state.get("investment_debate_state", {})

        # 初始化多轮状态
        rounds = investment_debate_state.get("rounds", [])
        current_round_index = investment_debate_state.get("current_round_index", 0)
        max_rounds = investment_debate_state.get("max_rounds", 2)
        report_content = investment_debate_state.get(cfg["report_state_key"], "")

        # ── 1. 获取所有第一阶段基础报告 ──────────────────────────────
        all_reports = {}
        if "reports" in state and isinstance(state["reports"], dict):
            all_reports.update(state["reports"])
        for key, value in state.items():
            if key.endswith("_report") and value and key not in all_reports:
                all_reports[key] = value

        report_display_names = _build_report_display_names()

        # ── 2. 获取股票信息 ─────────────────────────────────────────
        ticker = state.get("company_of_interest", "Unknown")
        from app.utils.stock_utils import StockUtils
        market_info = StockUtils.get_market_info(ticker)

        company_name = resolve_company_name(ticker, market_info)
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

        context_prefix = (
            f"股票代码：{ticker}\n"
            f"公司名称：{company_name}\n"
            f"价格单位：{currency}（{currency_symbol}）\n"
            "通用规则：请始终使用公司名称而不是股票代码来称呼这家公司\n"
        )
        system_prompt = context_prefix + "\n\n" + base_prompt
        messages = [SystemMessage(content=system_prompt)]

        # ── 4. 注入 Stage 1 报告 ───────────────────────────────────
        for key, content in all_reports.items():
            if content and key not in _STAGE2_REPORT_KEYS:
                display_name = report_display_names.get(
                    key,
                    key.replace("_report", "").replace("_", " ").title() + "报告",
                )
                messages.append(
                    HumanMessage(content=f"这是【{display_name}】：\n{content}")
                )

        # ── 5. 注入辩论历史上下文 ──────────────────────────────────
        if current_round_index > 0:
            logger.info(
                f"{emoji} [{label}研究员] 注入历史辩论上下文 "
                f"(Rounds 0 to {current_round_index - 1})"
            )
            for i in range(current_round_index):
                if i >= len(rounds):
                    continue
                round_data = rounds[i]

                # 注入己方之前的观点 (AIMessage = "我"说的)
                self_content = round_data.get(cfg["round_key"])
                if self_content:
                    phase = "初始阶段" if i == 0 else f"辩论第 {i} 轮"
                    prefix = f"【回顾】这是我在【{phase}】建立的{cfg['self_role_label']}："
                    messages.append(AIMessage(content=f"{prefix}\n{self_content}"))

                # 注入对手之前的观点 (HumanMessage = 对手说的)
                counter_content = round_data.get(counter_cfg["round_key"])
                if counter_content:
                    phase = "初始阶段" if i == 0 else f"辩论第 {i} 轮"
                    prefix = (
                        f"【回顾】这是{cfg['counterpart_role_label']}"
                        f"在【{phase}】提出的观点："
                    )
                    messages.append(
                        HumanMessage(content=f"{prefix}\n{counter_content}")
                    )

        # ── 6. 轮次触发指令 ────────────────────────────────────────
        if current_round_index == 0:
            round_context = "当前分析阶段：初始观点陈述（基于第一阶段报告生成初始分析报告）"
            trigger_msg = f"{round_context}\n{cfg['trigger_initial']}"
        else:
            round_context = (
                f"当前分析阶段：辩论第 {current_round_index} 轮"
                f"（共 {max_rounds} 轮辩论）"
            )
            trigger_msg = (
                f"{round_context}\n现在是辩论第 {current_round_index} 轮。"
                "请严格按照 System Prompt 中的【任务指南】开始发言。"
            )

        if current_round_index > 0:
            prev_round_idx = current_round_index - 1
            if prev_round_idx < len(rounds) and counter_cfg["round_key"] in rounds[prev_round_idx]:
                trigger_msg += "\n请特别注意反驳对手刚刚提出的最新观点（见上文）。"

        messages.append(HumanMessage(content=trigger_msg))

        # ── 7. 执行推理 ────────────────────────────────────────────
        response = llm.invoke(messages)
        content = response.content

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

        # ── 8. 更新状态 ────────────────────────────────────────────
        if current_round_index >= len(rounds):
            rounds.append({})

        rounds[current_round_index][cfg["round_key"]] = content

        # 累积到最终报告
        if current_round_index == 0:
            section_title = cfg["section_initial"]
        else:
            section_title = cfg["section_debate"].format(round=current_round_index)

        if section_title in report_content:
            logger.warning(
                f"{emoji} [WARNING] 报告中已包含 Round {current_round_index} 内容，跳过追加。"
            )
        else:
            report_content += f"\n\n{section_title}\n\n{content}"

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

        # ── 10. 构造 argument / history ────────────────────────────
        if current_round_index == 0:
            argument_prefix = f"# 【{cfg['argument_tag']} - 初始报告】"
        else:
            argument_prefix = f"# 【{cfg['argument_tag']} - 第 {current_round_index} 轮辩论】"

        argument = f"{argument_prefix}\n{content}"

        history = investment_debate_state.get("history", "")
        self_history = investment_debate_state.get(cfg["history_key"], "")

        if argument_prefix in self_history:
            logger.warning(
                f"{emoji} [WARNING] 历史记录中已包含 Round {current_round_index}，跳过追加。"
            )
        else:
            history = history + "\n" + argument
            self_history = self_history + "\n" + argument

        new_investment_debate_state = dict(investment_debate_state)
        new_investment_debate_state.update({
            "history": history,
            cfg["history_key"]: self_history,
            "current_response": argument,
            "count": investment_debate_state.get("count", 0) + 1,
            "latest_speaker": cfg["speaker"],
            "rounds": rounds,
            cfg["report_state_key"]: report_content,
            "current_round_index": (investment_debate_state.get("count", 0) + 1) // 2,
        })

        return {
            "investment_debate_state": new_investment_debate_state,
            "reports": {cfg["report_key"]: report_content},
        }

    return researcher_node
