"""
Skill 技能基础设施（Agent Skills 标准化实现）

Skill 是可分发的能力包，包含：
- SKILL.md：标准 frontmatter + 指令文档（必需）
- manifest.yaml：依赖、脚本入口声明（可选，带脚本的 skill 必需）
- scripts/：可执行脚本（通过 BuiltinToolSpec 注册为工具）
- references/：按需加载的参考文档
- assets/：静态资源

渐进式披露机制：
- 启动时只加载所有 skill 的 name + description（metadata 层）
- LLM 调用 load_skill(skill="xxx") 时加载完整 SKILL.md（instructions 层）
- LLM 调用脚本入口时按需执行（resources 层）

依赖自动安装：
- 首次加载 skill 时检查 manifest.yaml 声明的依赖
- 未满足 + SKILL_AUTO_INSTALL=true 时自动 pip install 到当前容器环境
- 所有安装记录写入 MongoDB skill_install_logs 集合审计
"""
from .registry import SkillRegistry
from .loader import parse_skill_metadata, load_skill_content
from .manifest import load_manifest, has_manifest

__all__ = [
    "SkillRegistry",
    "parse_skill_metadata",
    "load_skill_content",
    "load_manifest",
    "has_manifest",
]
