"""
日志规范 lint — 对应 AGENTS.md「Logging 规范」的机器强制。

规则：
1. no-print:      app/ 业务代码禁止 print()（app/scripts/ 一次性脚本豁免；
                  入口引导一律走 logging，配置前由 lastResort 输出 stderr）
2. error-exc-info ratchet: logger.error(...) 必须携带 exc_info=True。
                  存量 84 处（2026-11-02 基线，均不在 except 块内）以棘轮方式收敛：
                  只许减少不许增加；每批修复后手动下调 EXC_INFO_BASELINE。

ratchet 说明：批量修复属治理计划阶段 3（错误处理与日志组），
本 lint 先冻结上限防止债务再生长，新代码一律带 exc_info。
"""
import ast
from pathlib import Path

APP_DIR = Path(__file__).parent.parent.parent / "app"

# 2026-11-02 基线：app/ 下 logger.error( 不带 exc_info 的调用总数（AST 口径）。
# 阶段 3.6 批量补齐 except 块内 369 处后，剩余 84 处均不在 except 块内
# （无活跃异常上下文，exc_info 会打 "NoneType: None" 噪音，暂保留）。
# 每批修复后把该数字下调到当前实测值，只减不增。
EXC_INFO_BASELINE = 84


def _iter_app_py_files():
    for f in APP_DIR.rglob("*.py"):
        if "__pycache__" in f.parts:
            continue
        yield f


def test_no_print_in_app():
    """业务代码禁止 print()（app/scripts/ 一次性脚本除外）。"""
    violations = []
    for f in _iter_app_py_files():
        rel = f.relative_to(APP_DIR).as_posix()
        if rel.startswith("scripts/"):
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "print"
            ):
                violations.append(f"{rel}:{node.lineno}")
    assert not violations, (
        "业务代码禁止 print()，请改用 logging.getLogger(__name__)：\n"
        + "\n".join(violations)
    )


def test_logger_error_exc_info_ratchet():
    """logger.error() 不带 exc_info 的数量不得超过基线（棘轮收敛）。"""
    offenders = []
    for f in _iter_app_py_files():
        rel = f.relative_to(APP_DIR).as_posix()
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "error"
                and isinstance(node.func.value, ast.Name)
            ):
                if not any(kw.arg == "exc_info" for kw in node.keywords):
                    offenders.append(f"{rel}:{node.lineno}")
    count = len(offenders)
    if count > EXC_INFO_BASELINE:
        raise AssertionError(
            f"logger.error 不带 exc_info 的调用 {count} 处，超过基线 {EXC_INFO_BASELINE}"
            "（ERROR 必带 exc_info=True，见 AGENTS.md 日志规范）。\n"
            "存量示例（前 30 处）：\n" + "\n".join(offenders[:30])
        )
    print(f"\n[INFO][exc-info ratchet] {count}/{EXC_INFO_BASELINE}（棘轮只减不增）")
