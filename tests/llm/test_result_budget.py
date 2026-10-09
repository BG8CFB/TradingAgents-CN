"""result_budget 单元测试（本地逻辑 + 真实文件 I/O，无需 API）。

覆盖（对齐本地「工具结果硬上限」语义）：
- 未超限原样直传
- 超限**截断 + 显式标注**（比旧版"落盘 + 2K 预览"更保守：保留前 N 字符并
  明确告知已截断，模型不会把残缺数据当全量）
- registry.execute 同样受上限保护
- registry.extend 公共 API（子代理工具子集并入）
- EventSink.on_progress 进度通道（progress 事件不落库、转发文本）

背景：单个工具结果过大曾把上下文撑爆——中国市场分析师消息体累积到
1,144,006 tokens 被 API 400 拒绝（"maximum context length is 1048576"），
整位分析师中断，故恢复硬上限。
"""

from app.llm.events import EventSink
from app.llm.tools.registry import ToolRegistry
from app.llm.tools.result_budget import (
    DEFAULT_MAX_RESULT_CHARS,
    apply_result_budget,
)

TRUNCATION_MARK = "【结果已截断】"


class TestApplyResultBudget:
    def test_under_limit_passthrough(self):
        out = apply_result_budget("my_tool", "short result", task_id="t1")
        assert out == "short result"

    def test_over_limit_truncated_with_marker(self, tmp_path, monkeypatch):
        """超限截断：保留前 DEFAULT_MAX_RESULT_CHARS 字符 + 显式截断标注。"""
        monkeypatch.chdir(tmp_path)
        big = "x" * (DEFAULT_MAX_RESULT_CHARS + 10_000)
        out = apply_result_budget("my_tool", big, task_id="task-预算")

        assert out.startswith("x" * DEFAULT_MAX_RESULT_CHARS)
        assert TRUNCATION_MARK in out
        assert f"{len(big):,}" in out  # 原始长度如实告知模型
        assert len(out) < len(big)

    def test_custom_max_chars_honored(self, tmp_path, monkeypatch):
        """自定义阈值生效（调用方按场景收紧，如 MCP 走 100_000）。"""
        monkeypatch.chdir(tmp_path)
        out = apply_result_budget("t", "a" * 50, task_id="", max_chars=10)

        assert out.startswith("a" * 10)
        assert TRUNCATION_MARK in out

    def test_unsafe_task_id_no_disk_write(self, tmp_path, monkeypatch):
        """task_id 不参与落盘（本实现不写文件），任何字符都安全。"""
        monkeypatch.chdir(tmp_path)
        payload = "a" * (DEFAULT_MAX_RESULT_CHARS + 100)
        out = apply_result_budget("t", payload, task_id="../evil/id")

        assert TRUNCATION_MARK in out
        assert not (tmp_path / "evil").exists()
        assert list(tmp_path.iterdir()) == []  # 未产生任何文件


class TestRegistryBudgetIntegration:
    async def test_execute_truncates_oversized(self, tmp_path, monkeypatch):
        """registry.execute 大结果同样受上限保护。"""
        monkeypatch.chdir(tmp_path)
        reg = ToolRegistry()

        @reg.register
        def big_tool() -> str:
            """返回大结果"""
            return "y" * (DEFAULT_MAX_RESULT_CHARS + 5_000)

        out = await reg.execute("big_tool", {}, task_id="tk1")
        assert out.startswith("y" * DEFAULT_MAX_RESULT_CHARS)
        assert TRUNCATION_MARK in out

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
        await sink.emit(
            "progress",
            agent_key="bull",
            phase="stage2",
            completed=3,
            total=9,
            percent=33,
            step_text=" Bull 研究员正在发言 ",
        )
        # on_progress 通道传结构化 payload dict（消费方 graph_progress_callback
        # 按 payload.get("percent") 等键读取，对齐 commit 77bece61 计数式进度）
        assert progress_texts == [
            {"completed": 3, "total": 9, "percent": 33, "step_text": " Bull 研究员正在发言 "}
        ]
        # progress 不落库
        await sink.flush()
        assert persisted == []
        # 实时通道仍可见
        assert received and received[-1].event_type == "progress"

    async def test_progress_without_callback_no_error(self):
        sink = EventSink(task_id="t2")
        ev = await sink.emit("progress", text="hi")
        assert ev.event_type == "progress"
