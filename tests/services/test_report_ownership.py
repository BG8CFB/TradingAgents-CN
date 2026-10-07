"""分析报告归属（user_id）的守卫测试。

报告列表/详情接口都按 `user_id` 过滤（`reports_service._build_list_query` 在传入
user_id 时做精确匹配，路由传 `user["id"]`）。写入侧若漏落该字段，报告就是
「存进库了但列表里看不到」——本测试锁定写入路径必须落归属。
"""

from __future__ import annotations

import re
from pathlib import Path

SERVICE_PATH = Path(__file__).resolve().parents[2] / "app" / "services" / "analysis_service.py"


def _saving_method_body() -> str:
    """截取 `_save_analysis_result_web_style` 的方法体文本。"""
    source = SERVICE_PATH.read_text(encoding="utf-8")
    start = source.index("async def _save_analysis_result_web_style(")
    rest = source[start:]
    # 方法体到下一个同级 def 为止
    nxt = re.search(r"\n    (?:async )?def ", rest[len("async def _save_analysis_result_web_style("):])
    return rest if not nxt else rest[: len("async def _save_analysis_result_web_style(") + nxt.start()]


def test_report_document_persists_user_id():
    body = _saving_method_body()
    assert '"user_id"' in body, "报告文档必须写入 user_id，否则列表页按 user_id 过滤时看不到"


def test_owner_is_resolved_from_task_document():
    """归属应取自任务文档（写入方法只拿到 task_id），而不是依赖调用方传参。"""
    body = _saving_method_body()
    assert "analysis_tasks.find_one" in body, "应按 task_id 从 analysis_tasks 取回归属"
    assert re.search(r'"user_id"\s*:\s*report_user_id', body), "document 中应写入解析出的归属"


def test_owner_lookup_failure_does_not_block_save():
    """归属查询失败不得中断报告落库（报告本身仍有价值）。"""
    body = _saving_method_body()
    assert "except Exception" in body, "归属查询需要兜底，失败不能阻断保存"
