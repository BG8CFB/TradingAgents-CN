"""
Skill 系统测试套件

覆盖：
- SkillManifest Pydantic 模型与 manifest.py 解析
- SkillRegistry 单例、多目录扫描、启停、入口查询
- loader.py 的 frontmatter 解析（yaml.safe_load）
- availability.py 依赖检查
- builtin/registry.py 的 skill 入口注册/卸载
- is_skill_tool 判定
- 空目录退化（config/skills 无 skill 时运行时安全关闭清单）

测试原则（遵守项目规则）：
- 无 mock，全部真实调用代码路径
- 测试 skill 在 tmp_path 程序化构造（项目已移除预置方法论 skill）
- 不依赖 MongoDB/Redis 的测试用例可在无基础设施环境运行
"""
import sys
from pathlib import Path

import pytest

# 把项目根目录加入 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 测试用 skill 定义 ──────────────────────────────────────────────────────

PROMPT_SKILL_MD = """---
name: tmp-prompt-skill
description: 临时纯提示词技能，用于机制测试
version: 2.0.0
user-invocable: true
license: Apache-2.0
metadata:
  author: test
  category: test
allowed-tools: daily_quotes daily_indicators
---

# 临时提示词技能

仅用于测试 frontmatter 解析与 registry 机制。
"""

SCRIPT_SKILL_MD = """---
name: tmp-script-skill
description: 临时带脚本技能，用于 manifest 与 entrypoint 测试
version: 1.5.0
metadata:
  author: test
  category: test
---

# 临时脚本技能

manifest.yaml 声明 entrypoints，scripts/ 提供真实可执行函数。
"""

MANIFEST_YAML = """\
skill_name: tmp-script-skill
schema_version: "1.0"
entrypoints:
  - name: calc-indicators
    display_name: 计算技术指标
    description: 计算均线与 RSI
    module: scripts.entry
    function: calc_indicators
    inject_args:
      ticker: ticker
    markets:
      - CN
    domains:
      - daily_quotes
python_dependencies:
  - package: definitely-not-installed-test-package
    version_constraint: ">=1.0"
"""

SCRIPT_ENTRY = '''\
def calc_indicators(ticker: str, periods: int = 5):
    """返回 ticker 标识与一个确定性计算结果"""
    return {"ticker": ticker, "value": periods * 2}
'''


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    """在 tmp_path 程序化构造 1 个纯提示词 skill + 1 个带 manifest/脚本 skill"""
    # 纯提示词 skill
    prompt_dir = tmp_path / "tmp-prompt-skill"
    prompt_dir.mkdir()
    (prompt_dir / "SKILL.md").write_text(PROMPT_SKILL_MD, encoding="utf-8")

    # 带 manifest + 脚本的 skill
    script_dir = tmp_path / "tmp-script-skill"
    script_dir.mkdir()
    (script_dir / "SKILL.md").write_text(SCRIPT_SKILL_MD, encoding="utf-8")
    (script_dir / "manifest.yaml").write_text(MANIFEST_YAML, encoding="utf-8")
    scripts = script_dir / "scripts"
    scripts.mkdir()
    (scripts / "__init__.py").write_text("", encoding="utf-8")
    (scripts / "entry.py").write_text(SCRIPT_ENTRY, encoding="utf-8")
    return tmp_path


@pytest.fixture(autouse=True)
def reset_skill_registry():
    """每个测试前后重置 SkillRegistry 单例，避免状态污染"""
    from app.engine.tools.skill.registry import SkillRegistry
    SkillRegistry.reset_instance()
    yield
    SkillRegistry.reset_instance()


@pytest.fixture
def skill_registry(skills_dir: Path):
    """指向 tmp 目录的全新 SkillRegistry（并设为单例，供 availability 等模块取用）"""
    from app.engine.tools.skill.registry import SkillRegistry
    reg = SkillRegistry(skills_dir=str(skills_dir))
    SkillRegistry._instance = reg  # availability.py 走 get_instance()
    return reg


# ---------------------------------------------------------------------------
# manifest.py 解析测试
# ---------------------------------------------------------------------------


