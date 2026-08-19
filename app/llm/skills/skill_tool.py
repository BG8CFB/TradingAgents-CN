"""
Skill 触发工具（参考 claude-code SkillTool）

- 工具名 `skill`，input {skill: str, args?: str}
- handler 返回展开后的 SKILL.md 全文（渐进式披露第二阶段）
- 模型按其中的指令行事（scripts/references 由模型用普通工具按路径访问）
"""

from typing import List, Optional

from app.utils.logging_init import get_logger

from ..core.types import ToolDef
from .loader import SkillStore

logger = get_logger("app.llm.skills")

SKILL_TOOL_NAME = "skill"


def make_skill_tool(store: Optional[SkillStore] = None, skill_dirs: Optional[List[str]] = None) -> ToolDef:
    """构造 skill 工具。store 可复用（与清单注入共享同一视图）。"""

    _store = store or SkillStore(skill_dirs)

    async def skill(skill: str, args: str = "") -> str:
        result = _store.expand_skill(skill, args)
        logger.info(f"📚 [skill] 展开 {skill} ({len(result)} 字符)")
        return result

    return ToolDef(
        name=SKILL_TOOL_NAME,
        description=(
            "加载并展开一个 skill 的完整指令。先从清单中选择合适的 skill 名，"
            "调用本工具获取其完整指令后按指令执行。args 为传给 skill 的参数文本。"
        ),
        params_schema={
            "type": "object",
            "properties": {
                "skill": {"type": "string", "description": "skill 名称（来自清单）"},
                "args": {"type": "string", "description": "传给 skill 的参数（可选）"},
            },
            "required": ["skill"],
        },
        handler=skill,
        is_concurrency_safe=True,  # 只读展开，可并发
    )
