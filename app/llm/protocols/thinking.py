"""思考强度方言映射：canonical 档位 → 各厂家/推理框架请求参数。

设计文档：docs/superpowers/specs/2026-08-30-thinking-effort-design.md
适配范围按 2026-08-31 用户决策收敛为六类（实测 + 官方文档双口径）：

- OpenAI 官方（gpt-5.x/o 系）  reasoning_effort: none/minimal/low/medium/high/xhigh
- DeepSeek V4+                 reasoning_effort: low/high/max（官方兼容映射 medium→high、xhigh→max）
- Anthropic 协议               thinking.budget_tokens（数值换算，见 anthropic_client._apply_thinking）
- vLLM                         chat_template_kwargs.reasoning_effort + enable_thinking=false 关闭
                              + 顶层 thinking_token_budget 硬预算（2026-08-31 NAS 网关实测：
                              10→18/30→88/200→198 字思考，剂量响应完美）
- llama.cpp（llama-server）     同 vLLM 的 chat_template_kwargs 形状（--jinja 透传进模型模板）
- Ollama /v1                   顶层 reasoning_effort: low/medium/high（官方源码 openai.go 仅映射
                              三档；无关闭、无预算）

百炼/智谱/Kimi/Gemini 方言已按用户决策移除（2026-08-31），需要时按本模块模式重新接入。

框架方言（vllm/llamacpp/ollama）以 provider 名为准、不做模型名门控——框架决定参数形状，
档位合法值由模型自带 chat template 校验。例外是 Qwen3.8：模板只收 low/medium/xhigh，
发 high 直接 400（实测 + HF Qwen3.8-27B #113），故按模型名把 high/max 映射到 xhigh。

注入策略（保守）：档位未设置（None）、方言无法识别、或目标不支持对应操作
（如给 Ollama 配 off）时，一律不注入任何参数，仅记一条日志——避免把方言
参数发给不认识的网关导致 400。

方言判定：provider 名优先（收敛候选；框架方言不参与模型名兜底，
否则 match-all 会吞掉所有未知模型），模型名模式作能力门控（不匹配不注入）；
聚合渠道（302.AI/OpenRouter 等）的模型名保留原厂命名（如 "openai/o3"），
取 "/" 后段参与模式匹配。
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
# DeepSeek 三档方言：minimal→low、medium→high（官方兼容映射口径）
_TRINARY_EFFORT = {
    "minimal": "low", "low": "low", "medium": "high", "high": "high", "max": "max",
}
# chat_template_kwargs 档位（vLLM/llama.cpp 通用模板口径，多数模板收 low/medium/high）
_CTK_EFFORT = {
    "minimal": "low", "low": "low", "medium": "medium", "high": "high", "max": "high",
}
# Qwen3.8 模板只收 low/medium/xhigh（high 会 400），high/max 归一到 xhigh
_CTK_EFFORT_QWEN38 = {
    "minimal": "low", "low": "low", "medium": "medium", "high": "xhigh", "max": "xhigh",
}
# Ollama /v1 兼容层仅映射三档（官方源码 openai.go: high/medium/low → ThinkValue）
_OLLAMA_EFFORT = {
    "minimal": "low", "low": "low", "medium": "medium", "high": "high", "max": "high",
}
# Anthropic budget_tokens 换算（clamp 由 anthropic_client._apply_thinking 负责）
_ANTHROPIC_BUDGET = {
    "minimal": 1024, "low": 4096, "medium": 16384, "high": 32768, "max": 65536,
}

# Qwen3.8 系模型名（含聚合渠道 "Qwen/Qwen3.8-27B" 后段匹配）
_QWEN38_PATTERN = re.compile(r"qwen\s*3\.8", re.IGNORECASE)


@dataclass(frozen=True)
class _Dialect:
    """单一方言：provider 名集合 + 模型能力门控模式 + 参数构建器。

    model_pattern 为 None 表示框架方言（vllm/llamacpp/ollama）：以 provider 名
    唯一判定，不做模型门控，也不参与模型名兜底识别（match-all 会误吞一切）。
    """
    name: str
    providers: Tuple[str, ...]
    # 能力门控：模型名（聚合渠道取 "/" 后段）不匹配则不注入——避免把思考参数
    # 发给同厂家的非思考模型（如 provider=openai 下的 gpt-4o）导致 400
    model_pattern: Optional["re.Pattern[str]"]
    builder: Any  # Callable[[str, str, Optional[int]], Dict]（effort, model, budget → params）


def _build_openai(effort: str, model: str, budget: Optional[int]) -> Dict[str, Any]:
    if effort == "off":
        # gpt-5.1+ 支持 reasoning_effort="none"；o1/o3/o4 系无关闭档
        if re.match(r"^gpt-5", model, re.IGNORECASE):
            return {"reasoning_effort": "none"}
        logger.info(f"[thinking] o 系模型 {model} 不支持关闭思考，本次不注入参数")
        return {}
    return {"reasoning_effort": _OPENAI_EFFORT[effort]}


def _build_trinary(effort: str, model: str, budget: Optional[int]) -> Dict[str, Any]:
    """DeepSeek：顶层 reasoning_effort 三档，不支持关闭（仅思考模型）"""
    if effort == "off":
        logger.info(f"[thinking] 模型 {model} 为仅思考模型，无法关闭，本次不注入参数")
        return {}
    return {"reasoning_effort": _TRINARY_EFFORT[effort]}


def _ctk_effort_value(effort: str, model: str) -> str:
    """框架档位取值：Qwen3.8 模板限 low/medium/xhigh，其余模板按通用口径"""
    table = _CTK_EFFORT_QWEN38 if _QWEN38_PATTERN.search(model) else _CTK_EFFORT
    return table[effort]


def _build_vllm(effort: str, model: str, budget: Optional[int]) -> Dict[str, Any]:
    """vLLM：档位/开关经 chat_template_kwargs 进模型模板，预算走顶层采样参数。

    实测（2026-08-31，vLLM + Qwen3.8-27B）：enable_thinking=false 思考归零；
    reasoning_effort 档位是软倾向；thinking_token_budget 是唯一确定性硬上限。
    """
    ctk: Dict[str, Any] = {}
    if effort == "off":
        ctk["enable_thinking"] = False
    else:
        ctk["reasoning_effort"] = _ctk_effort_value(effort, model)
    extra_body: Dict[str, Any] = {"chat_template_kwargs": ctk}
    if budget and budget > 0:
        extra_body["thinking_token_budget"] = budget
    return {"extra_body": extra_body}


def _build_llamacpp(effort: str, model: str, budget: Optional[int]) -> Dict[str, Any]:
    """llama.cpp（llama-server --jinja）：chat_template_kwargs 透传进模型模板。

    预算仅服务端 --reasoning-budget 支持，/v1 无对应请求字段，不注入。
    """
    if budget:
        logger.info(f"[thinking] llama.cpp 预算须由服务端 --reasoning-budget 配置，请求级不注入 (budget={budget})")
    ctk: Dict[str, Any] = {}
    if effort == "off":
        ctk["enable_thinking"] = False
    else:
        ctk["reasoning_effort"] = _ctk_effort_value(effort, model)
    return {"extra_body": {"chat_template_kwargs": ctk}}


def _build_ollama(effort: str, model: str, budget: Optional[int]) -> Dict[str, Any]:
    """Ollama /v1 兼容层：顶层 reasoning_effort 三档（low/medium/high）。

    官方源码仅映射三档，无关闭、无预算；off/预算均不注入。
    """
    if budget:
        logger.info(f"[thinking] Ollama /v1 不支持请求级思考预算，不注入 (budget={budget})")
    if effort == "off":
        logger.info("[thinking] Ollama /v1 不支持关闭思考（需用原生 API think 字段），本次不注入参数")
        return {}
    return {"reasoning_effort": _OLLAMA_EFFORT[effort]}


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
        name="vllm",
        providers=("vllm",),
        model_pattern=None,
        builder=_build_vllm,
    ),
    _Dialect(
        name="llamacpp",
        providers=("llamacpp", "llama.cpp", "llama-cpp", "llama-server"),
        model_pattern=None,
        builder=_build_llamacpp,
    ),
    _Dialect(
        name="ollama",
        providers=("ollama",),
        model_pattern=None,
        builder=_build_ollama,
    ),
)


def _lookup_model(model: str) -> str:
    """聚合渠道模型名（如 "openai/o3"、"deepseek/deepseek-v4"）取 "/" 后段参与匹配"""
    return (model or "").split("/")[-1].strip()


def detect_dialect(provider: Optional[str], model: str) -> Optional[_Dialect]:
    """方言判定：provider 名收敛候选，模型模式作能力门控；无匹配返回 None。

    provider 显式命中后不再落入模型名兜底——避免自托管 Qwen（provider=vllm 等）
    误命中已删除的百炼方言这类错配。
    """
    lookup = _lookup_model(model)
    prov = (provider or "").strip().lower()
    for dialect in _DIALECTS:
        if prov and prov in dialect.providers:
            if dialect.model_pattern is None or dialect.model_pattern.search(lookup):
                return dialect
            return None
    # 聚合渠道/自定义厂家：纯模型名模式识别（框架方言 match-all，不参与兜底）
    for dialect in _DIALECTS:
        if dialect.model_pattern is not None and dialect.model_pattern.search(lookup):
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
    provider: Optional[str],
    model: str,
    effort: Optional[str],
    budget: Optional[int] = None,
) -> Dict[str, Any]:
    """OpenAI 兼容协议：canonical 档位 → 请求参数（可能含 extra_body）。

    返回 {} 表示不注入。返回结构约定：顶层键为 openai SDK 一等参数
    （reasoning_effort），"extra_body" 键为非标准方言参数（chat_template_kwargs /
    thinking_token_budget）。budget 仅 vLLM 方言消费（硬上限），其余方言忽略。
    """
    if not effort and not (budget and budget > 0):
        return {}
    dialect = detect_dialect(provider, model)
    if dialect is None:
        logger.info(
            f"[thinking] 模型 {model}（provider={provider or '未知'}）未匹配思考方言，"
            f"档位 {effort or '未设'}/预算 {budget or '未设'} 不注入参数"
        )
        return {}
    if not effort:
        # 仅配了预算：off/档位语义缺位，走 off 之外的框架仅 vLLM 支持预算
        if dialect.name == "vllm":
            return {"extra_body": {"thinking_token_budget": budget}}
        logger.info(f"[thinking] {dialect.name} 方言无请求级预算参数，仅预算配置不注入")
        return {}
    return dialect.builder(effort, _lookup_model(model), budget)


def merge_openai_thinking_params(
    params: Dict[str, Any],
    kwargs: Dict[str, Any],
    *,
    provider: Optional[str],
    model: str,
    effort: Optional[str],
    budget: Optional[int] = None,
) -> None:
    """把 build_openai_thinking_params 的结果合并进请求参数。

    extra_body 与调用方可能传入的 extra_body 合并（不覆盖）；其余键并入 params。
    openai 客户端的 chat / chat_stream 在 params.update(kwargs) 之前调用。
    """
    thinking = build_openai_thinking_params(provider, model, effort, budget)
    if not thinking:
        return
    extra_body = thinking.pop("extra_body", None)
    if extra_body:
        merged = {**(kwargs.get("extra_body") or {}), **extra_body}
        kwargs["extra_body"] = merged
    params.update(thinking)