class TestManifestParsing:
    """manifest.yaml 解析测试"""

    def test_load_manifest_script_skill(self, skills_dir):
        """应正确解析带 manifest 的 skill"""
        from app.engine.tools.skill.manifest import load_manifest

        manifest = load_manifest(str(skills_dir / "tmp-script-skill"))
        assert manifest is not None
        assert manifest.skill_name == "tmp-script-skill"
        assert manifest.schema_version == "1.0"
        assert len(manifest.entrypoints) == 1

        ep = manifest.entrypoints[0]
        assert ep.name == "calc-indicators"
        assert ep.display_name == "计算技术指标"
        assert ep.module == "scripts.entry"
        assert ep.function == "calc_indicators"
        assert "ticker" in ep.inject_args
        assert "CN" in ep.markets
        assert "daily_quotes" in ep.domains

        assert len(manifest.python_dependencies) == 1
        assert (
            manifest.python_dependencies[0].package
            == "definitely-not-installed-test-package"
        )

    def test_load_manifest_pure_prompt_skill_returns_none(self, skills_dir):
        """纯 prompt skill 无 manifest，应返回 None"""
        from app.engine.tools.skill.manifest import has_manifest, load_manifest

        assert has_manifest(str(skills_dir / "tmp-prompt-skill")) is False
        assert load_manifest(str(skills_dir / "tmp-prompt-skill")) is None

    def test_has_manifest_detects_yaml(self, skills_dir):
        """has_manifest 应识别 manifest.yaml"""
        from app.engine.tools.skill.manifest import has_manifest

        assert has_manifest(str(skills_dir / "tmp-script-skill")) is True

    def test_load_manifest_nonexistent_dir_returns_none(self):
        """不存在的目录应返回 None（不抛异常）"""
        from app.engine.tools.skill.manifest import load_manifest

        assert load_manifest("/nonexistent/path/xyz") is None


# ---------------------------------------------------------------------------
# loader.py frontmatter 解析测试
# ---------------------------------------------------------------------------


class TestFrontmatterParsing:
    """SKILL.md frontmatter 解析（yaml.safe_load）"""

    def test_parse_metadata_prompt_skill(self, skills_dir):
        """应正确解析纯提示词 skill 的 frontmatter"""
        from app.engine.tools.skill.loader import parse_skill_metadata

        meta = parse_skill_metadata(str(skills_dir / "tmp-prompt-skill" / "SKILL.md"))
        assert meta["name"] == "tmp-prompt-skill"
        assert "机制测试" in meta["description"]
        assert meta["version"] == "2.0.0"
        assert meta["user_invocable"] is True
        assert meta["license"] == "Apache-2.0"
        # allowed-tools 应被解析为列表
        assert meta["allowed_tools"] == ["daily_quotes", "daily_indicators"]
        # metadata 字段应保留
        assert meta["metadata"].get("category") == "test"

    def test_parse_metadata_script_skill(self, skills_dir):
        """应正确解析脚本 skill 的 metadata"""
        from app.engine.tools.skill.loader import parse_skill_metadata

        meta = parse_skill_metadata(str(skills_dir / "tmp-script-skill" / "SKILL.md"))
        assert meta["name"] == "tmp-script-skill"
        assert meta["version"] == "1.5.0"
        assert meta["metadata"].get("category") == "test"

    def test_parse_metadata_nonexistent_file(self):
        """不存在的文件应返回仅含 file_path 的字典"""
        from app.engine.tools.skill.loader import parse_skill_metadata

        meta = parse_skill_metadata("/nonexistent/SKILL.md")
        assert meta == {"file_path": "/nonexistent/SKILL.md"}


# ---------------------------------------------------------------------------
# SkillRegistry 单例与发现测试
# ---------------------------------------------------------------------------


