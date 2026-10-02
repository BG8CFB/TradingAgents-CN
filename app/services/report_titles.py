"""
报告 key → 智能体中文显示名（全部来自数据源，禁止硬编码中文名）

名称优先级：
1. 任务事件 analysis_events 中 agent_start 的 payload.name（运行时权威，含动态智能体）
2. AgentRegistry（配置权威：静态 9 节点 + phase1 分析师，slug → YAML name）
前端只消费本模块下发的映射，不得自行写死任何智能体名称。
"""

from typing import Dict, List

import logging

logger = logging.getLogger("services.report_titles")


def _slug_to_internal(slug: str) -> str:
    """slug → 报告/状态键前缀（与 build_analyst_specs 一致）"""
    return slug.replace("-analyst", "").replace("-", "_")


def _load_slug_names() -> Dict[str, str]:
    """全部 agent 配置的 slug → name（registry 单一权威表；含数据库迁移过的配置时由调用方补充）"""
    from app.engine.orchestrator.registry import names_by_slug

    return names_by_slug()


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

    # 2) 配置补全（slug → internal key 直推 + registry 别名索引）
    from app.engine.orchestrator.registry import slug_for_report_key

    slug_names = _load_slug_names()
    internal_names = {_slug_to_internal(s): n for s, n in slug_names.items()}
    for raw_key in report_keys:
        key = raw_key.replace("_report", "")
        if key in titles:
            continue
        name = internal_names.get(key)
        if name is None:
            slug = slug_for_report_key(key)
            name = slug_names.get(slug) if slug else None
        if name:
            titles[key] = name

    return {k: v for k, v in titles.items()}
