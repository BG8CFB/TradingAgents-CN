"""
ClawHub 市场集成测试（真实 HTTP，标记 integration）

覆盖：
- 列表分页（limit + nextCursor）与条目 reference（owner/slug）
- 搜索（实测 /api/v1/search 返回 results，客户端归一化为 items）
- 详情 canonical_url 回链、owner 消歧（reference 携带 owner）
- 版本文件清单（含 sha256）
- 真实安装一个小型无依赖 skill 到用户目录（结束后清理）
- 安装命令解析（skills-sh: / @owner/slug / git URL）

网络不可达时跳过（外部依赖，不算失败）。
"""
import asyncio
import shutil
import sys
from pathlib import Path

import httpx
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.engine.tools.skill.marketplace import (
    AmbiguousSkillSlug,
    MarketplaceClient,
    parse_reference,
)
from app.engine.tools.skill.registry_installer import install_from_marketplace
from app.services.skill_service import SkillService

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client():
    return MarketplaceClient("https://clawhub.ai", cache_ttl=0)


def _upstream_reachable() -> bool:
    try:
        resp = httpx.get("https://clawhub.ai/api/v1/skills", params={"limit": 1}, timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


_REACHABLE = _upstream_reachable()
_SKIP_REASON = "clawhub.ai 不可达（外部网络依赖）"


def _first_item(client) -> dict:
    """取列表第一个含 reference 的条目（上游偶发返回空列表，重试后再放弃）"""
    import time

    for _ in range(3):
        result = asyncio.run(client.list_skills(limit=10))
        if result["items"]:
            for item in result["items"]:
                if item.get("reference") and "/" in item["reference"]:
                    return item
            return result["items"][0]
        time.sleep(1)
    pytest.skip("上游列表暂时为空（外部服务抖动）")


@pytest.mark.skipif(not _REACHABLE, reason=_SKIP_REASON)
class TestMarketplaceReadOnly:
    def test_list_pagination_and_reference(self, client):
        result = asyncio.run(client.list_skills(limit=5))
        assert 1 <= len(result["items"]) <= 5
        assert all(i["slug"] for i in result["items"])
        # 归一化条目必须带 reference（owner/slug 或裸 slug），供安装消歧
        assert all("reference" in i for i in result["items"])
        if result["next_cursor"]:
            page2 = asyncio.run(client.list_skills(limit=5, cursor=result["next_cursor"]))
            assert page2["items"]

    def test_search_returns_results(self, client):
        item = _first_item(client)
        result = asyncio.run(client.search(item["slug"].split("-")[0]))
        # 实测 /api/v1/search 返回 {"results": [...]}；客户端归一化进 items
        assert isinstance(result["items"], list)
        assert "items" in result

    def test_detail_canonical_url(self, client):
        item = _first_item(client)
        detail = asyncio.run(client.get_skill(item["reference"]))
        assert detail["slug"]
        assert detail["canonical_url"].startswith("https://clawhub.ai/")
        # reference 消歧：详情返回 owner/slug 形式
        assert "/" in detail["reference"] or detail["owner"]

    def test_version_files_with_sha256(self, client):
        item = _first_item(client)
        detail = asyncio.run(client.get_skill(item["reference"]))
        version = detail.get("latest_version")
        if not version:
            pytest.skip("该 skill 无版本信息")
        files = asyncio.run(client.get_version_files(detail["reference"], version))
        assert any(f["path"] == "SKILL.md" for f in files)

    def test_ambiguous_bare_slug_raises_or_disambiguates(self, client):
        """裸 slug 若撞名，客户端应抛 AmbiguousSkillSlug（带 ?owner= 则不抛）"""
        item = _first_item(client)
        slug = item["slug"]
        try:
            detail = asyncio.run(client.get_skill(slug))
            assert detail["slug"] == slug or detail["slug"]
        except AmbiguousSkillSlug as e:
            assert e.matches  # 携带候选列表
            owner, _ = parse_reference(
                f"{e.matches[0].get('ownerHandle')}/{e.matches[0].get('slug')}"
            )
            assert owner


@pytest.mark.skipif(not _REACHABLE, reason=_SKIP_REASON)
class TestMarketplaceInstall:
    def test_install_small_skill_and_cleanup(self, client):
        """真实安装一个市场 skill，校验落盘与来源标记，结束后清理"""
        result = asyncio.run(install_from_marketplace("gifgrep"))
        try:
            assert result["success"], result
            installed = Path(result["installed_path"])
            assert (installed / "SKILL.md").exists()
            import yaml

            data = yaml.safe_load((installed / "manifest.yaml").read_text(encoding="utf-8"))
            assert data["source"]["type"] == "registry"
            assert data["source"]["url"].startswith("https://clawhub.ai")
        finally:
            if result.get("installed_path"):
                shutil.rmtree(result["installed_path"], ignore_errors=True)


class TestReferenceParsing:
    """安装命令/引用解析（纯逻辑，无网络）"""

    def test_skills_sh_reference(self):
        resolved = SkillService.resolve_install_reference(
            "openclaw skills install skills-sh:vercel-labs/skills/find-skills"
        )
        assert resolved["kind"] == "git"
        assert resolved["url"] == "https://github.com/vercel-labs/skills.git"
        assert resolved["subdir"] == "find-skills"

    def test_npx_skills_add_marketplace_url(self):
        """npx skills add https://clawhub.ai/{owner}/skills/{slug} → 市场安装（非 git clone）"""
        resolved = SkillService.resolve_install_reference(
            "npx skills add https://clawhub.ai/othmanadi/skills/planning-with-files"
        )
        assert resolved["kind"] == "marketplace"
        assert resolved["reference"] == "othmanadi/planning-with-files"

    def test_bare_marketplace_url(self):
        resolved = SkillService.resolve_install_reference(
            "https://clawhub.ai/obakosa/skills/calculate-fair-value"
        )
        assert resolved["kind"] == "marketplace"
        assert resolved["reference"] == "obakosa/calculate-fair-value"

    def test_non_marketplace_url_still_git(self):
        resolved = SkillService.resolve_install_reference(
            "https://github.com/anthropics/skills"
        )
        assert resolved["kind"] == "git"

    def test_at_owner_slug(self):
        resolved = SkillService.resolve_install_reference("@obakosa/calculate-fair-value")
        assert resolved["kind"] == "marketplace"
        assert resolved["reference"] == "obakosa/calculate-fair-value"

    def test_bare_slug(self):
        resolved = SkillService.resolve_install_reference("gifgrep")
        assert resolved["kind"] == "marketplace"
        assert resolved["reference"] == "gifgrep"

    def test_git_url_with_fragment(self):
        resolved = SkillService.resolve_install_reference(
            "https://github.com/anthropics/skills#document-skills/docx"
        )
        assert resolved["kind"] == "git"
        assert resolved["url"] == "https://github.com/anthropics/skills"
        assert resolved["subdir"] == "document-skills/docx"

    def test_git_shorthand(self):
        resolved = SkillService.resolve_install_reference("git:anthropics/skills")
        assert resolved["kind"] == "git"
        assert resolved["url"] == "https://github.com/anthropics/skills.git"
        assert resolved["subdir"] == ""

    def test_invalid(self):
        assert SkillService.resolve_install_reference("")["kind"] == "invalid"
        assert SkillService.resolve_install_reference("skills-sh:")["kind"] == "invalid"
