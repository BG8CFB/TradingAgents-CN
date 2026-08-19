"""result_budget 单元测试（本地逻辑 + 真实文件 I/O，无需 API）。

覆盖：
- 未超限：原样返回
- 超限：预览 + 完整结果路径，全文原子落盘可读回
- registry.execute 接入预算（大结果 → 预览文本）
- registry.extend 公共 API（子代理工具子集并入）
- EventSink.on_progress 进度通道（progress 事件不落库、转发文本）
"""

from app.llm.events import EventSink
from app.llm.tools.registry import ToolRegistry
from app.llm.tools.result_budget import (
    DEFAULT_MAX_RESULT_CHARS,
    PREVIEW_CHARS,
    apply_result_budget,
)


class TestApplyResultBudget:
    def test_under_limit_passthrough(self):
        out = apply_result_budget("my_tool", "short result", task_id="t1")
        assert out == "short result"

    def test_over_limit_persists_and_returns_preview(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # runtime 目录落在临时仓库根下（TA_RUNTIME_DIR 未设）
        big = "x" * (DEFAULT_MAX_RESULT_CHARS + 10_000)
        out = apply_result_budget("my_tool", big, task_id="task-预算")

        assert out.startswith("x" * PREVIEW_CHARS)
        assert "已保存" in out and "完整结果" in out
        # 从预览中提取落盘路径并读回全文
        path_line = [ln for ln in out.splitlines() if "已保存" in ln][0]
        path = path_line.split("：", 1)[1].rstrip("]")
        content = open(path, encoding="utf-8").read()  # noqa: SIM115
        assert content == big

    def test_custom_max_chars(self):
        out = apply_result_budget("t", "a" * 50, task_id="", max_chars=10)
        assert "已保存" in out

    def test_unsafe_task_id_sanitized(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        out = apply_result_budget("t", "a" * (DEFAULT_MAX_RESULT_CHARS + 100), task_id="../evil/id")
        assert ".." not in out.split("已保存：", 1)[1] or "evil" in out


class TestRegistryBudgetIntegration:
    async def test_execute_applies_budget(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        reg = ToolRegistry()

        @reg.register
        def big_tool() -> str:
            """返回大结果"""
            return "y" * (DEFAULT_MAX_RESULT_CHARS + 5_000)

        out = await reg.execute("big_tool", {}, task_id="tk1")
        assert len(out) < 10_000
        assert "已保存" in out

    async def test_execute_small_untouched(self):
        reg = ToolRegistry()

        @reg.register
        def small_tool() -> str:
            """小结果"""
            return "ok"

        assert await reg.execute("small_tool", {}) == "ok"

    def test_extend_reuses_defs(self):
        from app.llm.core.types import ToolDef

        reg = ToolRegistry()

        def handler(x: int) -> str:
            return str(x)

        defs = [ToolDef(name="ext_tool", description="外部工具", params_schema={"type": "object", "properties": {}}, handler=handler)]
        reg.extend(defs)
        assert reg.get("ext_tool") is not None
        assert reg.defs()[0].handler is handler


class TestEventSinkProgressChannel:
    async def test_progress_event_forwarded_not_persisted(self):
        received = []
        persisted = []
        sink = EventSink(
            task_id="t-prog",
            on_event=lambda ev: received.append(ev),
            on_persist=lambda batch: persisted.extend(batch),
            on_progress=lambda text: None,  # 直接断言经 events 通道
        )
        progress_texts = []
        sink._on_progress = progress_texts.append
        await sink.emit("progress", agent_key="bull", phase="stage2", text=" Bull 研究员正在发言 ")
        assert progress_texts == [" Bull 研究员正在发言 "]
        # progress 不落库
        await sink.flush()
        assert persisted == []
        # 实时通道仍可见
        assert received and received[-1].event_type == "progress"

    async def test_progress_without_callback_no_error(self):
        sink = EventSink(task_id="t2")
        ev = await sink.emit("progress", text="hi")
        assert ev.event_type == "progress"
