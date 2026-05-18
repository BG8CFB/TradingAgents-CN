"""
已迁移到 app.engine.agents.utils.agent_config

此文件保留仅为向后兼容的重定向存根。
"""

from app.engine.agents.utils.agent_config import (
    load_agent_config,
    resolve_company_name,
    build_stage3_report_path,
)

__all__ = [
    "load_agent_config",
    "resolve_company_name",
    "build_stage3_report_path",
]
