"""Agent 身份注册表（单一权威来源）。

收敛身份映射的六处硬编码副本：
- pipeline.py 四张表（_NODE_SLUG_MAP / _NODE_DISPLAY_FALLBACK / _NODE_EVENT_KEYS / _SLUG_ALIAS）
- prompts/builder.py report_display_names() 与 stage_2/trader.py 的复制副本
- services/report_titles.py _REPORT_KEY_SLUG_ALIAS（5 条，缺 risk_manager_decision）
- services/analysis_service.py known_report_titles 固定清单
- dynamic_analyst.py _get_non_analyst_mappings 进度文案
- 前端 agentDisplayNames.ts REPORT_KEY_SLUG_ALIAS（经 /api/registry/display-names 下发替代）

数据分两段：
- 内置静态段：9 个非分析师节点（Stage 2-4），字段从上述旧表与 phase2/3 YAML 誊抄；
  report_keys 取三处旧别名表并集（补齐 report_titles.py 缺的 risk_manager_decision）
- 动态段：分析师，从 phase1 YAML（DynamicAnalystFactory.get_all_agents）派生

行为约束（P1 等价保证）：各查询函数与被替代的旧函数输出逐项相等；本模块不改变
任何调用方的控制流。缓存与 DynamicAnalystFactory.clear_cache() 通过
clear_registry_cache() 联动（agent_configs 保存配置后调用）。
"""

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("orchestrator.registry")

# kind 枚举（P2 NodeSpec.type 前身；risk-manager 为 judge 兼终端，见 spec §4.2）
KIND_ANALYST = "analyst"
KIND_DEBATER = "debater"
KIND_JUDGE = "judge"
KIND_TRADER = "trader"
KIND_SUMMARIZER = "summarizer"

_REPORT_SUFFIX = "_report"
_ANALYST_SUFFIX_RE = re.compile(r"-analyst$")


@dataclass(frozen=True)
class AgentIdentity:
    """单个智能体的身份标识（六标识 + 进度文案）。

    slug: 配置权威 slug（summary 无 YAML 配置，用固定 "summary"）
    node_name: 旧英文执行节点名（"Bull Researcher"）——node_timings/进度/golden 锚
    internal_key: 状态/报告键前缀（分析师：slug 去 -analyst、- 转 _；非分析师 = event_key）
    name: 中文显示名（运行时从 YAML 解析；summary 固定「报告总结」，解析失败为空）
    icon: 展示图标（分析师由 _get_analyst_icon 派生）
    event_key: 事件流 agent_key（与各节点 run_conversation 内事件对齐）
    report_keys: 归属本节点的报告键全集（含历史别名，标题解析用）
    kind: analyst | debater | judge | trader | summarizer
    progress_name: 进度文案（非分析师为 icon+进度文案的另一套固定中文，与旧
        _get_non_analyst_mappings 逐字一致）
    """

    slug: str
    node_name: str
    internal_key: str
    name: str
    icon: str
    event_key: str
    report_keys: Tuple[str, ...]
    kind: str
    progress_name: str

    @property
    def is_analyst(self) -> bool:
        return self.kind == KIND_ANALYST


def format_analyst_node(internal_key: str) -> str:
    """internal_key → 执行节点名（与旧 pipeline._format_analyst_node 一致，如 'market' → 'Market Analyst'）"""
    return internal_key.replace("_", " ").title().replace(" ", "_") + " Analyst"


def analyst_internal_key(slug: str) -> str:
    """分析师 slug → internal_key（与旧装配规则一致：去 -analyst 后缀、- 转 _）"""
    return _ANALYST_SUFFIX_RE.sub("", slug).replace("-", "_")


# 内置静态段（9 个非分析师节点）：
# (slug, node_name, event_key, icon, report_keys, kind, progress_name)
# name 运行时经 load_agent_display_name 解析；summary 无 slug 配置走固定 fallback。
_STATIC_ROWS: Tuple[Tuple, ...] = (
    (
        "bull-researcher",
        "Bull Researcher",
        "researcher_bull",
        "🐂",
        ("bull_researcher",),
        KIND_DEBATER,
        "🐂 看涨研究员",
    ),
    (
        "bear-researcher",
        "Bear Researcher",
        "researcher_bear",
        "🐻",
        ("bear_researcher",),
        KIND_DEBATER,
        "🐻 看跌研究员",
    ),
    (
        "research-manager",
        "Research Manager",
        "research_manager",
        "👔",
        ("research_team_decision",),
        KIND_JUDGE,
        "👔 研究经理",
    ),
    (
        "trader",
        "Trader",
        "trader",
        "💼",
        ("trader_investment_plan", "investment_plan", "final_trade_decision"),
        KIND_TRADER,
        "💼 交易员决策",
    ),
    ("risky-analyst", "Risky Analyst", "risk_debater_risky", "🔥", ("risky_analyst",), KIND_DEBATER, "🔥 激进风险评估"),
    ("safe-analyst", "Safe Analyst", "risk_debater_safe", "🛡️", ("safe_analyst",), KIND_DEBATER, "🛡️ 保守风险评估"),
    (
        "neutral-analyst",
        "Neutral Analyst",
        "risk_debater_neutral",
        "⚖️",
        ("neutral_analyst",),
        KIND_DEBATER,
        "⚖️ 中性风险评估",
    ),
    (
        "risk-manager",
        "Risk Judge",
        "risk_manager",
        "🎯",
        ("risk_management_decision", "risk_manager_decision"),
        KIND_JUDGE,
        "🎯 风险经理",
    ),
    ("summary", "Summary Agent", "summary", "📊", (), KIND_SUMMARIZER, "📊 生成报告"),
)

