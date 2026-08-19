"""
Data access convention tests — 消费层数据访问纪律（架构铁律的 lint 化）。

规则（对应架构文档「数据层发展路线」）：
1. no-sdk-import:       消费方禁止直接 import 第三方数据源 SDK
2. no-sources-import:   消费方禁止 import app.data.sources / app.data.processor
                        （生产侧 worker 与数据层自身豁免）
3. no-db-handle-in-services: services/engine 禁止直连 MongoDB 句柄
                        （应用层集合走应用仓储，业务数据必须经 DataInterface）

豁免机制：文件头注释 `# data-access-exempt: <原因>`（前 10 行内），
lint 识别该标记放行并在输出中汇总，防止白名单漂移且可审计。

enforcement 说明：数据层标准化改造（Phase 4 消费层收敛）完成前，
ENFORCE=False 为 warn 模式（只打印不失败）；收敛完成后改为 True。
"""
import ast
from pathlib import Path

APP_DIR = Path(__file__).parent.parent.parent / "app"

# ENFORCE=True: 强制模式（Phase 4 消费层收敛完成后启用）
ENFORCE = True

# 规则 1：禁止的数据源 SDK 顶层包名
FORBIDDEN_SDKS = {"tushare", "akshare", "baostock", "yfinance", "finnhub", "alpha_vantage"}

# 规则 1/2 白名单目录/文件（相对 app/ 的 posix 路径前缀）
SDK_IMPORT_WHITELIST_PREFIXES = (
    "data/sources",          # 数据源层自身
    "services/config/data_source_service.py",  # 数据源连通性测试功能
)
SOURCES_IMPORT_WHITELIST_PREFIXES = (
    "data/",                 # 数据层内部
    "worker/",               # 生产侧同步 worker（写路径）
)

# 规则 3 检查目录
DB_HANDLE_SCAN_DIRS = ("services", "engine")


def _iter_py_files(scan_root: Path):
    for f in scan_root.rglob("*.py"):
        if "__pycache__" in f.parts:
            continue
        yield f


def _relpath(f: Path) -> str:
    return f.relative_to(APP_DIR).as_posix()


def _has_exempt_marker(filepath: Path) -> bool:
    try:
        head = "\n".join(
            filepath.read_text(encoding="utf-8").splitlines()[:10]
        )
    except (OSError, UnicodeDecodeError):
        return False
    return "# data-access-exempt:" in head


def _imported_roots(tree: ast.Module):
    """返回文件 import 的顶层包名集合与 'from x.y' 的完整点路径列表。"""
    tops, froms = set(), []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                tops.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            froms.append(node.module)
            tops.add(node.module.split(".")[0])
    return tops, froms


def _assert_no_violations(violations, rule_name):
    if not violations:
        return
    if ENFORCE:
        raise AssertionError(
            f"[{rule_name}] 发现 {len(violations)} 处违规:\n"
            + "\n".join(f"  {v}" for v in violations)
        )
    print(f"\n[WARN][{rule_name}] {len(violations)} 处存量违规（ENFORCE=False，仅提示）:")
    for v in violations:
        print(f"  {v}")


def test_no_sdk_import_in_consumers():
    """消费方禁止直接 import 数据源 SDK（tushare/akshare/yfinance 等）。"""
    violations = []
    scan_root = APP_DIR
    for f in _iter_py_files(scan_root):
        rel = _relpath(f)
        if rel.startswith(SDK_IMPORT_WHITELIST_PREFIXES):
            continue
        if _has_exempt_marker(f):
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"))
        tops, _ = _imported_roots(tree)
        hit = tops & FORBIDDEN_SDKS
        if hit:
            violations.append(f"{rel}: import 数据源 SDK {sorted(hit)}")
    _assert_no_violations(violations, "no-sdk-import")


def test_no_sources_import_in_consumers():
    """消费方禁止 import app.data.sources / app.data.processor 内部实现。"""
    violations = []
    for f in _iter_py_files(APP_DIR):
        rel = _relpath(f)
        if rel.startswith(SOURCES_IMPORT_WHITELIST_PREFIXES):
            continue
        if _has_exempt_marker(f):
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"))
        _, froms = _imported_roots(tree)
        for mod in froms:
            if mod.startswith(("app.data.sources", "app.data.processor")):
                violations.append(f"{rel}: from {mod} import ...")
    _assert_no_violations(violations, "no-sources-import")


def test_no_db_handle_in_services_and_engine():
    """services/engine 禁止直连 MongoDB 句柄；豁免需文件头标记。"""
    forbidden_names = {
        "get_mongo_db", "get_mongo_db_sync", "get_motor_db",
        "AsyncIOMotorClient", "MongoClient", "get_mongo_client",
    }
    violations, exemptions = [], []
    for sub in DB_HANDLE_SCAN_DIRS:
        scan_dir = APP_DIR / sub
        if not scan_dir.exists():
            continue
        for f in _iter_py_files(scan_dir):
            rel = _relpath(f)
            if _has_exempt_marker(f):
                exemptions.append(rel)
                continue
            content = f.read_text(encoding="utf-8")
            tree = ast.parse(content)
            found = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id in forbidden_names:
                    found.add(node.id)
                elif isinstance(node, ast.Attribute) and node.attr in forbidden_names:
                    found.add(node.attr)
            if found:
                violations.append(f"{rel}: 使用 MongoDB 直连句柄 {sorted(found)}")
    if exemptions:
        print(f"\n[INFO][no-db-handle] {len(exemptions)} 个文件声明豁免: {exemptions}")
    _assert_no_violations(violations, "no-db-handle-in-services")
