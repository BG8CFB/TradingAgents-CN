"""
Router convention tests — enforces naming standards.

Rules:
1. Every router must have prefix="/api/<domain>" (except health.py)
2. Every router must have English Title-Case tags (e.g. "CN Data Management")
3. No router file should call MongoDB methods directly
   (find/find_one/aggregate/count_documents/insert_*/update_*/delete_*/distinct/bulk_write)

Coverage: rglob scans ALL subdirectories under app/routers/
(including cn/ hk/ us/ config/ sync/ — 历史上只扫顶层与 config/，子目录曾逃离检查).
"""
import ast
import re
from pathlib import Path

ROUTERS_DIR = Path(__file__).parent.parent.parent / "app" / "routers"
# __init__.py 聚合导出；health.py 双路径特例（存在即豁免，见 AGENTS.md）；
# config/scheduler.py 为空占位（死代码清偿在治理计划中）
EXEMPT_FILENAMES = {"__init__.py", "health.py", "scheduler.py"}

# 英文 Title-Case：每词首字母大写（允许全大写缩写词如 CN/HK/US/API）
TAG_TITLE_CASE = re.compile(r"^[A-Z][A-Za-z0-9]*( [A-Z][A-Za-z0-9]*)*$")

# Mongo 直连方法（带点前缀避免误匹配无关的 find( 字样）
FORBIDDEN_MONGO_CALLS = [
    ".find(", ".find_one(", ".aggregate(",
    ".count_documents(", ".distinct(", ".bulk_write(",
    ".insert_one(", ".insert_many(",
    ".update_one(", ".update_many(",
    ".delete_one(", ".delete_many(",
]


def get_router_files():
    """递归收集全部路由文件（含 cn/hk/us/config 等子目录）。"""
    return [
        f for f in ROUTERS_DIR.rglob("*.py")
        if f.name not in EXEMPT_FILENAMES
    ]


def _router_assignments(tree: ast.Module):
    """产出 (node, apirouter_call) 对：`router = APIRouter(...)` 赋值。"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "router":
                if isinstance(node.value, ast.Call):
                    yield node.value


def test_routers_have_api_prefix():
    for filepath in get_router_files():
        content = filepath.read_text(encoding="utf-8")
        if "APIRouter" not in content:
            continue
        tree = ast.parse(content)
        for call in _router_assignments(tree):
            for kw in call.keywords:
                if kw.arg == "prefix":
                    if isinstance(kw.value, ast.Constant):
                        prefix = kw.value.value
                        assert prefix.startswith("/api/"), (
                            f"{filepath.relative_to(ROUTERS_DIR)}: prefix '{prefix}'"
                            " should start with /api/"
                        )


def test_routers_have_english_title_case_tags():
    """Tags 必须存在且为英文 Title-Case 字符串字面量。"""
    for filepath in get_router_files():
        content = filepath.read_text(encoding="utf-8")
        if "APIRouter" not in content:
            continue
        tree = ast.parse(content)
        rel = filepath.relative_to(ROUTERS_DIR)
        found_router = False
        for call in _router_assignments(tree):
            found_router = True
            tags_kw = next((kw for kw in call.keywords if kw.arg == "tags"), None)
            assert tags_kw is not None, f"{rel}: missing tags=[] in APIRouter()"
            assert isinstance(tags_kw.value, (ast.List, ast.Tuple)), (
                f"{rel}: tags 应为字符串字面量列表"
            )
            for elt in tags_kw.value.elts:
                assert isinstance(elt, ast.Constant) and isinstance(elt.value, str), (
                    f"{rel}: tags 应为字符串字面量"
                )
                assert TAG_TITLE_CASE.match(elt.value), (
                    f"{rel}: tag '{elt.value}' 非英文 Title-Case"
                )
        # 文件内 import 了 APIRouter 却没找到 router 赋值的（如动态构建）也要暴露
        if not found_router and "APIRouter(" in content:
            raise AssertionError(f"{rel}: 检测到 APIRouter( 调用但无法解析 router 赋值")


def test_no_mongo_in_routers():
    """Router files should not contain direct MongoDB operations"""
    for filepath in get_router_files():
        content = filepath.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_MONGO_CALLS:
            assert pattern not in content, (
                f"{filepath.relative_to(ROUTERS_DIR)}: contains forbidden"
                f" '{pattern}' — use service layer instead"
            )
