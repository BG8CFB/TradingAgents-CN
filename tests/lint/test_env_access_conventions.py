"""
环境变量访问约定测试 —— 替代旧 pre-commit bash grep 钩子（跨平台、零依赖）。

规则：`os.getenv()` 只允许出现在配置层白名单模块内，
其余模块应使用 `app/core/config.py` 暴露的配置体系或 `app/core/env.py` 的 `get_env()`。

白名单与 pyproject.toml / AGENTS.md 中的描述保持同步；
新增白名单必须同步更新本文件与 AGENTS.md。
"""
import re
from pathlib import Path

APP_DIR = Path(__file__).parent.parent.parent / "app"

# 白名单：前缀匹配（目录以 / 结尾表示整个子包）
GETENV_WHITELIST = [
    "core/config.py",
    "core/env.py",  # 统一读取入口本身（get_env/has_env_var）
    "core/config_bridge.py",
    "core/config_initializer.py",
    "core/startup_validator.py",
    "engine/config/env_utils.py",
    "llm/config.py",
    "llm/limits.py",  # 输出上限解析器：读 LLM_DEFAULT_MAX_TOKENS 全局回滚开关
    "worker/scheduler_setup.py",
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
