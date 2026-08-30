"""思考强度方言映射：canonical 档位 → 各厂家请求参数。

设计文档：docs/superpowers/specs/2026-08-30-thinking-effort-design.md
档位口径按 2026-08-30 各家官方文档校准（后续演进只改本模块）：

- OpenAI gpt-5.x/o 系    reasoning_effort: none/minimal/low/medium/high/xhigh（gpt-5.1+ 支持 none）
- DeepSeek V4            reasoning_effort: low/high/max（官方兼容映射 medium→high、xhigh→max）
- Kimi K2-thinking/K3    顶层 reasoning_effort: low/high/max（K3 始终思考不可关）
- 智谱 GLM-4.5/4.6       extra_body.thinking.type: enabled/disabled（无档位）
- 智谱 GLM-5.2+          thinking.type + effort 档位（low/high/max）；GLM-5.3 不可关闭
- 通义 Qwen（百炼）       extra_body: enable_thinking(bool) + thinking_budget(1~32768)
- Gemini 2.5/3           OpenAI 兼容层 reasoning_effort（minimal/low/medium/high）
- Anthropic 协议          thinking.budget_tokens（数值，由档位换算，见 anthropic_client._apply_thinking）

注入策略（保守）：档位未设置（None）、方言无法识别、或模型不支持对应操作
（如给不可关闭思考的模型配 off）时，一律不注入任何参数，仅记一条日志——
避免把方言参数发给不认识的网关导致 400。

方言判定：provider 名优先（收敛候选），模型名模式作能力门控（不匹配不注入）；
聚合渠道（302.AI/OpenRouter 等）的模型名保留原厂命名（如 "openai/o3"），
取 "/" 后段参与模式匹配，天然覆盖聚合场景。
"""

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# canonical 档位 → 各方言取值
_OPENAI_EFFORT = {
    "minimal": "minimal", "low": "low", "medium": "medium", "high": "high", "max": "xhigh",
}
# DeepSeek/Kimi/GLM-5 三档方言：minimal→low、medium→high（均为官方映射口径）
_TRINARY_EFFORT = {
    "minimal": "low", "low": "low", "medium": "high", "high": "high", "max": "max",
}
# Gemini thinking_level 无 max 档，极限档回落 high
_GEMINI_EFFORT = {
    "minimal": "minimal", "low": "low", "medium": "medium", "high": "high", "max": "high",
}
# Anthropic budget_tokens 换算（clamp 由 anthropic_client._apply_thinking 负责）
_ANTHROPIC_BUDGET = {
    "minimal": 1024, "low": 4096, "medium": 16384, "high": 32768, "max": 65536,
}
# Qwen thinking_budget 上限 32768（百炼官方约束），极限档与高档同值
_QWEN_BUDGET = {
    "minimal": 1024, "low": 4096, "medium": 16384, "high": 32768, "max": 32768,
}


@dataclass(frozen=True)
class _Dialect:
    """单一厂家方言：provider 名集合 + 模型能力门控模式 + 参数构建器"""
    name: str
    providers: Tuple[str, ...]
    # 能力门控：模型名（聚合渠道取 "/" 后段）不匹配则不注入——避免把思考参数
    # 发给同厂家的非思考模型（如 provider=openai 下的 gpt-4o）导致 400
    model_pattern: "re.Pattern[str]"
    builder: Any  # Callable[[str, str], Dict[str, Any]]（effort, model_suffix → params）


def _build_openai(effort: str, model: str) -> Dict[str, Any]:
    if effort == "off":
        # gpt-5.1+ 支持 reasoning_effort="none"；o1/o3/o4 系无关闭档
        if re.match(r"^gpt-5", model, re.IGNORECASE):
            return {"reasoning_effort": "none"}
        logger.info(f"[thinking] o 系模型 {model} 不支持关闭思考，本次不注入参数")
        return {}
    return {"reasoning_effort": _OPENAI_EFFORT[effort]}


def _build_trinary(effort: str, model: str) -> Dict[str, Any]:
    """DeepSeek / Kimi：顶层 reasoning_effort 三档，不支持关闭（仅思考模型）"""
    if effort == "off":
        logger.info(f"[thinking] 模型 {model} 为仅思考模型，无法关闭，本次不注入参数")
        return {}
    return {"reasoning_effort": _TRINARY_EFFORT[effort]}


def _build_glm(effort: str, model: str) -> Dict[str, Any]:
    """智谱 GLM：thinking 对象经 extra_body 传入。

    GLM-4.5/4.6 仅开关；GLM-5.2+ 增加档位（low/high/max）；GLM-5.3 起不可关闭。
    """
    m = re.match(r"^glm-(\d+)(?:\.(\d+))?", model, re.IGNORECASE)
    major = int(m.group(1)) if m else 0
    minor = int(m.group(2) or 0) if m else 0
    if effort == "off":
        if major >= 5 and minor >= 3:
            logger.info(f"[thinking] {model} 不支持关闭思考，本次不注入参数")
            return {}
        return {"extra_body": {"thinking": {"type": "disabled"}}}
    if major >= 5 and minor >= 2:
        return {"extra_body": {"thinking": {"type": "enabled", "effort": _TRINARY_EFFORT[effort]}}}
    # GLM-4.5/4.6 无档位，仅开/关
    return {"extra_body": {"thinking": {"type": "enabled"}}}


