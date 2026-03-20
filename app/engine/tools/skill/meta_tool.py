"""
load_skill Meta-Tool

提供一个 LangChain Tool，让 LLM 能够按需加载 Skill 的完整指令文档。
这是渐进式披露机制的核心：LLM 先看到工具列表中的可用技能摘要，
自主判断后调用 load_skill(skill="xxx") 获取完整指导。
"""
import logging

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from .registry import SkillRegistry

logger = logging.getLogger(__name__)


class _LoadSkillInput(BaseModel):
    """load_skill 工具的输入参数"""
    skill_name: str = Field(
        ...,
        description="要加载的技能名称",
    )


def _build_description(registry: SkillRegistry) -> str:
    """
    动态生成 load_skill 工具的 description

    根据当前可用技能列表，生成包含技能清单的描述文本。
    如果没有已安装的 Skill，返回提示信息。

    Args:
        registry: 技能注册表实例

    Returns:
        工具描述文本
    """
    skills = registry.list_skills()

    if not skills:
        return "当前没有已安装的技能。"

    skill_lines = []
    for s in skills:
        desc = s["description"] or "（无描述）"
        skill_lines.append(f"- {s['name']}: {desc}")

    description = (
        "加载技能以获取专业的分析指导。调用后你将获得该技能的完整指令文档。\n\n"
        "可用技能列表：\n"
        + "\n".join(skill_lines)
        + "\n\n"
        '调用示例：load_skill(skill="example_skill")'
    )

    return description


def _run_load_skill(skill_name: str, registry: SkillRegistry) -> str:
    """
    load_skill 工具的执行逻辑

    从注册表获取指定技能的 SKILL.md 完整内容并返回。
    技能不存在或已禁用时返回错误提示。

    Args:
        skill_name: 要加载的技能名称
        registry: 技能注册表实例

    Returns:
        SKILL.md 的完整文本，或错误提示信息
    """
    content = registry.get_skill_content(skill_name)

    if content is None:
        # 判断是禁用还是不存在
        all_names = {s["name"] for s in registry._skills}
        if skill_name in all_names:
            return f"技能 \"{skill_name}\" 当前已被禁用。"
        return f"技能 \"{skill_name}\" 不存在。可用技能: {', '.join(s['name'] for s in registry.list_skills()) or '无'}"

    logger.info(f"LLM 加载技能: {skill_name}")
    return content


def create_load_skill_tool(registry: SkillRegistry) -> StructuredTool:
    """
    创建 load_skill Meta-Tool

    生成一个 LangChain StructuredTool，LLM 通过调用此工具
    按需获取 Skill 的完整指令文档。

    Args:
        registry: 技能注册表实例

    Returns:
        LangChain StructuredTool 实例
    """
    description = _build_description(registry)

    tool = StructuredTool.from_function(
        func=lambda skill_name: _run_load_skill(skill_name, registry),
        name="load_skill",
        description=description,
        args_schema=_LoadSkillInput,
    )

    return tool