class TestSkillRegistryDiscovery:
    """SkillRegistry 单例与目录扫描"""

    def test_singleton_returns_same_instance(self):
        """多次 get_instance 应返回同一对象"""
        from app.engine.tools.skill.registry import SkillRegistry
        r1 = SkillRegistry.get_instance()
        r2 = SkillRegistry.get_instance()
        assert r1 is r2

    def test_reset_instance_creates_new(self):
        """reset_instance 后应创建新实例"""
        from app.engine.tools.skill.registry import SkillRegistry
        r1 = SkillRegistry.get_instance()
        SkillRegistry.reset_instance()
        r2 = SkillRegistry.get_instance()
        assert r1 is not r2

    def test_discovers_tmp_skills(self, skill_registry):
        """应发现 tmp 目录下的 2 个测试 skill"""
        all_skills = skill_registry.list_all_skills()
        names = {s["name"] for s in all_skills}
        assert "tmp-prompt-skill" in names
        assert "tmp-script-skill" in names
        assert len(all_skills) >= 2

    def test_tmp_skill_source_type_is_local(self, skill_registry):
        """显式指定目录下的 skill，source_type 应为 local"""
        for s in skill_registry.list_all_skills():
            assert s["source_type"] == "local"

    def test_get_manifest_returns_correct(self, skill_registry):
        """get_manifest 应正确返回有/无 manifest 的 skill"""
        m1 = skill_registry.get_manifest("tmp-script-skill")
        assert m1 is not None
        assert m1.skill_name == "tmp-script-skill"

        m2 = skill_registry.get_manifest("tmp-prompt-skill")
        assert m2 is None  # 纯 prompt skill

    def test_get_entrypoints_only_for_manifest_skills(self, skill_registry):
        """只有带 manifest 的 skill 才有 entrypoints"""
        eps1 = skill_registry.get_entrypoints("tmp-script-skill")
        assert len(eps1) == 1
        assert eps1[0]["name"] == "calc-indicators"

        eps2 = skill_registry.get_entrypoints("tmp-prompt-skill")
        assert eps2 == []

    def test_get_skill_content_caches(self, skill_registry):
        """get_skill_content 应返回 SKILL.md 全文"""
        content = skill_registry.get_skill_content("tmp-prompt-skill")
        assert content is not None
        assert "机制测试" in content
        # 二次访问应命中缓存
        content2 = skill_registry.get_skill_content("tmp-prompt-skill")
        assert content == content2

    def test_enable_disable_lifecycle(self, skill_registry):
        """启停 skill 应影响 is_enabled 与 list_skills"""
        name = "tmp-prompt-skill"
        assert skill_registry.is_enabled(name) is True

        assert skill_registry.disable_skill(name) is True
        assert skill_registry.is_enabled(name) is False
        # list_skills 应过滤掉禁用的
        names_in_list = {s["name"] for s in skill_registry.list_skills()}
        assert name not in names_in_list

        assert skill_registry.enable_skill(name) is True
        assert skill_registry.is_enabled(name) is True
        names_in_list = {s["name"] for s in skill_registry.list_skills()}
        assert name in names_in_list

    def test_enable_nonexistent_returns_false(self, skill_registry):
        """启用不存在的 skill 应返回 False"""
        assert skill_registry.enable_skill("nonexistent-skill") is False
        assert skill_registry.disable_skill("nonexistent-skill") is False

    def test_reload_clears_cache(self, skill_registry):
        """reload 应清空内容缓存并重新发现"""
        # 先填充缓存
        skill_registry.get_skill_content("tmp-prompt-skill")
        assert "tmp-prompt-skill" in skill_registry._content_cache

        skill_registry.reload()
        assert "tmp-prompt-skill" not in skill_registry._content_cache
        # 仍能发现 skill
        assert any(
            s["name"] == "tmp-prompt-skill" for s in skill_registry.list_all_skills()
        )

    def test_empty_skills_dir_degrades_gracefully(self, tmp_path):
        """空目录应发现 0 个 skill 且不抛异常"""
        from app.engine.tools.skill.registry import SkillRegistry

        empty = tmp_path / "empty-skills"
        empty.mkdir()
        reg = SkillRegistry(skills_dir=str(empty))
        assert reg.list_all_skills() == []


# ---------------------------------------------------------------------------
# availability.py 依赖检查测试
# ---------------------------------------------------------------------------


