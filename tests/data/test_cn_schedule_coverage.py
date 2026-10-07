"""CN 调度表覆盖守卫。

「数据中心」页列出 13 个数据域，但调度表曾漏登记 3 个（龙虎榜 / 大宗交易 / 两融），
它们因此永不自动同步、长期停留在旧日期。本测试锁定这些域必须在调度表中登记，
且每条登记都具备可执行的调度要素。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

SCHEDULE_PATH = Path(__file__).resolve().parents[2] / "app" / "data" / "scheduler" / "jobs" / "cn" / "schedule.yaml"

# 曾漏排的三个域：任何新增数据域都应同步检查此表
SCHEDULED_EVENT_DOMAINS = ("dragon_tiger", "block_trade", "margin_trading")


def _schedule() -> dict:
    return yaml.safe_load(SCHEDULE_PATH.read_text(encoding="utf-8"))


def test_schedule_file_exists_and_parses():
    schedule = _schedule()
    assert isinstance(schedule, dict) and schedule, "调度表必须可解析且非空"


@pytest.mark.parametrize("domain", SCHEDULED_EVENT_DOMAINS)
def test_market_event_domain_is_registered(domain):
    assert domain in _schedule(), f"{domain} 未登记定时任务，将永不自动同步"


@pytest.mark.parametrize("domain", SCHEDULED_EVENT_DOMAINS)
def test_registered_entry_is_executable(domain):
    entry = _schedule()[domain]
    for key in ("cron", "timezone", "mode", "depends_on"):
        assert entry.get(key), f"{domain} 缺少调度要素 {key}"
    assert entry["timezone"] == "Asia/Shanghai"
    assert len(entry["cron"].split()) == 5, "cron 必须是 5 段式"