# Summary 无 slug 配置的固定显示名（旧 _NODE_DISPLAY_FALLBACK 唯一条目）
_SUMMARY_FALLBACK_NAME = "报告总结"

# 进程内缓存：配置文件运行期不变化，首次查询后固化；clear_registry_cache() 失效
_identities_cache: Optional[List[AgentIdentity]] = None
_slug_name_cache: Dict[str, str] = {}


def _load_display_name(slug: str) -> str:
    """slug → YAML 中文名（带进程缓存；未命中返回空串）。

    覆盖旧 load_agent_display_name 的每次直读行为：结果等价，I/O 收敛为一次。
    """
    if slug in _slug_name_cache:
        return _slug_name_cache[slug]
    name = ""
    try:
        from app.engine.agents.utils.agent_config import load_agent_display_name

        name = load_agent_display_name(slug) or ""
    except Exception as e:  # noqa: BLE001 - 显示名解析失败回退空串，不阻断查询
        logger.warning(f"⚠️ [registry] 加载显示名失败: {slug}, {e}")
    _slug_name_cache[slug] = name
    return name


def _build_static_identities() -> List[AgentIdentity]:
    """静态段 → AgentIdentity 列表（name 从 YAML 解析，summary 用固定 fallback）"""
    rows = []
    for slug, node_name, event_key, icon, report_keys, kind, progress_name in _STATIC_ROWS:
        if kind == KIND_SUMMARIZER:
            name = _SUMMARY_FALLBACK_NAME
        else:
            name = _load_display_name(slug)
        rows.append(
            AgentIdentity(
                slug=slug,
                node_name=node_name,
                internal_key=event_key,
                name=name,
                icon=icon,
                event_key=event_key,
                report_keys=report_keys,
                kind=kind,
                progress_name=progress_name,
            )
        )
    return rows


def _build_dynamic_identities() -> List[AgentIdentity]:
    """动态段：phase1 分析师 → AgentIdentity 列表（与旧 build_analyst_specs 派生规则一致）"""
    from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory

    rows: List[AgentIdentity] = []
    seen: set = set()
    for agent in DynamicAnalystFactory.get_all_agents():
        slug = agent.get("slug", "")
        name = agent.get("name", "")
        if not slug or not name:
            continue
        internal_key = analyst_internal_key(slug)
        if internal_key in seen:
            continue
        seen.add(internal_key)
        icon = DynamicAnalystFactory._get_analyst_icon(slug, name, agent_config=agent)
        rows.append(
            AgentIdentity(
                slug=slug,
                node_name=format_analyst_node(internal_key),
                internal_key=internal_key,
                name=name,
                icon=icon,
                # 分析师事件流 agent_key = internal_key（run_analyst/_run_analyst 同键）
                event_key=internal_key,
                report_keys=(f"{internal_key}{_REPORT_SUFFIX}",),
                kind=KIND_ANALYST,
                progress_name=f"{icon} {name}",
            )
        )
    return rows


def _load_identities() -> List[AgentIdentity]:
    """全部身份（静态 9 节点 + 动态分析师），进程内缓存一次"""
    global _identities_cache
    if _identities_cache is None:
        try:
            _identities_cache = _build_static_identities() + _build_dynamic_identities()
        except Exception as e:  # noqa: BLE001 - 动态段构建失败退化为仅静态段（旧表等价行为）
            logger.warning(f"⚠️ [registry] 分析师身份构建失败，退化为静态段: {e}")
            _identities_cache = _build_static_identities()
    return _identities_cache


def clear_registry_cache() -> None:
    """配置更新后失效全部缓存（与 DynamicAnalystFactory.clear_cache 联动调用）"""
    global _identities_cache
    _identities_cache = None
    _slug_name_cache.clear()


# ── 查询函数（与被替代的旧函数输出逐项相等）───────────────────────────────


def get_identity_by_node(node_name: str) -> Optional[AgentIdentity]:
    """执行节点名 → 身份（分析师节点名动态段命中；未命中 None）"""
    for identity in _load_identities():
        if identity.node_name == node_name:
            return identity
    return None


