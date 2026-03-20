"""
Skill 技能基础设施（Claude Code 风格）

渐进式披露机制：
- LLM 看到工具列表中有一个 "load_skill" 工具
- description 列出所有已安装 Skill 的名称和简短描述
- LLM 自主判断是否需要某个 Skill
- 调用 load_skill(skill="xxx") 返回 SKILL.md 的完整内容
- Skill 是 prompt 模板，不是可执行代码
"""
from .registry import SkillRegistry

__all__ = ["SkillRegistry"]
