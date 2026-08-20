"""
Skill 加载与渐进式披露（参考 claude-code loadSkillsDir / SkillTool/prompt.ts）

- 常态只暴露 name + description(+when_to_use) 清单：预算 ~8000 字符、单条 1536 截断
- 命中后 expand_skill 读取 SKILL.md 全文，替换 $ARGUMENTS 与 ${SKILL_DIR} 占位符
"""

import re
from pathlib import Path
from typing import List, Optional

import logging

from .discovery import SkillMeta, discover_skills

logger = logging.getLogger("app.llm.skills")

# 预算参数（参考 claude-code：上下文 1%，约 8000 字符；单条描述 1536）
LISTING_CHAR_BUDGET = 8000
PER_DESC_LIMIT = 1536


class SkillStore:
    """skill 目录的内存视图（发现 + 清单 + 展开）"""

    def __init__(self, skill_dirs: Optional[List[str]] = None):
        self.skills = discover_skills(skill_dirs)

    def get(self, name: str) -> Optional[SkillMeta]:
        return self.skills.get(name)

    def invocable(self) -> List[SkillMeta]:
        """模型可调用的 skill（剔除 disable-model-invocation）"""
        return [s for s in self.skills.values() if not s.disable_model_invocation]

    def listing_text(self) -> str:
        """渐进式披露第一阶段：name + description 清单（超预算时降级为仅名字）"""
        skills = sorted(self.invocable(), key=lambda x: x.name)
        if not skills:
            return ""
        lines = ["The following skills are available for use with the skill tool:"]
        listed: set = set()
        total = 0
        for s in skills:
            desc = s.description[:PER_DESC_LIMIT]
            entry = f"- {s.name}: {desc}"
            if s.when_to_use:
                entry += f" (when to use: {s.when_to_use[:200]})"
            if total + len(entry) > LISTING_CHAR_BUDGET:
                break  # 超预算：未列出的降级为 names-only（参考项目行为）
            lines.append(entry)
            listed.add(s.name)
            total += len(entry)
        remaining = [s.name for s in skills if s.name not in listed]
        if remaining:
            lines.append(f"(描述预算不足，仅列名: {', '.join(remaining)})")
        return "\n".join(lines)

    def expand_skill(self, name: str, args: str = "") -> str:
        """渐进式披露第二阶段：读取全文并做占位符替换。

        占位符（对齐参考项目）：
        - $ARGUMENTS → args
        - ${CLAUDE_SKILL_DIR} / ${SKILL_DIR} → skill 绝对目录
        """
        meta = self.skills.get(name)
        if meta is None:
            return f"错误：未知 skill '{name}'。可用: {sorted(self.skills)}"
        if meta.disable_model_invocation:
            return f"错误：skill '{name}' 已禁用模型调用"
        skill_md = Path(meta.skill_dir) / "SKILL.md"
        try:
            text = skill_md.read_text(encoding="utf-8")
        except OSError as e:
            return f"错误：读取 skill 失败: {e}"
        body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, count=1, flags=re.DOTALL)
        body = body.replace("$ARGUMENTS", args or "")
        # 替换串用 lambda：避免 Windows 路径反斜杠被当作正则转义（\U 等会报错）
        body = re.sub(r"\$\{(?:CLAUDE_)?SKILL_DIR\}", lambda _m: str(meta.skill_dir), body)
        header = f"Base directory for this skill: {meta.skill_dir}\n\n"
        footer = self._allowed_tools_hint(meta)
        return header + body.strip() + footer

    @staticmethod
    def _allowed_tools_hint(meta: SkillMeta) -> str:
        """frontmatter allowed-tools → 尾部能力边界提示（对齐 claude-code 权限声明）"""
        at = meta.frontmatter.get("allowed-tools") or meta.frontmatter.get("allowed_tools")
        if isinstance(at, str):
            tools = [t for t in at.replace(",", " ").split() if t]
        elif isinstance(at, list):
            tools = [str(t) for t in at if str(t).strip()]
        else:
            return ""
        if not tools:
            return ""
        return f"\n\n---\n本 skill 限定的数据工具: {', '.join(tools)}（仅通过这些工具获取数据）"
