"""prompt 组装层：报告注入 / 辩论历史重建 / 环境上下文 / 文案常量的唯一来源"""

from .builder import (
    build_recall_rounds,
    build_researcher_trigger,
    collect_reports,
    context_prefix,
    inject_report_messages,
    report_display_names,
    wrap_report,
)
from .parts import REFLECTION_SYSTEM_PROMPT, SUMMARY_SYSTEM_PROMPT

__all__ = [
    "build_recall_rounds",
    "build_researcher_trigger",
    "collect_reports",
    "context_prefix",
    "inject_report_messages",
    "report_display_names",
    "wrap_report",
    "REFLECTION_SYSTEM_PROMPT",
    "SUMMARY_SYSTEM_PROMPT",
]
