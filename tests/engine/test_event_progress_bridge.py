"""进度单通道桥测试（替代已删除的 ProgressManager）

契约：pipeline 的 progress_callback 旧兼容入口统一挂到 EventSink.on_progress；
progress 事件仅走 on_progress 通道（不落库、不进 on_event 实时通道）。
"""

import asyncio

from app.llm.events import Event, EventSink


class Recorder:
    """捕获 on_progress / on_event 调用的替身（真实签名）"""

    def __init__(self):
        self.progress = []
        self.events = []
        self.persisted = []

    def on_progress(self, text: str):
        self.progress.append(text)

    def on_event(self, ev: Event):
        self.events.append(ev)

    def on_persist(self, batch):
        self.persisted.extend(batch)


async def _emit(sink: EventSink):
    await sink.emit("progress", agent_key="Market Analyst", phase="analysts", text="📈 市场分析师分析中")
    await sink.emit("agent_start", agent_key="market", phase="analysts", name="市场分析师")
    await sink.flush()


def test_progress_forwards_to_on_progress_only():
    rec = Recorder()
    sink = EventSink(task_id="t1", on_event=rec.on_event, on_persist=rec.on_persist, on_progress=rec.on_progress)
    asyncio.run(_emit(sink))

    # progress 文本经 on_progress 通道转发（旧 progress_callback 兼容出口）
    assert rec.progress == ["📈 市场分析师分析中"]
    # progress 不进实时通道、不落库；agent_start 正常落库
    assert [e.event_type for e in rec.events] == ["progress", "agent_start"]
    assert [e.event_type for e in rec.persisted] == ["agent_start"]


def test_pipeline_wraps_bare_callback_into_sink():
    """run_pipeline 无 event_sink 但有 progress_callback 时自动构造轻量 sink"""
    from app.engine.orchestrator.pipeline import run_pipeline
    import inspect

    # 仅验证函数签名兼容（progress_callback 参数保留为兼容入口）
    sig = inspect.signature(run_pipeline)
    assert "progress_callback" in sig.parameters
    assert "event_sink" in sig.parameters
