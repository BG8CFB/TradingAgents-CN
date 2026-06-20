"""
健康检查 / 状态消息映射表的单元测试。

覆盖内容：
- app.routers.health.get_version() 优先从 pyproject.toml 读取
- app.services.analysis_service._TASK_STATUS_MESSAGES 覆盖所有可能状态
- 映射表内不存在 "任务{status}中..." 这类语法错误模板
"""

from __future__ import annotations

import pytest

from app.routers.health import get_version
from app.services.analysis_service import _TASK_STATUS_MESSAGES


def test_get_version_reads_pyproject_toml():
    """get_version 必须返回 pyproject.toml 中的版本号，不依赖已安装包元数据。"""
    import re
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    pyproject = project_root / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    assert m, "pyproject.toml 必须定义 version 字段"

    expected = m.group(1)
    actual = get_version()
    assert actual == expected, f"get_version()={actual} != pyproject.toml={expected}"


def test_get_version_is_not_unknown_placeholder():
    """get_version 不应返回 unknown 占位值（pyproject.toml 应存在）。"""
    v = get_version()
    assert not v.endswith("unknown"), f"版本未知，可能 pyproject.toml 缺失：{v}"


@pytest.mark.parametrize(
    "status",
    ["pending", "queued", "running", "completed", "failed", "cancelled", "canceled"],
)
def test_status_message_covers_all_common_statuses(status: str):
    """映射表应覆盖所有可能从 DB 读到的任务状态。"""
    assert status in _TASK_STATUS_MESSAGES, f"状态 '{status}' 未在映射表中"


def test_status_messages_have_no_english_status_inlined():
    """映射表的消息中不应残留英文状态词混入中文（防 "任务completed中..." 回归）。"""
    english_statuses = {
        "pending",
        "queued",
        "running",
        "completed",
        "failed",
        "cancelled",
        "canceled",
    }
    for key, msg in _TASK_STATUS_MESSAGES.items():
        for s in english_statuses:
            assert s not in msg, f"消息 '{msg}' 中残留英文状态词 '{s}'（key={key}）"


def test_status_message_for_completed_is_not_progressive():
    """已完成任务的消息不应包含 '中...' 这类进行式后缀。"""
    msg = _TASK_STATUS_MESSAGES.get("completed", "")
    assert "中" not in msg and "..." not in msg, f"completed 消息 '{msg}' 不应含进行式"


def test_status_messages_are_chinese():
    """所有消息必须是中文，对前端用户友好。"""
    for key, msg in _TASK_STATUS_MESSAGES.items():
        # 至少包含一个中文字符
        assert any("一" <= c <= "鿿" for c in msg), f"消息 '{msg}' (key={key}) 非中文"


def test_status_messages_contain_no_format_placeholders():
    """消息不应含 {status} 等格式占位符，避免 .format() 调用产生意外替换。"""
    for key, msg in _TASK_STATUS_MESSAGES.items():
        assert "{" not in msg and "}" not in msg, (
            f"消息 '{msg}' (key={key}) 含格式占位符，可能被误 .format()"
        )


def test_get_version_falls_back_to_package_metadata_if_pyproject_missing(monkeypatch):
    """pyproject.toml 路径不可读时，应降级到包元数据（不应崩溃）。"""
    from app.routers import health

    class _MissingPath:
        def is_file(self) -> bool:
            return False

    monkeypatch.setattr(health, "_PYPROJECT", _MissingPath())
    v = health.get_version()
    # 已安装包返回 1.3.2；未安装环境返回 "0.0.0+unknown"。两者都合法。
    assert isinstance(v, str) and v, f"降级路径返回空值：{v!r}"
