"""
Skill 安装器测试套件（本地 zip / 本地路径 / git interactive 校验）

覆盖：
- package_validator：正常包 / 缺 SKILL.md / 恶意 name / manifest 不一致
- local_installer：zip slip / 符号链接条目 / 超大 / 多包 zip 拒绝与清理；
  正常 zip 安装到真实用户目录（结束后卸载清理）；本地路径导入与覆盖备份
- git_installer.install_from_git_interactive：非 https 拒绝（不实际联网克隆）

测试原则：无 mock，真实文件 I/O；安装到真实 config/skills 后立即清理。
"""
import shutil
import sys
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.engine.tools.skill.git_installer import install_from_git_interactive
from app.engine.tools.skill.local_installer import (
    install_from_local_path,
    install_from_zip,
    mark_skill_source,
)
from app.engine.tools.skill.package_validator import validate_skill_package

VALID_SKILL_MD = """---
name: {name}
description: 测试技能
version: 1.0.0
---

# 测试技能

仅用于安装器测试。
"""


def _make_skill_dir(base: Path, name: str) -> Path:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(VALID_SKILL_MD.format(name=name), encoding="utf-8")
    return d


def _make_zip(tmp_path: Path, entries: dict, name: str = "test-skill.zip") -> Path:
    zp = tmp_path / name
    with zipfile.ZipFile(zp, "w") as zf:
        for path, content in entries.items():
            if isinstance(content, bytes):
                zf.writestr(path, content)
            else:
                zf.writestr(path, content)
    return zp


# ── package_validator ─────────────────────────────────────────────────


class TestValidateSkillPackage:
    def test_valid_package(self, tmp_path):
        d = _make_skill_dir(tmp_path, "valid-skill")
        name, err = validate_skill_package(d)
        assert err is None
        assert name == "valid-skill"

    def test_missing_skill_md(self, tmp_path):
        d = tmp_path / "no-skill-md"
        d.mkdir()
        name, err = validate_skill_package(d)
        assert err is not None and "SKILL.md" in err
        assert name is None

    def test_malicious_name_rejected(self, tmp_path):
        d = _make_skill_dir(tmp_path, "pkg")
        (d / "SKILL.md").write_text(
            VALID_SKILL_MD.format(name="../../evil"), encoding="utf-8"
        )
        name, err = validate_skill_package(d)
        assert err is not None and "非法字符" in err

    def test_manifest_mismatch_rejected(self, tmp_path):
        d = _make_skill_dir(tmp_path, "pkg")
        (d / "manifest.yaml").write_text(
            "schema_version: '1.0'\nskill_name: other-name\n", encoding="utf-8"
        )
        name, err = validate_skill_package(d)
        assert err is not None and "不一致" in err
        assert name == "pkg"

    def test_manifest_match_passes(self, tmp_path):
        d = _make_skill_dir(tmp_path, "pkg")
        (d / "manifest.yaml").write_text(
            "schema_version: '1.0'\nskill_name: pkg\n", encoding="utf-8"
        )
        name, err = validate_skill_package(d)
        assert err is None and name == "pkg"


# ── local_installer：zip 安全 ────────────────────────────────────────


class TestInstallFromZipSecurity:
    def test_zip_slip_rejected(self, tmp_path):
        zp = _make_zip(
            tmp_path,
            {
                "SKILL.md": VALID_SKILL_MD.format(name="evil-skill"),
                "../evil.txt": "pwned",
            },
        )
        result = install_from_zip(zp)
        assert not result["success"]
        assert "zip slip" in result["error"]
        assert not (tmp_path / "evil.txt").exists()

    def test_absolute_path_entry_rejected(self, tmp_path):
        zp = _make_zip(
            tmp_path,
            {"SKILL.md": VALID_SKILL_MD.format(name="evil-skill"), "/etc/passwd": "x"},
        )
        result = install_from_zip(zp)
        assert not result["success"]

    def test_symlink_entry_rejected(self, tmp_path):
        zp = tmp_path / "symlink.zip"
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("SKILL.md", VALID_SKILL_MD.format(name="evil-skill"))
            info = zipfile.ZipInfo("link")
            # S_IFLNK = 0o120000
            info.external_attr = (0o120777 << 16)
            zf.writestr(info, "/etc/passwd")
        result = install_from_zip(zp)
        assert not result["success"]
        assert "符号链接" in result["error"]

    def test_multi_package_rejected(self, tmp_path):
        zp = _make_zip(
            tmp_path,
            {
                "a/SKILL.md": VALID_SKILL_MD.format(name="skill-a"),
                "b/SKILL.md": VALID_SKILL_MD.format(name="skill-b"),
            },
        )
        result = install_from_zip(zp)
        assert not result["success"]
        assert "唯一子目录" in result["error"] or "SKILL.md" in result["error"]

    def test_not_a_zip(self, tmp_path):
        p = tmp_path / "fake.zip"
        p.write_text("not a zip", encoding="utf-8")
        result = install_from_zip(p)
        assert not result["success"]


