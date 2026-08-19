"""
报告 key → 智能体中文显示名（全部来自数据源，禁止硬编码中文名）

名称优先级：
1. 任务事件 analysis_events 中 agent_start 的 payload.name（运行时权威，含动态智能体）
2. config/agents/*.yaml 的 slug→name（配置权威）
前端只消费本模块下发的映射，不得自行写死任何智能体名称。
"""

import os
from typing import Dict, List, Optional

import yaml

from app.utils.logging_init import get_logger

logger = get_logger("services.report_titles")

# 报告 key → agent 配置 slug 的别名（纯键名对应关系；中文名一律来自配置）
_REPORT_KEY_SLUG_ALIAS = {
    "trader_investment_plan": "trader",
    "investment_plan": "trader",
    "final_trade_decision": "trader",
    "research_team_decision": "research-manager",
    "risk_management_decision": "risk-manager",
}

_AGENT_CONFIG_FILES = (
    "phase1_agents_config.yaml",
    "phase2_agents_config.yaml",
    "phase3_agents_config.yaml",
)


def _slug_to_internal(slug: str) -> str:
    """slug → 报告/状态键前缀（与 build_analyst_specs 一致）"""
    return slug.replace("-analyst", "").replace("-", "_")


def _config_dir() -> Optional[str]:
    """定位 config/agents 目录（与 agent_config.load_agent_config 相同的探测策略）"""
    probe = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        candidate = os.path.join(probe, "config", "agents")
        if os.path.exists(candidate):
            return candidate
        nxt = os.path.dirname(probe)
        if nxt == probe:
            return None
        probe = nxt
    return None


def _load_slug_names() -> Dict[str, str]:
    """读取全部 agent 配置的 slug → name（含数据库迁移过的配置时由调用方补充）"""
    names: Dict[str, str] = {}
    agents_dir = _config_dir()
    if not agents_dir:
        return names
    for config_file in _AGENT_CONFIG_FILES:
        path = os.path.join(agents_dir, config_file)
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            for agent in (config.get("agents") or []) + (config.get("customModes") or []):
                slug, name = agent.get("slug"), agent.get("name")
                if slug and name:
                    names[slug] = name
        except Exception as e:  # noqa: BLE001 - 单文件失败不影响其余
            logger.warning(f"⚠️ [report_titles] 读取 {config_file} 失败: {e}")
    return names


async def build_report_titles(task_id: str, report_keys: List[str]) -> Dict[str, str]:
    """为任务结果构建 {报告 key: 中文显示名}；无法解析的 key 不出现在结果中"""
    if not report_keys:
        return {}

    titles: Dict[str, str] = {}

    # 1) 运行时事件权威名（agent_start.payload.name，agent_key 即报告 key 前缀）
    try:
        from app.services.analysis_events import load_events

        for ev in await load_events(task_id, event_type="agent_start", limit=500):
            key = ev.get("agent_key") or ""
            name = (ev.get("payload") or {}).get("name")
            if key and isinstance(name, str) and name:
                titles[key] = name
    except Exception as e:  # noqa: BLE001 - 事件不可用时退回配置
        logger.debug(f"[report_titles] 读取任务事件失败: {e}")

    # 2) 配置补全（slug → internal key 直推 + 别名）
    slug_names = _load_slug_names()
    internal_names = {_slug_to_internal(s): n for s, n in slug_names.items()}
    for raw_key in report_keys:
        key = raw_key.replace("_report", "")
        if key in titles:
            continue
        name = internal_names.get(key)
        if name is None:
            slug = _REPORT_KEY_SLUG_ALIAS.get(key)
            name = slug_names.get(slug) if slug else None
        if name:
            titles[key] = name

    return {k: v for k, v in titles.items()}
