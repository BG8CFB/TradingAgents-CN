"""
环境变量访问约定测试 —— 替代旧 pre-commit bash grep 钩子（跨平台、零依赖）。

规则：
1. `os.getenv()` 只允许出现在配置层白名单模块内，
   其余模块应使用 `app/core/config.py` 暴露的配置体系或 `app/core/env.py` 的 `get_env()`。
2. `os.environ` 直读/直写同样只允许白名单模块（ast 检查，避免 docstring 误报）。

白名单与 pyproject.toml / AGENTS.md 中的描述保持同步；
新增白名单必须同步更新本文件与 AGENTS.md。
"""
import ast
import re
from pathlib import Path

APP_DIR = Path(__file__).parent.parent.parent / "app"

# 白名单：前缀匹配（目录以 / 结尾表示整个子包）
GETENV_WHITELIST = [
    "__main__.py",  # 进程入口：Windows 编码引导需在日志初始化前写 PYTHONIOENCODING 等
    "main.py",  # 应用入口 lifespan：密钥同步 os.environ（多 worker 共享）
    "core/config.py",
    "core/env.py",  # 统一读取入口本身（get_env/has_env_var）
    "core/config_bridge.py",
    "core/config_initializer.py",
    "core/startup_validator.py",
    "llm/config.py",
    "llm/limits.py",  # 输出上限解析器：读 LLM_DEFAULT_MAX_TOKENS 全局回滚开关
    "worker/scheduler_setup.py",
    "services/secret_service.py",  # 密钥桥接子系统：设计职责就是把受管密钥同步进 os.environ
]

GETENV_PATTERN = re.compile(r"os\.getenv\(")


def _is_whitelisted(rel_posix: str) -> bool:
    return any(rel_posix == w or rel_posix.startswith(w) for w in GETENV_WHITELIST)


def test_no_bare_os_getenv_outside_whitelist():
    violations = []
    for py in APP_DIR.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        rel = py.relative_to(APP_DIR).as_posix()
        if _is_whitelisted(rel):
            continue
        content = py.read_text(encoding="utf-8")
        for lineno, line in enumerate(content.splitlines(), 1):
            if GETENV_PATTERN.search(line):
                violations.append(f"{rel}:{lineno}: {line.strip()}")
    assert not violations, (
        "os.getenv() 只允许在配置层白名单模块中使用，"
        "请改用 app/core/config.py 或 app/core/env.py 的 get_env()：\n"
        + "\n".join(violations)
    )


def test_no_bare_os_environ_outside_whitelist():
    """os.environ 直读/直写只允许白名单模块（ast 检查，docstring 不误报）。"""
    violations = []
    for py in APP_DIR.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        rel = py.relative_to(APP_DIR).as_posix()
        if _is_whitelisted(rel):
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "environ"
                and isinstance(node.value, ast.Name)
                and node.value.id == "os"
            ):
                violations.append(f"{rel}:{node.lineno}: os.environ 访问")
    assert not violations, (
        "os.environ 直读/直写只允许在配置层白名单模块中使用，"
        "读取请改用 app/core/env.py 的 get_env()/get_raw_env()：\n"
        + "\n".join(violations)
    )