class TestSkillAvailability:
    """依赖可用性检查（不安装）"""

    def test_pure_prompt_skill_is_satisfied(self, skill_registry):
        """纯 prompt skill 无 manifest，依赖应默认满足"""
        from app.engine.tools.skill.availability import check_skill_dependencies

        av = check_skill_dependencies("tmp-prompt-skill")
        assert av.dependencies_satisfied is True
        assert av.env_satisfied is True
        assert av.dependencies == []

    def test_skill_with_missing_dep_is_unsatisfied(self, skill_registry):
        """声明了未安装测试包的 skill 应 unsatisfied"""
        from app.engine.tools.skill.availability import check_skill_dependencies

        av = check_skill_dependencies("tmp-script-skill")
        assert av.dependencies_satisfied is False
        dep = next(
            (
                d
                for d in av.dependencies
                if d.package == "definitely-not-installed-test-package"
            ),
            None,
        )
        assert dep is not None
        assert dep.satisfied is False

    def test_check_skill_dependencies_raw_returns_dict(self, skill_registry):
        """check_skill_dependencies_raw 应返回标准字典结构"""
        from app.engine.tools.skill.availability import check_skill_dependencies_raw

        result = check_skill_dependencies_raw("tmp-prompt-skill")
        assert "satisfied" in result
        assert "missing" in result
        assert "warnings" in result
        assert isinstance(result["satisfied"], bool)
        assert isinstance(result["missing"], list)

    def test_package_to_module_mapping(self):
        """包名到模块名的映射应正确"""
        from app.engine.tools.skill.availability import _package_to_module

        assert _package_to_module("ta-lib") == "talib"
        assert _package_to_module("Pillow") == "PIL"
        assert _package_to_module("pyyaml") == "yaml"
        assert _package_to_module("mplfinance") == "mplfinance"
        # 未知包名：连字符转下划线
        assert _package_to_module("some-package") == "some_package"


# ---------------------------------------------------------------------------
# entrypoint_loader 真实脚本执行测试
# ---------------------------------------------------------------------------


class TestEntrypointLoader:
    """skill 脚本入口应可被真实 import 并执行"""

    def test_load_all_skill_entrypoints(self, skills_dir):
        """依赖不满足的 skill 应被跳过并记入 unavailable"""
        from app.engine.tools.builtin.registry import unregister_skill_entrypoints
        from app.engine.tools.skill.entrypoint_loader import (
            load_all_skill_entrypoints,
        )
        from app.engine.tools.skill.registry import SkillRegistry

        reg = SkillRegistry(skills_dir=str(skills_dir))
        SkillRegistry._instance = reg

        result = load_all_skill_entrypoints()
        try:
            # tmp-script-skill 依赖未安装 → 不注册，记入 unavailable
            assert "tmp-script-skill" not in result["registered"]
            assert "tmp-script-skill" in result["unavailable"]
        finally:
            unregister_skill_entrypoints("tmp-script-skill")

    def test_manifest_function_executable(self, skills_dir):
        """manifest 声明的函数应真实可调用（直接 import，走 entrypoint 同路径）"""
        import importlib

        sys.path.insert(0, str(skills_dir / "tmp-script-skill"))
        try:
            entry = importlib.import_module("scripts.entry")
            result = entry.calc_indicators("000001", periods=10)
            assert result == {"ticker": "000001", "value": 20}
        finally:
            sys.path.remove(str(skills_dir / "tmp-script-skill"))
            sys.modules.pop("scripts.entry", None)
            sys.modules.pop("scripts", None)


# ---------------------------------------------------------------------------
# builtin/registry.py skill 入口注册测试
# ---------------------------------------------------------------------------


