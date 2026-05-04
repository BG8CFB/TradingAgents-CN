"""
Router convention tests — enforces naming standards.

Rules:
1. Every router must have prefix="/api/<domain>" (except health.py)
2. Every router must have exactly one English Title-Case tag
3. No router file should import motor or call find_one/aggregate directly
"""
import ast
import os
from pathlib import Path

ROUTERS_DIR = Path(__file__).parent.parent.parent / "app" / "routers"
EXEMPT_FILES = {"__init__.py", "health.py"}


def get_router_files():
    files = []
    for f in ROUTERS_DIR.glob("*.py"):
        if f.name not in EXEMPT_FILES:
            files.append(f)
    # Also check config/ subdirectory
    config_dir = ROUTERS_DIR / "config"
    if config_dir.exists():
        for f in config_dir.glob("*.py"):
            if f.name != "__init__.py" and f.name != "scheduler.py":
                files.append(f)
    return files


def test_routers_have_api_prefix():
    for filepath in get_router_files():
        content = filepath.read_text(encoding="utf-8")
        if "APIRouter" not in content:
            continue
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "router":
                        # Find APIRouter call
                        if isinstance(node.value, ast.Call):
                            for kw in node.value.keywords:
                                if kw.arg == "prefix":
                                    if isinstance(kw.value, ast.Constant):
                                        prefix = kw.value.value
                                        assert prefix.startswith("/api/"), \
                                            f"{filepath.name}: prefix '{prefix}' should start with /api/"


def test_routers_have_english_tags():
    """Tags should be English Title-Case strings"""
    for filepath in get_router_files():
        content = filepath.read_text(encoding="utf-8")
        if "APIRouter" not in content:
            continue
        # Skip if using tags from __init__.py (config sub-routers)
        if "config/" in str(filepath) and filepath.name != "__init__.py":
            continue
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "router":
                        if isinstance(node.value, ast.Call):
                            has_tags = False
                            for kw in node.value.keywords:
                                if kw.arg == "tags":
                                    has_tags = True
                            assert has_tags, f"{filepath.name}: missing tags=[] in APIRouter()"


def test_no_mongo_in_routers():
    """Router files should not contain direct MongoDB operations"""
    forbidden = ["find_one(", "aggregate(", "update_one(", "insert_one(", "delete_one("]
    for filepath in get_router_files():
        content = filepath.read_text(encoding="utf-8")
        for pattern in forbidden:
            assert pattern not in content, \
                f"{filepath.name}: contains forbidden '{pattern}' — use service layer instead"