def get_identity_by_slug(slug: str) -> Optional[AgentIdentity]:
    """slug → 身份（含分析师动态段）"""
    for identity in _load_identities():
        if identity.slug == slug:
            return identity
    return None


def event_key_for_node(node_name: str) -> str:
    """节点名 → 事件流 agent_key（旧 _NODE_EVENT_KEYS.get(node_name, node_name) 等价）"""
    identity = get_identity_by_node(node_name)
    return identity.event_key if identity else node_name


def display_name_for_node(node_name: str) -> str:
    """节点名 → 中文显示名（旧 _resolve_display_names().get(node_name) 等价：未命中无值）"""
    identity = get_identity_by_node(node_name)
    return identity.name if identity and identity.name else ""


def slug_for_node(node_name: str) -> str:
    """节点名 → 配置 slug（旧 _NODE_SLUG_MAP 查询等价；summary 返回固定 slug）"""
    identity = get_identity_by_node(node_name)
    return identity.slug if identity else ""


def _report_key_slug_index() -> Dict[str, str]:
    """报告键（去 _report 后缀的基键）→ slug 索引 = 旧 _SLUG_ALIAS 的超集"""
    index: Dict[str, str] = {}
    for identity in _load_identities():
        for key in identity.report_keys:
            base = key[: -len(_REPORT_SUFFIX)] if key.endswith(_REPORT_SUFFIX) else key
            index[base] = identity.slug
    return index


def slug_for_report_key(report_key: str) -> Optional[str]:
    """报告基键（去 _report 后缀与否均可）→ 归属 slug（别名索引；未命中 None）"""
    base = report_key[: -len(_REPORT_SUFFIX)] if report_key.endswith(_REPORT_SUFFIX) else report_key
    return _report_key_slug_index().get(base)


def report_title(report_key: str, display_name: str = "") -> str:
    """report_key → 展示标题（旧 pipeline._report_display_title 解析链等价）。

    解析链：去 _report 后缀 → 别名索引命中 slug（未命中走 slug 化兜底）
    → YAML 中文名双候选探测（slug、slug-analyst）→ display_name → report_key 原样。
    """
    base = report_key[: -len(_REPORT_SUFFIX)] if report_key.endswith(_REPORT_SUFFIX) else report_key
    slug = _report_key_slug_index().get(base, base.replace("_", "-"))
    title = ""
    for candidate in (slug, f"{slug}-analyst"):
        title = _load_display_name(candidate)
        if title:
            break
    return title or display_name or report_key


def analyst_report_display_names() -> Dict[str, str]:
    """分析师 report_key → 「{中文名}报告」（旧 builder.report_display_names 等价）"""
    names: Dict[str, str] = {}
    for identity in _load_identities():
        if identity.is_analyst and identity.name:
            names[f"{identity.internal_key}{_REPORT_SUFFIX}"] = f"{identity.name}报告"
    return names


def progress_text(node_name: str) -> Optional[str]:
    """节点名 → 进度文案（旧 build_node_mapping 查询等价；None = 调用方回退节点名）"""
    identity = get_identity_by_node(node_name)
    if identity is None:
        # 旧映射对 tools_*/Msg Clear* 等辅助节点显式置 None（跳过/回退），此处同样返回 None
        return None
    if identity.is_analyst:
        return identity.progress_name or None
    return identity.progress_name


def builtin_progress_texts() -> Dict[str, str]:
    """内置 9 非分析师节点的进度文案（旧 _get_non_analyst_mappings 等价）"""
    return {i.node_name: i.progress_name for i in _load_identities() if not i.is_analyst}


def names_by_slug() -> Dict[str, str]:
    """slug → YAML 中文名（旧 report_titles._load_slug_names 三文件全量等价：静态 9 + phase1 全部）"""
    return {i.slug: i.name for i in _load_identities() if i.name}


def all_display_keys() -> Dict[str, str]:
    """全部展示键 → 中文名（/api/registry/display-names 数据源）。

    键集合 = 前端 agentDisplayNames.ts 本地构建四类键（slug / base / base_report /
    base_analyst）的超集，外加：全部 report_keys（trader 3 别名、judge 2 别名等历史
    键）与 event_key。值为裸 YAML 中文名（前端现状语义，不带「报告」后缀）。
    """
    keys: Dict[str, str] = {}
    for identity in _load_identities():
        name = identity.name
        if not name:
            continue
        base = _ANALYST_SUFFIX_RE.sub("", identity.slug).replace("-", "_")
        for key in (identity.slug, base, f"{base}{_REPORT_SUFFIX}", f"{base}_analyst"):
            keys[key] = name
        for report_key in identity.report_keys:
            keys[report_key] = name
        if identity.event_key and identity.event_key != base:
            keys[identity.event_key] = name
    return keys
