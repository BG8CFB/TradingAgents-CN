"""
事件流（面向分析过程面板：agent 上下文与工具调用实时展示 + 落库回放）

事件类型：
- agent_start / agent_end        智能体节点开始/结束（payload: 名称、阶段、耗时）
- llm_request / llm_response     每轮模型调用（payload: 消息数、估算 token、工具数）
- text_delta                     流式文本增量（payload: text）——仅实时通道，不落库
- tool_call / tool_result        工具调用与结果（payload: name、input、output、耗时、is_error）
- compact                        上下文压缩发生（payload: 层级 micro/auto/reactive、前后 token）
- user_message_injected          用户消息注入运行中的智能体（payload: agent_key、text 摘要）
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from app.utils.logging_init import get_logger

logger = get_logger("app.llm.events")

# 不落库、仅实时下发的事件（高频）
REALTIME_ONLY = {"text_delta"}


@dataclass
class Event:
    task_id: str
    seq: int
    ts: float
    agent_key: str
    event_type: str
    phase: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "seq": self.seq,
            "ts": self.ts,
            "phase": self.phase,
            "agent_key": self.agent_key,
            "event_type": self.event_type,
            "payload": self.payload,
        }


class EventSink:
    """事件汇聚点：实时回调（WS 下发）+ 可选批量落库回调"""

    def __init__(
        self,
        task_id: str = "",
        on_event: Optional[Callable[[Event], Any]] = None,
        on_persist: Optional[Callable[[List[Event]], Any]] = None,
        persist_batch: int = 20,
        persist_interval: float = 2.0,
    ):
        self.task_id = task_id
        self._on_event = on_event  # 实时回调（同步或异步）
        self._on_persist = on_persist  # 落库回调（批量）
        self._persist_batch = persist_batch
        self._persist_interval = persist_interval
        self._buffer: List[Event] = []
        self._seq = 0
        self._last_flush = time.time()
        self._agent_status: Dict[str, str] = {}  # agent_key -> running|completed

    # ---- agent 状态跟踪（用户消息发送校验依据）----

    def mark_running(self, agent_key: str) -> None:
        self._agent_status[agent_key] = "running"

    def mark_completed(self, agent_key: str) -> None:
        self._agent_status[agent_key] = "completed"

    def is_running(self, agent_key: str) -> bool:
        return self._agent_status.get(agent_key) == "running"

    @property
    def running_agents(self) -> List[str]:
        return [k for k, v in self._agent_status.items() if v == "running"]

    # ---- 发射 ----

    async def emit(self, event_type: str, agent_key: str = "", phase: str = "", **payload: Any) -> Event:
        self._seq += 1
        ev = Event(
            task_id=self.task_id,
            seq=self._seq,
            ts=time.time(),
            agent_key=agent_key,
            event_type=event_type,
            phase=phase,
            payload=payload,
        )
        # 实时下发
        if self._on_event is not None:
            try:
                result = self._on_event(ev)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:  # noqa: BLE001 - 事件失败不阻断对话
                logger.warning(f"⚠️ [events] 实时回调失败: {e}")
        # 落库缓冲（text_delta 等高频事件不落库）
        if self._on_persist is not None and event_type not in REALTIME_ONLY:
            self._buffer.append(ev)
            if len(self._buffer) >= self._persist_batch or (
                self._buffer and time.time() - self._last_flush >= self._persist_interval
            ):
                await self.flush()
        return ev

    async def flush(self) -> None:
        """把缓冲事件批量交给落库回调"""
        if not self._buffer or self._on_persist is None:
            return
        batch, self._buffer = self._buffer, []
        self._last_flush = time.time()
        try:
            result = self._on_persist(batch)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:  # noqa: BLE001
            logger.warning(f"⚠️ [events] 落库失败（丢弃 {len(batch)} 条）: {e}")
