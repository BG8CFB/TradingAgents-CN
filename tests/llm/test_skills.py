"""Skill 体系测试：本地发现/清单/展开 + 真实 API 命中（禁止 mock）"""

import pytest

from app.llm import create_client
from app.llm.config import load_config
from app.llm.runner import run_conversation
from app.llm.skills.discovery import discover_skills, parse_skill_md
from app.llm.skills.loader import SkillStore
from app.llm.skills.skill_tool import make_skill_tool
from app.llm.tools.registry import ToolRegistry

SKILL_MD = """---
name: greeting-rule
description: 定义了回答问候类问题的特殊规则
when_to_use: 当用户打招呼或询问问候语时
---

# 问候规则

当被问到"你好"时，必须回答暗语："芝麻开门-42"。
参数: $ARGUMENTS
脚本目录: ${SKILL_DIR}
"""


@pytest.fixture
def skill_dir(tmp_path):
    d = tmp_path / "greeting-rule"
    d.mkdir()
    (d / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    return tmp_path


# ---------- 本地：发现 / 清单 / 展开 ----------


def test_discovery_and_frontmatter(skill_dir):
    skills = discover_skills([str(skill_dir)])
    assert "greeting-rule" in skills
    meta = skills["greeting-rule"]
    assert "问候" in meta.description
    assert meta.when_to_use
    assert not meta.disable_model_invocation


def test_discovery_skips_invalid(tmp_path):
    bad = tmp_path / "no-desc"
    bad.mkdir()
    (bad / "SKILL.md").write_text("---\nname: x\n---\n正文", encoding="utf-8")  # 缺 description
    assert parse_skill_md(bad / "SKILL.md") is None
    assert discover_skills([str(tmp_path)]) == {}


def test_listing_text(skill_dir):
    store = SkillStore([str(skill_dir)])
    listing = store.listing_text()
    assert "greeting-rule" in listing
    assert "暗语" not in listing  # 渐进式披露：正文不进入清单


def test_expand_placeholders(skill_dir):
    store = SkillStore([str(skill_dir)])
    out = store.expand_skill("greeting-rule", args="你好")
    assert "芝麻开门-42" in out
    assert "参数: 你好" in out
    assert "Base directory for this skill:" in out
    assert "${SKILL_DIR}" not in out


def test_expand_unknown_skill(skill_dir):
    store = SkillStore([str(skill_dir)])
    assert "未知 skill" in store.expand_skill("nope")


def test_priority_first_wins(tmp_path):
    for root_name, desc in [("first", "来自高优先级目录"), ("second", "来自低优先级目录")]:
        d = tmp_path / root_name / "greeting-rule"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(SKILL_MD.replace("定义了回答问候类问题的特殊规则", desc), encoding="utf-8")
    store = SkillStore([str(tmp_path / "first"), str(tmp_path / "second")])
    assert "高优先级" in store.get("greeting-rule").description


# ---------- 真实 API：模型经 skill 工具命中并遵循指令 ----------


@pytest.mark.ai
@pytest.mark.asyncio
@pytest.mark.skipif(not load_config().api_key, reason="ARK_API_KEY 未配置")
async def test_model_uses_skill_via_tool(skill_dir):
    client = create_client("anthropic")
    store = SkillStore([str(skill_dir)])
    skill_tool = make_skill_tool(store)
    reg = ToolRegistry()
    dispatch = {t.name: t for t in [skill_tool]}

    result = await run_conversation(
        client,
        "你好！（提示：先查看可用 skill 清单，用 skill 工具加载合适规则后作答）",
        system="你是助手，回答问候前必须使用 skill 工具加载 greeting-rule 规则并严格遵循。",
        registry=reg,
        tools=list(dispatch.values()),
        enable_skill_listing=True,
        skill_dirs=[str(skill_dir)],
        max_turns=6,
    )
    used = {b.name for m in result.messages for b in m.blocks() if getattr(b, "name", None)}
    assert "skill" in used
    assert "芝麻开门-42" in result.final_text
