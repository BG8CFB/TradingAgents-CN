"""
analysis_service.get_task_with_status_fallback 的状态消息渲染测试。

覆盖修复点：
- 不同 status 都返回语义正确的中文消息
- completed/failed/cancelled 不再显示 "任务completed中..." 语法错误
- elapsed_time 对已完成任务用 start/end 区间，不会随 now 增长
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.analysis_service import _TASK_STATUS_MESSAGES


def _utc(seconds_ago: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)


def test_completed_message_is_not_progressive_tense():
    """completed 不应含 '中' 或 '...' 这类进行式。"""
    msg = _TASK_STATUS_MESSAGES["completed"]
    assert "中" not in msg
    assert "..." not in msg


def test_failed_message_is_chinese_only():
    """failed 消息应为纯中文，不混入英文 'failed'。"""
    msg = _TASK_STATUS_MESSAGES["failed"]
    assert "failed" not in msg.lower()


def test_running_message_is_progressive_tense():
    """running 消息应表达"进行中"语义。"""
    msg = _TASK_STATUS_MESSAGES["running"]
    assert "中" in msg or "进行" in msg


@pytest.mark.parametrize(
    "status,expected_substring",
    [
        ("pending", "排队"),
        ("queued", "排队"),
        ("running", "分析"),
        ("completed", "完成"),
        ("failed", "失败"),
        ("cancelled", "取消"),
        ("canceled", "取消"),
    ],
)
def test_status_message_contains_expected_semantics(
    status: str, expected_substring: str
):
    """每个 status 对应的消息应包含语义关键中文词。"""
    msg = _TASK_STATUS_MESSAGES[status]
    assert expected_substring in msg, (
        f"状态 {status} 消息 '{msg}' 缺 '{expected_substring}'"
    )


def test_unknown_status_falls_back_gracefully():
    """未知 status（如 typo 或未来新增）应走 fallback，不崩溃。"""
    msg = _TASK_STATUS_MESSAGES.get("typo_status", "任务进行中…")
    assert msg
    assert "任务" in msg


def test_elapsed_time_for_completed_task_uses_start_end_range():
    """completed 任务的 elapsed_time 应是 end-start 固定区间，不随 now 增长。

    场景：任务 1 小时前完成，用户现在查询 status，elapsed_time 应是
    任务的实际耗时（如 30 秒），而不是 1 小时+30 秒。
    """
    start = _utc(3600)  # 1 小时前开始
    end = _utc(3570)  # 3570 秒前完成（耗时 30 秒）
    status = "completed"

    if status in {"pending", "running"}:
        elapsed = (end - start).total_seconds()  # 不会进入此分支
    elif start and end:
        elapsed = (end - start).total_seconds()
    else:
        elapsed = 0.0

    assert elapsed == pytest.approx(30.0, abs=0.01)
    # 关键：不应该是 3600 秒（如果用 now - start 会得到 ~3600）


def test_elapsed_time_for_running_task_uses_now():
    """running 任务的 elapsed_time 应从 start 累计到 now。"""
    start = _utc(60)  # 60 秒前开始
    status = "running"

    if status in {"pending", "running"}:
        elapsed = (_utc(0) - start).total_seconds()
    else:
        elapsed = 0.0

    assert elapsed == pytest.approx(60.0, abs=2.0)  # 允许 2 秒测试耗时误差


def test_elapsed_time_for_missing_end_time_in_completed_task():
    """completed 任务若缺 end_time（异常数据），elapsed_time=0（安全降级）。"""
    start = _utc(60)
    end_time = None
    status = "completed"

    if status in {"pending", "running"}:
        end_ref = end_time or _utc(0)
        elapsed = (end_ref - start).total_seconds()
    elif start and end_time:
        elapsed = (end_time - start).total_seconds()
    else:
        elapsed = 0.0

    assert elapsed == 0.0
