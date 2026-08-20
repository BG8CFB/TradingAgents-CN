"""进度单通道桥测试（计数式重构后）

契约：pipeline 发射结构化 progress 事件（completed/total/percent/step_text）；
progress 经 on_progress 通道转发给服务层落盘（payload 为 dict），同时走
on_event 实时通道下发 WS（前端实时消费），但不进 Mongo 落库缓冲。
"""

import asyncio

from app.llm.events import Event, EventSink


class Recorder:
    """捕获 on_progress / on_event 调用的替身（真实签名）"""

    def __init__(self):
        self.progress = []
        self.events = []
        self.persisted = []

    def on_progress(self, payload: dict):
        self.progress.append(payload)

    def on_event(self, ev: Event):
        self.events.append(ev)

    def on_persist(self, batch):
        self.persisted.extend(batch)


async def _emit(sink: EventSink):
    await sink.emit(
        "progress", agent_key="market", phase="analysts",
        completed=1, total=8, percent=5, step_text="📈 市场分析师",
    )
    await sink.emit("agent_start", agent_key="market", phase="analysts", name="市场分析师")
    await sink.flush()


def test_progress_forwards_structured_payload():
    rec = Recorder()
    sink = EventSink(task_id="t1", on_event=rec.on_event, on_persist=rec.on_persist, on_progress=rec.on_progress)
    asyncio.run(_emit(sink))

    # on_progress 通道收到完整结构化 payload（服务层据此写 progress_tracker）
    assert rec.progress == [
        {"completed": 1, "total": 8, "percent": 5, "step_text": "📈 市场分析师"}
    ]
    # progress 也走 on_event 实时通道（WS agent_event 帧，前端实时进度来源）
    assert [e.event_type for e in rec.events] == ["progress", "agent_start"]
    # progress 不落库；agent_start 正常落库
    assert [e.event_type for e in rec.persisted] == ["agent_start"]


def test_pipeline_wraps_bare_callback_into_sink():
    """run_pipeline 无 event_sink 但有 progress_callback 时自动构造轻量 sink"""
    from app.engine.orchestrator.pipeline import run_pipeline
    import inspect

    # 仅验证函数签名兼容（progress_callback 参数保留为兼容入口）
    sig = inspect.signature(run_pipeline)
    assert "progress_callback" in sig.parameters
    assert "event_sink" in sig.parameters
    assert "progress_range" in sig.parameters
