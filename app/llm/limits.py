"""输出上限 / 上下文窗口单一解析器 — 全项目唯一事实源。

对齐 claude-code 的 {default, upperLimit} 语义（参考项目/claude-code
src/utils/context.ts getModelMaxOutputTokens）：按模型解析输出上限与封顶，
能力数据（model_catalog）优先补缺，用户显式配置永远最高，代码常量仅兜底。

解析优先级：
- max_tokens     : llm_configs 用户设置 > model_catalog > 环境变量
                   LLM_DEFAULT_MAX_TOKENS > DEFAULT_MAX_TOKENS(128000)
- context_window : llm_configs 用户设置 > model_catalog context_length > None
                   （None=未知，压缩层走 DEFAULT_CONTEXT_WINDOW 兜底）
- upper_limit    : min(max(catalog.max_tokens, ESCALATED_MAX_TOKENS), MAX_TOKENS_MAX)

注意：catalog 索引由调用方（providers.py）注入，本模块零数据库依赖，
避免 app/llm 层反向依赖数据库连接层。
"""

import os
from dataclasses import dataclass
from typing import Dict, Optional

from app.constants.llm_defaults import (
    DEFAULT_CONTEXT_WINDOW,
    DEFAULT_MAX_TOKENS,
    ESCALATED_MAX_TOKENS,
    MAX_TOKENS_MAX,
)
from app.utils.logging_init import get_logger

logger = get_logger("app.llm")

# catalog 索引：{(provider|model): {"context_length": int, "max_tokens": int|None}}
# 由 providers.py 在客户端解析时注入（惰性，避免循环 import；进程内缓存）
_catalog_index: Dict[str, Dict[str, Optional[int]]] = {}


def set_catalog_index(index: Dict[str, Dict[str, Optional[int]]]) -> None:
    """providers.py 加载 model_catalog 后注入；重复调用覆盖旧值。"""
    global _catalog_index
    _catalog_index = dict(index or {})


def get_catalog_index() -> Dict[str, Dict[str, Optional[int]]]:
    return _catalog_index


def _env_default_max_tokens() -> Optional[int]:
    """环境变量全局默认（回滚开关）；非法值忽略。"""
    raw = os.getenv("LLM_DEFAULT_MAX_TOKENS", "").strip()
    if not raw:
        return None
    try:
        val = int(raw)
    except ValueError:
        logger.warning(f"⚠️ [limits] 环境变量 LLM_DEFAULT_MAX_TOKENS 非法: {raw!r}，忽略")
        return None
    if val < 1:
        return None
    return min(val, MAX_TOKENS_MAX)


@dataclass(frozen=True)
class OutputLimits:
    """模型输出/输入能力三元组。"""

    max_tokens: int  # 单次请求默认输出上限（anthropic 必填语义）
    upper_limit: int  # 截断升级封顶（升级重发的目标值）
    context_window: Optional[int]  # 输入窗口；None=未知（压缩层用兜底）


def resolve_output_limits(
    model: str,
    provider: Optional[str] = None,
    *,
    db_max_tokens: Optional[int] = None,
    db_context_window: Optional[int] = None,
) -> OutputLimits:
    """解析模型输出上限与上下文窗口。

    Args:
        model: 模型名（如 Qwen3.8-27B）
        provider: 厂家名（catalog 索引键组成；缺省尝试任意 provider 匹配）
        db_max_tokens: 调用方已知的 llm_configs 每模型显式值（最高优先）
        db_context_window: 同上（context_window 字段）
    """
    catalog = _lookup_catalog(model, provider)

    # ── max_tokens：显式配置 > catalog > 环境变量 > 常量兜底 ──
    max_tokens = _first_positive(db_max_tokens, catalog.get("max_tokens"))
    if max_tokens is None:
        max_tokens = _env_default_max_tokens() or DEFAULT_MAX_TOKENS

    # ── upper_limit：catalog 能力与升级常量取大者，封顶 MAX_TOKENS_MAX ──
    catalog_max = catalog.get("max_tokens")
    upper_base = max(ESCALATED_MAX_TOKENS, catalog_max) if catalog_max else ESCALATED_MAX_TOKENS
    upper_limit = min(upper_base, MAX_TOKENS_MAX)
    if max_tokens > upper_limit:
        upper_limit = min(max_tokens, MAX_TOKENS_MAX)

    # ── context_window：显式配置 > catalog context_length ──
    context_window = _first_positive(db_context_window, catalog.get("context_length"))

    return OutputLimits(
        max_tokens=max_tokens,
        upper_limit=upper_limit,
        context_window=context_window,
    )


def fallback_context_window(limits: OutputLimits) -> int:
    """压缩层用：窗口未知时取兜底（DEFAULT_CONTEXT_WINDOW）。"""
    return limits.context_window or DEFAULT_CONTEXT_WINDOW


def _lookup_catalog(
    model: str, provider: Optional[str]
) -> Dict[str, Optional[int]]:
    """catalog 索引查找：精确 provider|model > 任意 provider 的 model 命中。"""
    if not model or not _catalog_index:
        return {}
    if provider:
        hit = _catalog_index.get(f"{provider.strip().lower()}|{model}")
        if hit:
            return hit
    # provider 未知或不匹配时按模型名兜底匹配（catalog 键最长优先由注入方保证）
    for key, value in _catalog_index.items():
        if key.split("|", 1)[-1] == model:
            return value
    return {}


def _first_positive(*values: Optional[int]) -> Optional[int]:
    for v in values:
        if isinstance(v, int) and v > 0:
            return v
    return None
