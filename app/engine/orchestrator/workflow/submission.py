"""submit_report 提交协议（P3，设计文档 §4.6b/§4.7）——替代「取最后一轮回复」。

现状报告 = result.final_text 隐式截取、机器可解析输出靠提示词约定 + 解析兜底；
改为显式工具提交：参数天然带 schema 校验，机器可解析链从提示词约定升级为
API 级强制。

- 每个节点装配唯一必然工具 submit_report：content（markdown 正文）+ 按节点
  type 的结构化字段（§4.7 表）；schema 校验失败 = 工具报错返回模型重试
  （bounded，计入 max_turns）
- SubmissionBox 捕获模式：工具 handler 闭包写 box → 节点装配层把工具传入
  run_conversation → 会话结束后 finalize_submission 取提交（模型未调用 →
  final_text 降级，标记 fallback_text）
- 写入路径：commit_submission 统一「写黑板 reports + 发 report_ready（携带
  submission 来源标记）」——structured 在工具调用即时触发（报告 tab 精确
  锚点，不再依赖会话结束推断），fallback_text 在会话结束降级后触发；
  debater 例外不写黑板（提交内容落 rounds[side]，由辩论组管理，见 §4.2 类型表）
- judge 的 judge_decision 不收独立参数：现状三处落点（judge_decision /
  investment_plan / reports.research_team_decision）均为同一全文，schema 仅收
  content、落点映射在节点装配层——避免模型重复誊写全文导致三处漂移
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.llm.core.types import ToolDef

logger = logging.getLogger("orchestrator.workflow.submission")

SUBMISSION_STRUCTURED = "structured"
SUBMISSION_FALLBACK = "fallback_text"

TOOL_NAME = "submit_report"

# trader/terminal 的 action 规范值（SignalProcessor 消费的中文枚举为 canonical）
_ACTION_CANONICAL = ("买入", "持有", "卖出")
_ACTION_ALIASES = {
    "buy": "买入",
    "sell": "卖出",
    "hold": "持有",
    "买入": "买入",
    "卖出": "卖出",
    "持有": "持有",
    "购买": "买入",
    "出售": "卖出",
    "观望": "持有",
    "维持": "持有",
    "清仓": "卖出",
    "加仓": "买入",
    "建仓": "买入",
}

# summarizer 的 final_signal 规范值（structured_summary 契约为英文枚举）
_SIGNAL_CANONICAL = ("Buy", "Hold", "Sell")
_SIGNAL_ALIASES = {
    "buy": "Buy",
    "hold": "Hold",
    "sell": "Sell",
    "买入": "Buy",
    "持有": "Hold",
    "卖出": "Sell",
}

# 支持 schema 构建的节点类型（未知类型在工厂入口拒绝）
SUPPORTED_NODE_TYPES = ("analyst", "debater", "judge", "trader", "summarizer", "terminal")


class SubmissionError(ValueError):
    """提交校验失败（工具层转错误字符串返回模型重试，计入 max_turns）"""


@dataclass
class Submission:
    """一次报告提交（content + 按 type 的结构化字段 + 提交来源标记）"""

    content: str
    fields: Dict[str, Any] = field(default_factory=dict)
    source: str = SUBMISSION_STRUCTURED


@dataclass
class SubmissionBox:
    """提交捕获盒（工具 handler 与节点装配层之间的传递载体）"""

    value: Optional[Submission] = None

    def set(self, submission: Submission) -> None:
        if self.value is not None:
            raise SubmissionError("报告已提交，请勿重复提交；请简短收尾并结束回复。")
        self.value = submission


# ── 枚举/数值规范化 ────────────────────────────────────────────────────────


def _normalize_enum(value: Any, aliases: Dict[str, str], canonical: tuple, label: str) -> str:
    """枚举字段规范化：别名映射 → canonical；缺失/未识别抛 SubmissionError"""
    if not isinstance(value, str) or value.strip().lower() not in aliases:
        raise SubmissionError(f"参数 {label} 必须是 {'/'.join(canonical)} 之一（收到: {value!r}），请修正后重新提交")
    return aliases[value.strip().lower()]


def _coerce_number(value: Any, label: str) -> float:
    """数值字段宽容转换（数字或数字字符串）；失败抛 SubmissionError"""
    if isinstance(value, bool) or value is None:
        raise SubmissionError(f"参数 {label} 必须是数字（收到: {value!r}）")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise SubmissionError(f"参数 {label} 必须是数字（收到: {value!r}）") from None


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# ── type × schema（§4.7 表：结构化输出契约从提示词迁移为工具参数 schema）────


_CONTENT_PROP: Dict[str, Any] = {
    "type": "string",
    "description": "完整报告 markdown 正文（人类可读的最终交付内容，先写正文再提交）",
}

_DECISION_PROPS: Dict[str, Any] = {
    "action": {
        "type": "string",
        "enum": list(_ACTION_CANONICAL),
        "description": "投资动作（买入/持有/卖出，必填）",
    },
    "target_price": {
        "type": "number",
        "description": "目标价（本币计价的具体数值；报告中未给出则省略）",
    },
    "confidence": {
        "type": "number",
        "description": "决策信心 0-1（未明确提及可省略）",
    },
    "risk_score": {
        "type": "number",
        "description": "风险评分 0-1（未明确提及可省略）",
    },
    "reasoning": {
        "type": "string",
        "description": "决策主要理由的一句话摘要",
    },
}

# summarizer：structured_summary 的 7 个结构化字段（+ content 共 8 参数）
_SUMMARIZER_PROPS: Dict[str, Any] = {
    "key_indicators": {
        "type": "object",
        "description": "关键点位（entry_price/target_price/stop_loss/support_level/resistance_level，值为字符串）",
    },
    "model_confidence": {
        "type": "number",
        "description": "模型信心 0-100",
    },
    "risk_assessment": {
        "type": "object",
        "description": "风险评估（level/score/description）",
    },
    "analysis_summary": {
        "type": "string",
        "description": "分析摘要（纯文本）",
    },
    "investment_recommendation": {
        "type": "string",
        "description": "投资建议（纯文本）",
    },
    "analysis_reference": {
        "type": "array",
        "items": {"type": "string"},
        "description": "分析依据条目列表",
    },
    "final_signal": {
        "type": "string",
        "enum": list(_SIGNAL_CANONICAL),
        "description": "最终信号（Buy/Hold/Sell）",
    },
}

_SUMMARIZER_REQUIRED = (
    "key_indicators",
    "model_confidence",
    "risk_assessment",
    "analysis_summary",
    "investment_recommendation",
    "final_signal",
)

# 各 type 的结构化附加参数（analyst/debater/judge 仅 content，见模块 docstring）
_TYPE_EXTRA_PROPS: Dict[str, Dict[str, Any]] = {
    "analyst": {},
    "debater": {},
    "judge": {},
    "trader": _DECISION_PROPS,
    "terminal": _DECISION_PROPS,
    "summarizer": _SUMMARIZER_PROPS,
}

# 各 type 的必填附加参数
_TYPE_EXTRA_REQUIRED: Dict[str, List[str]] = {
    "analyst": [],
    "debater": [],
    "judge": [],
    "trader": ["action"],
    "terminal": ["action"],
    "summarizer": list(_SUMMARIZER_REQUIRED),
}


def build_params_schema(node_type: str) -> Dict[str, Any]:
    """节点 type → submit_report 参数 JSON Schema（协议层强校验的一手来源）"""
    if node_type not in SUPPORTED_NODE_TYPES:
        raise SubmissionError(f"未知节点类型: {node_type!r}（支持: {SUPPORTED_NODE_TYPES}）")
    props: Dict[str, Any] = {"content": _CONTENT_PROP}
    props.update(_TYPE_EXTRA_PROPS[node_type])
    return {
        "type": "object",
        "properties": props,
        "required": ["content", *_TYPE_EXTRA_REQUIRED[node_type]],
    }


def build_tool_description(node_type: str) -> str:
    """节点 type → 工具描述（提交规范契约段：唯一提交入口 + 收尾约束）"""
    extra_hint = {
        "trader": "，并填写结构化决策参数（action 必填）",
        "terminal": "，并填写最终决策参数（action 必填）",
        "summarizer": "，并填写全部结构化总结字段",
    }.get(node_type, "")
    return (
        "提交你的最终产出（唯一提交入口；提交即定稿，不要再用其他方式输出结论）。"
        f"content 为完整报告 markdown 正文{extra_hint}。"
        "提交成功后简短收尾并结束回复，不要重复报告内容。"
    )


# ── 提交校验（handler 内同步执行；失败 → SubmissionError → 模型有界重试）────


def validate_submission(node_type: str, content: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """按 type 校验并规范化结构化字段，返回规范化结果（不修改 content）。

    required 缺失 / 枚举非法 / 数值不可解析 → SubmissionError（错误信息面向模型，
    指明修正方向）；数值越界做宽容裁剪（与 SignalProcessor/summary 现状一致）。
    """
    if not isinstance(content, str) or not content.strip():
        raise SubmissionError("缺少必填参数 content（完整报告 markdown 正文）")
    if node_type in ("analyst", "debater", "judge"):
        return {}
    if node_type in ("trader", "terminal"):
        normalized: Dict[str, Any] = {
            "action": _normalize_enum(fields.get("action"), _ACTION_ALIASES, _ACTION_CANONICAL, "action")
        }
        if fields.get("target_price") is not None:
            normalized["target_price"] = _coerce_number(fields["target_price"], "target_price")
        if fields.get("confidence") is not None:
            normalized["confidence"] = _clamp(_coerce_number(fields["confidence"], "confidence"), 0.0, 1.0)
        if fields.get("risk_score") is not None:
            normalized["risk_score"] = _clamp(_coerce_number(fields["risk_score"], "risk_score"), 0.0, 1.0)
        if fields.get("reasoning") is not None:
            normalized["reasoning"] = str(fields["reasoning"])
        return normalized
    if node_type == "summarizer":
        missing = [k for k in _SUMMARIZER_REQUIRED if fields.get(k) is None]
        if missing:
            raise SubmissionError(f"结构化总结缺少必填字段: {', '.join(missing)}，请补齐后重新提交")
        if not isinstance(fields["key_indicators"], dict):
            raise SubmissionError("key_indicators 必须是对象（点位键值）")
        if not isinstance(fields["risk_assessment"], dict):
            raise SubmissionError("risk_assessment 必须是对象（level/score/description）")
        normalized = {
            "key_indicators": fields["key_indicators"],
            "model_confidence": _clamp(_coerce_number(fields["model_confidence"], "model_confidence"), 0, 100),
            "risk_assessment": fields["risk_assessment"],
            "analysis_summary": str(fields["analysis_summary"]),
            "investment_recommendation": str(fields["investment_recommendation"]),
            "final_signal": _normalize_enum(fields["final_signal"], _SIGNAL_ALIASES, _SIGNAL_CANONICAL, "final_signal"),
        }
        reference = fields.get("analysis_reference")
        if reference is not None:
            if not isinstance(reference, list):
                raise SubmissionError("analysis_reference 必须是字符串数组")
            normalized["analysis_reference"] = [str(item) for item in reference]
        return normalized
    raise SubmissionError(f"未知节点类型: {node_type!r}（支持: {SUPPORTED_NODE_TYPES}）")


# ── 写入路径（structured 即时 / fallback 会话结束，共用单条路径）───────────


async def commit_submission(
    submission: Submission,
    *,
    state: Optional[Dict[str, Any]],
    report_key: str,
    event_sink: Optional[Any],
    agent_key: str = "",
    phase: str = "",
    display_name: str = "",
) -> None:
    """提交落黑板 + 发 report_ready（携带 submission 来源标记）。

    report_key 为空（debater 例外）时不写黑板不发事件——提交内容由辩论组
    rounds[side] 管理。事件发射失败不阻断节点（与 pipeline._emit_report_ready
    同语义）；merge 侧 diff 发射因黑板已有同值内容而自然跳过，不会双发。
    """
    if not report_key:
        return
    if state is not None:
        state.setdefault("reports", {})[report_key] = submission.content
    if event_sink is None:
        return
    try:
        from app.engine.orchestrator import registry
        from app.llm.events import REPORT_CONTENT_MAX_CHARS

        await event_sink.emit(
            "report_ready",
            agent_key=agent_key,
            phase=phase,
            report_key=report_key,
            title=registry.report_title(report_key, display_name),
            content=submission.content[:REPORT_CONTENT_MAX_CHARS],
            submission=submission.source,
        )
    except Exception as e:  # noqa: BLE001 - 事件失败不阻断提交
        logger.warning(f"⚠️ [submission] report_ready 发射失败: {e}")


def make_submit_report_tool(
    box: SubmissionBox,
    *,
    node_type: str,
    report_key: str = "",
    state: Optional[Dict[str, Any]] = None,
    event_sink: Optional[Any] = None,
    agent_key: str = "",
    phase: str = "",
    display_name: str = "",
) -> ToolDef:
    """构造节点的 submit_report 工具（SubmissionBox 模式：handler 闭包捕获上下文）。

    Args:
        box: 提交捕获盒（节点装配层创建，会话结束后 finalize 取值）
        node_type: 决定参数 schema 与校验规则（SUPPORTED_NODE_TYPES 之一）
        report_key: 主输出报告键；空 = 不写黑板（debater 例外模式）
        state / event_sink / agent_key / phase / display_name: 黑板与事件上下文
    """
    if node_type not in SUPPORTED_NODE_TYPES:
        raise SubmissionError(f"未知节点类型: {node_type!r}（支持: {SUPPORTED_NODE_TYPES}）")

    async def handler(**input: Any) -> str:
        fields = {k: v for k, v in input.items() if k != "content"}
        normalized = validate_submission(node_type, input.get("content"), fields)
        box.set(Submission(content=input["content"].strip(), fields=normalized, source=SUBMISSION_STRUCTURED))
        await commit_submission(
            box.value,
            state=state,
            report_key=report_key,
            event_sink=event_sink,
            agent_key=agent_key,
            phase=phase,
            display_name=display_name,
        )
        return "✅ 已收到报告提交。请简短收尾并结束本轮回复，不要重复报告内容。"

    return ToolDef(
        name=TOOL_NAME,
        description=build_tool_description(node_type),
        params_schema=build_params_schema(node_type),
        handler=handler,
        is_concurrency_safe=False,
    )


def finalize_submission(
    box: SubmissionBox,
    *,
    final_text: str = "",
    fallback_fields: Optional[Dict[str, Any]] = None,
) -> Submission:
    """会话结束后取提交：模型已提交 → 原样返回；未调用 → final_text 降级。

    降级路径（可靠性保证，§4.6b）：content = final_text，结构化字段回退
    调用方传入的文本解析结果（SignalProcessor / summary JSON 提取），
    标记 fallback_text。
    """
    if box.value is not None:
        return box.value
    return Submission(
        content=(final_text or "").strip(),
        fields=dict(fallback_fields or {}),
        source=SUBMISSION_FALLBACK,
    )