def _build_qwen(effort: str, model: str) -> Dict[str, Any]:
    """通义 Qwen（百炼 OpenAI 兼容）：enable_thinking + thinking_budget 经 extra_body"""
    if effort == "off":
        # 仅思考模式模型（qwen3-*-thinking-* / deepseek-r1 经百炼托管）无法关闭
        if re.search(r"(thinking|r1)", model, re.IGNORECASE):
            logger.info(f"[thinking] {model} 为仅思考模型，无法关闭，本次不注入参数")
            return {}
        return {"extra_body": {"enable_thinking": False}}
    return {"extra_body": {"enable_thinking": True, "thinking_budget": _QWEN_BUDGET[effort]}}


def _build_gemini(effort: str, model: str) -> Dict[str, Any]:
    if effort == "off":
        logger.info("[thinking] Gemini 不支持经兼容层关闭思考，本次不注入参数")
        return {}
    return {"reasoning_effort": _GEMINI_EFFORT[effort]}


_DIALECTS: Tuple[_Dialect, ...] = (
    _Dialect(
        name="openai",
        providers=("openai",),
        model_pattern=re.compile(r"^(o[134](-mini|-preview)?\b|gpt-5)", re.IGNORECASE),
        builder=_build_openai,
    ),
    _Dialect(
        name="deepseek",
        providers=("deepseek",),
        # V3.1 起混合思考；V4 系支持 reasoning_effort。旧 deepseek-chat(V3) 不注入
        model_pattern=re.compile(r"deepseek-(v4|v3\.[12]|r1|reasoner)", re.IGNORECASE),
        builder=_build_trinary,
    ),
    _Dialect(
        name="kimi",
        providers=("moonshot", "kimi"),
        model_pattern=re.compile(r"kimi", re.IGNORECASE),
        builder=_build_trinary,
    ),
    _Dialect(
        name="glm",
        providers=("zhipu", "glm", "bigmodel", "chatglm"),
        # thinking 参数自 GLM-4.5 引入；glm-4-flash/4-air 等旧模型不注入
        model_pattern=re.compile(r"^glm-(4\.[5-9]\d*|5)", re.IGNORECASE),
        builder=_build_glm,
    ),
    _Dialect(
        name="qwen",
        providers=("qwen", "dashscope", "alibaba", "tongyi"),
        model_pattern=re.compile(r"^(qwen|qwq)", re.IGNORECASE),
        builder=_build_qwen,
    ),
    _Dialect(
        name="gemini",
        providers=("gemini", "google"),
        # 2.5 系起支持思考控制
        model_pattern=re.compile(r"^gemini-(2\.5|3)", re.IGNORECASE),
        builder=_build_gemini,
    ),
)


def _lookup_model(model: str) -> str:
    """聚合渠道模型名（如 "openai/o3"、"zhipu/glm-5.3"）取 "/" 后段参与匹配"""
    return (model or "").split("/")[-1].strip()


def detect_dialect(provider: Optional[str], model: str) -> Optional[_Dialect]:
    """方言判定：provider 名收敛候选，模型模式作能力门控；无匹配返回 None。"""
    lookup = _lookup_model(model)
    prov = (provider or "").strip().lower()
    for dialect in _DIALECTS:
        if prov and prov in dialect.providers:
            return dialect if dialect.model_pattern.search(lookup) else None
    # 聚合渠道/自定义厂家：纯模型名模式识别
    for dialect in _DIALECTS:
        if dialect.model_pattern.search(lookup):
            return dialect
    return None


def resolve_anthropic_thinking_budget(
    effort: Optional[str], explicit_budget: Optional[int]
) -> Optional[int]:
    """Anthropic 协议：档位/显式预算 → thinking budget token 数。

    优先级：显式 thinking_budget（表单「思考预算」，>0 生效）> 档位换算。
    返回 None 表示不开启（off 与未设置在 Anthropic 侧等价，思考本就是 opt-in）。
    """
    if explicit_budget and explicit_budget > 0:
        return explicit_budget
    return _ANTHROPIC_BUDGET.get(effort or "")


def build_openai_thinking_params(
    provider: Optional[str], model: str, effort: Optional[str]
) -> Dict[str, Any]:
    """OpenAI 兼容协议：canonical 档位 → 请求参数（可能含 extra_body）。

    返回 {} 表示不注入。返回结构约定：顶层键为 openai SDK 一等参数
    （reasoning_effort），"extra_body" 键为非标准方言参数（百炼/智谱）。
    """
    if not effort:
        return {}
    dialect = detect_dialect(provider, model)
    if dialect is None:
        logger.info(
            f"[thinking] 模型 {model}（provider={provider or '未知'}）未匹配思考方言，"
            f"档位 {effort} 不注入参数"
        )
        return {}
    return dialect.builder(effort, _lookup_model(model))


def merge_openai_thinking_params(
    params: Dict[str, Any],
    kwargs: Dict[str, Any],
    *,
    provider: Optional[str],
    model: str,
    effort: Optional[str],
) -> None:
    """把 build_openai_thinking_params 的结果合并进请求参数。

    extra_body 与调用方可能传入的 extra_body 合并（不覆盖）；其余键并入 params。
    openai 客户端的 chat / chat_stream 在 params.update(kwargs) 之前调用。
    """
    thinking = build_openai_thinking_params(provider, model, effort)
    if not thinking:
        return
    extra_body = thinking.pop("extra_body", None)
    if extra_body:
        merged = {**(kwargs.get("extra_body") or {}), **extra_body}
        kwargs["extra_body"] = merged
    params.update(thinking)