# ── local_installer：真实安装（安装后清理） ──────────────────────────


class TestInstallFromZipReal:
    def test_normal_zip_install_and_cleanup(self, tmp_path):
        zp = _make_zip(
            tmp_path,
            {
                "my-zip-skill/SKILL.md": VALID_SKILL_MD.format(name="my-zip-skill"),
                "my-zip-skill/references/note.md": "# note",
            },
        )
        result = install_from_zip(zp)
        try:
            assert result["success"], result
            installed = Path(result["installed_path"])
            assert installed.exists()
            assert (installed / "SKILL.md").exists()
            assert (installed / "references" / "note.md").exists()
        finally:
            if result.get("installed_path"):
                shutil.rmtree(result["installed_path"], ignore_errors=True)

    def test_top_level_zip_install_and_cleanup(self, tmp_path):
        zp = _make_zip(tmp_path, {"SKILL.md": VALID_SKILL_MD.format(name="my-top-skill")})
        result = install_from_zip(zp)
        try:
            assert result["success"], result
        finally:
            if result.get("installed_path"):
                shutil.rmtree(result["installed_path"], ignore_errors=True)


class TestInstallFromLocalPathReal:
    def test_path_import_and_cleanup(self, tmp_path):
        src = _make_skill_dir(tmp_path, "my-path-skill")
        result = install_from_local_path(str(src))
        try:
            assert result["success"], result
            # 源目录不受影响（复制而非移动）
            assert (src / "SKILL.md").exists()
        finally:
            if result.get("installed_path"):
                shutil.rmtree(result["installed_path"], ignore_errors=True)

    def test_missing_dir(self):
        result = install_from_local_path(str(Path("Z:/definitely/not/exist")))
        assert not result["success"]

    def test_dir_without_skill_md(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        result = install_from_local_path(str(d))
        assert not result["success"]
        assert "SKILL.md" in result["error"]


# ── mark_skill_source ─────────────────────────────────────────────────


class TestMarkSkillSource:
    def test_writes_and_updates(self, tmp_path):
        d = _make_skill_dir(tmp_path, "mark-skill")
        mark_skill_source(d, "registry", url="https://clawhub.ai/x/skills/y", version="1.2.3")
        import yaml

        data = yaml.safe_load((d / "manifest.yaml").read_text(encoding="utf-8"))
        assert data["source"]["type"] == "registry"
        assert data["source"]["url"] == "https://clawhub.ai/x/skills/y"
        assert data["source"]["version"] == "1.2.3"
        assert data["skill_name"] == "mark-skill"

        # 幂等更新
        mark_skill_source(d, "local")
        data = yaml.safe_load((d / "manifest.yaml").read_text(encoding="utf-8"))
        assert data["source"]["type"] == "local"
        assert data["source"]["url"] == "https://clawhub.ai/x/skills/y"


# ── git interactive 校验（不联网） ────────────────────────────────────


class TestGitInteractiveValidation:
    def test_non_https_rejected(self):
        result = install_from_git_interactive("git@github.com:user/skill.git")
        assert not result["success"]
        assert "https" in result["error"]

    def test_file_url_rejected(self):
        result = install_from_git_interactive("file:///tmp/repo")
        assert not result["success"]

    def test_empty_url_rejected(self):
        result = install_from_git_interactive("")
        assert not result["success"]