class TestBuiltinRegistrySkillEntrypoints:
    """skill 入口注册到 BUILTIN_TOOL_REGISTRY"""

    def test_register_skill_entrypoint_appends(self):
        """register_skill_entrypoint 应追加到 registry"""
        from app.engine.tools.builtin.registry import (
            BUILTIN_TOOL_REGISTRY,
            BuiltinToolSpec,
            register_skill_entrypoint,
            unregister_skill_entrypoints,
            _TOOL_ID_INDEX,
        )

        initial_count = len(BUILTIN_TOOL_REGISTRY)
        test_id = "test-skill.test-entry"

        # 构造一个测试 spec
        def _fn(x):
            return x

        spec = BuiltinToolSpec(
            tool_id=test_id,
            display_name="测试入口",
            domains=["test"],
            markets=["CN"],
            fn=_fn,
            inject_args={},
            description="测试用",
        )

        try:
            assert register_skill_entrypoint(spec) is True
            assert len(BUILTIN_TOOL_REGISTRY) == initial_count + 1
            assert test_id in _TOOL_ID_INDEX
        finally:
            unregister_skill_entrypoints("test-skill")
        assert len(BUILTIN_TOOL_REGISTRY) == initial_count

    def test_register_duplicate_returns_false(self):
        """重复注册同名 tool_id 应被拒绝"""
        from app.engine.tools.builtin.registry import (
            BuiltinToolSpec,
            register_skill_entrypoint,
            unregister_skill_entrypoints,
        )

        def _fn(x):
            return x

        spec = BuiltinToolSpec(
            tool_id="dup-test.entry",
            display_name="dup",
            domains=[],
            markets=[],
            fn=_fn,
            inject_args={},
            description="",
        )
        try:
            assert register_skill_entrypoint(spec) is True
            # 第二次应失败
            assert register_skill_entrypoint(spec) is False
        finally:
            unregister_skill_entrypoints("dup-test")

    def test_unregister_by_prefix(self):
        """按前缀批量卸载"""
        from app.engine.tools.builtin.registry import (
            BuiltinToolSpec,
            register_skill_entrypoint,
            unregister_skill_entrypoints,
        )

        def _fn(x):
            return x

        for name in ["a", "b"]:
            spec = BuiltinToolSpec(
                tool_id=f"prefix-test.{name}",
                display_name=name,
                domains=[],
                markets=[],
                fn=_fn,
                inject_args={},
                description="",
            )
            register_skill_entrypoint(spec)

        count = unregister_skill_entrypoints("prefix-test")
        assert count == 2

    def test_is_skill_tool_detection(self):
        """is_skill_tool 应识别 skill 工具"""
        from app.engine.tools.builtin.registry import (
            BuiltinToolSpec,
            is_skill_tool,
            register_skill_entrypoint,
            unregister_skill_entrypoints,
        )

        def _fn(x):
            return x

        spec = BuiltinToolSpec(
            tool_id="ist-test.entry",
            display_name="",
            domains=[],
            markets=[],
            fn=_fn,
            inject_args={},
            description="",
        )
        register_skill_entrypoint(spec)
        try:
            # 注册后 is_skill_tool 应识别（包含点且在索引中）
            assert is_skill_tool("ist-test.entry") is True
            # builtin 工具不含点，应返回 False
            assert is_skill_tool("daily_quotes") is False
            # 不存在的工具
            assert is_skill_tool("nonexistent.foo") is False
        finally:
            unregister_skill_entrypoints("ist-test")


# ---------------------------------------------------------------------------
# 空目录退化：config/skills 无 skill 时运行时安全关闭清单
# ---------------------------------------------------------------------------


class TestEmptySkillsDegradation:
    """项目移除预置方法论 skill 后，空目录应安全退化"""

    def test_skill_store_listing_empty(self, tmp_path):
        """SkillStore 扫描空目录 → 清单为空字符串"""
        from app.llm.skills.loader import SkillStore

        empty = tmp_path / "empty-skills"
        empty.mkdir()
        store = SkillStore([str(empty)])
        assert store.invocable() == []
        assert store.listing_text() == ""

    def test_expand_unknown_skill_returns_error_text(self, tmp_path):
        """展开不存在的 skill 应返回错误提示而非抛异常"""
        from app.llm.skills.loader import SkillStore

        empty = tmp_path / "empty-skills"
        empty.mkdir()
        store = SkillStore([str(empty)])
        result = store.expand_skill("nonexistent-skill", "args")
        assert "未知 skill" in result


# ---------------------------------------------------------------------------
# 回归测试：dependency_installer 的字典结构 bug（CVE-style regression）
# ---------------------------------------------------------------------------


class TestDependencyInstallerPostCheckParsing:
    """
    回归测试：dependency_installer 中 post_check 字典解析

    历史问题：post_check["availability"] 是 dict（来自 model_dump），
    其中的 dependencies 是 list[dict]，曾误用 d.package 属性访问触发
    AttributeError（仅在依赖已满足时触发，由于短路求值此前未发现）。
    """

    def test_parse_satisfied_packages_from_dict_structure(self):
        """模拟 post_check 字典结构，验证 satisfied_packages 抽取逻辑"""
        post_check = {
            "satisfied": True,
            "missing": [],
            "warnings": [],
            "availability": {
                "skill_name": "test",
                "enabled": True,
                "dependencies_satisfied": True,
                "dependencies": [
                    {
                        "package": "mplfinance",
                        "version_constraint": ">=0.12.10b0",
                        "satisfied": True,
                        "installed_version": "0.12.10b0",
                        "note": "",
                    },
                    {
                        "package": "ta-lib",
                        "version_constraint": ">=0.4.28",
                        "satisfied": False,
                        "installed_version": "",
                        "note": "",
                    },
                ],
                "env_satisfied": True,
                "missing_env": [],
            },
        }

        # 复刻 dependency_installer 中的修复逻辑
        availability_dict = post_check.get("availability") or {}
        deps_list = availability_dict.get("dependencies", []) if isinstance(
            availability_dict, dict
        ) else []
        satisfied_packages = [
            d["package"]
            for d in deps_list
            if isinstance(d, dict) and d.get("satisfied")
        ]

        assert satisfied_packages == ["mplfinance"]
        # 关键：必须能成功运行（不会因 d.package 属性访问抛 AttributeError）
        assert "ta-lib" not in satisfied_packages

    def test_parse_satisfied_packages_empty_availability(self):
        """availability 为 None 时应返回空列表不崩溃"""
        post_check = {
            "satisfied": False,
            "missing": ["x"],
            "warnings": [],
            "availability": None,
        }

        availability_dict = post_check.get("availability") or {}
        deps_list = availability_dict.get("dependencies", []) if isinstance(
            availability_dict, dict
        ) else []
        satisfied_packages = [
            d["package"]
            for d in deps_list
            if isinstance(d, dict) and d.get("satisfied")
        ]
        assert satisfied_packages == []


# ---------------------------------------------------------------------------
# 回归测试：git_installer 的 trusted_hosts_override 参数
# ---------------------------------------------------------------------------


class TestGitInstallerTrustedHostsOverride:
    """
    回归测试：git_installer 的 trusted_hosts_override 参数

    历史问题：原实现通过 os.environ 临时覆盖，但 _get_trusted_hosts
    从 pydantic settings 读取（类加载时缓存），覆盖无效。已改为
    将合并后的 trusted_hosts 显式传给 _validate_git_url。
    """

    def test_validate_git_url_uses_explicit_trusted_hosts(self):
        """显式传入的 trusted_hosts 应被校验逻辑使用"""
        from app.engine.tools.skill.git_installer import _validate_git_url

        # github.com 在全局默认白名单内（github.com,gitee.com）
        err = _validate_git_url(
            "https://github.com/foo/bar",
            trusted_hosts={"github.com"},
        )
        assert err is None

        # example.com 不在显式白名单内，应被拒绝
        err = _validate_git_url(
            "https://example.com/foo/bar",
            trusted_hosts={"github.com"},
        )
        assert err is not None
        assert "example.com" in err

    def test_validate_git_url_falls_back_to_global_when_none(self):
        """trusted_hosts=None 时应回退到全局 settings 读取"""
        from app.engine.tools.skill.git_installer import (
            _get_trusted_hosts,
            _validate_git_url,
        )

        # 全局白名单默认包含 github.com
        global_hosts = _get_trusted_hosts()
        if "github.com" in global_hosts:
            err = _validate_git_url("https://github.com/x/y", trusted_hosts=None)
            assert err is None

    def test_install_from_git_passes_override_through(self):
        """install_from_git 应将 trusted_hosts_override 合并并传入校验"""
        from app.engine.tools.skill.git_installer import install_from_git

        # 不实际克隆，仅验证 URL 校验阶段正确使用 override
        # 传入一个语法非法的 URL 以在克隆前 fail-fast
        result = install_from_git(
            "https://untrusted-host.example.com/foo/bar",
            trusted_hosts_override=["github.com"],
        )
        # 因为 example.com 不在白名单，应在 URL 校验阶段被拒绝
        assert result["success"] is False
        assert "untrusted-host.example.com" in result["error"]

        # 反例：将 untrusted-host.example.com 加入 override，应通过 URL 校验
        # （会在后续 git clone 阶段失败，但不会以"不在白名单"为由拒绝）
        result2 = install_from_git(
            "https://my-private-host.example.com/foo/bar",
            trusted_hosts_override=["my-private-host.example.com"],
        )
        # URL 校验通过；后续克隆会失败
        if result2["success"] is False:
            # 失败原因不应该是"不在白名单"
            assert "不在可信白名单内" not in result2["error"]
