"""
事件流（面向分析过程面板：agent 上下文与工具调用实时展示 + 落库回放）

事件类型：
- agent_start / agent_end        智能体节点开始/结束（payload: 名称、阶段、耗时）
- llm_request / llm_response     每轮模型调用（payload: 消息数、估算 token、工具数；
                                  request 首轮附完整 messages 数组、response 附本轮文本全文）
- text_delta                     流式文本增量（payload: text）——仅实时通道，不落库
- thinking                       推理模型 thinking/reasoning 块（payload: text）——落库+实时
- tool_call / tool_result        工具调用与结果（payload: name、tool_use_id、input、output、耗时、is_error）
- compact                        上下文压缩发生（payload: 层级 micro/auto/reactive、前后 token）
- user_message_injected          用户消息注入运行中的智能体（payload: agent_key、text 全文）
- report_ready                   单份报告就绪（payload: report_key、title、content）——
                                  pipeline 在节点增量合并时 diff reports 字典发射
- progress                       流水线进度消息（payload: text）——经 on_progress 通道转发，
                                  兼容旧 progress_callback 外部接口（不落库）
"""

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import logging

logger = logging.getLogger("app.llm.events")

# ── payload 截断上限（集中管理，供 runner / pipeline 复用）──────────────
# 为何截断：事件 payload 走 WS 实时下发 + Mongo analysis_events 落库回放，
# 超大 payload 会撑爆 WS 帧与单条文档；截断保留的前缀已足够前端还原过程上下文，
# 完整原文仍保存在主数据存储（reports 结果文档）中，不因截断丢失。
TOOL_RESULT_MAX_CHARS = 8000  # 工具结果：8000 覆盖绝大多数行情/搜索返回，前端可直读
REPORT_CONTENT_MAX_CHARS = 30000  # report_ready 报告内容：单份报告展示上限（总结报告偶发超长）

# user_message_injected 不截断：用户消息本身体量可控，全文回放是消息审计的依据

# system-reminder 包装（message_queue 注入用户消息时的包裹层，回放时解包出原文）
_SYSTEM_REMINDER_PATTERN = re.compile(
    r"^\s*<system-reminder>\s*(.*?)\s*</system-reminder>\s*$", re.DOTALL
)


def unwrap_system_reminder(text: str) -> str:
    """如整条消息被 <system-reminder> 包裹则解包出内层原文，否则原样返回"""
    try:
        m = _SYSTEM_REMINDER_PATTERN.match(text or "")
        return m.group(1) if m else (text or "")
    except Exception:  # noqa: BLE001 - 解包失败不影响原文本
        return text or ""


def flatten_message_content(content: Any) -> str:
    """消息 content 防御式展平为文本（str 直返；block 列表逐块取文本/摘要；异常安全）"""
    try:
        if isinstance(content, str):
            return content
        if content is None:
            return ""
        if isinstance(content, (list, tuple)):
            parts: List[str] = []
            for b in content:
                if isinstance(b, str):
                    parts.append(b)
                    continue
                text = getattr(b, "text", None)
                if isinstance(text, str) and text:
                    parts.append(text)
                elif hasattr(b, "name") and hasattr(b, "id"):
                    parts.append(f"[tool_use:{getattr(b, 'name', '')}]")
                elif hasattr(b, "tool_use_id"):
                    parts.append(f"[tool_result:{getattr(b, 'content', '')}]")
                else:
                    parts.append(str(b))
            return "".join(parts)
        return str(content)
    except Exception:  # noqa: BLE001 - 展平失败降级 str()
        try:
            return str(content)
        except Exception:
            return ""


def messages_event_payload(messages: List[Any]) -> List[Dict[str, str]]:
    """llm_request 的 messages 数组：[{role, content}]，content 经展平为纯文本"""
    out: List[Dict[str, str]] = []
    for m in messages or []:
        role = getattr(m, "role", "")
        role = getattr(role, "value", role)  # Role 枚举 → 字符串
        out.append({
            "role": str(role),
            "content": flatten_message_content(getattr(m, "content", "")),
        })
    return out


# 不落库、仅实时下发的事件（高频）
REALTIME_ONLY = {"text_delta"}
# 仅经 on_progress 通道转发的事件（进度消息，走旧 progress_callback 兼容出口）
PROGRESS_ONLY = {"progress"}


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
        on_progress: Optional[Callable[[str], Any]] = None,
    ):
        self.task_id = task_id
        self._on_event = on_event  # 实时回调（同步或异步）
        self._on_persist = on_persist  # 落库回调（批量）
        self._on_progress = on_progress  # 进度回调（旧 progress_callback 兼容出口）
        self._persist_batch = persist_batch
        self._persist_interval = persist_interval
        self._buffer: List[Event] = []
        self._seq = 0
        self._last_flush = time.time()
        self._agent_status: Dict[str, str] = {}  # agent_key -> running|completed
        # 已携带过全量 messages 的 agent（llm_request 体积控制：每个 agent 仅首个请求轮带全量）
        self._full_messages_agents: set = set()

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

    # ---- llm_request 全量 messages 体积控制（per-agent 首轮判定）----

    def claim_full_messages(self, agent_key: str) -> bool:
        """该 agent_key 首次调用返回 True 并登记；后续（含跨 conversation loop 重入）返回 False"""
        if agent_key in self._full_messages_agents:
            return False
        self._full_messages_agents.add(agent_key)
        return True

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
        # 进度转发（progress 事件专走旧 progress_callback 兼容出口）
        if event_type in PROGRESS_ONLY and self._on_progress is not None:
            try:
                result = self._on_progress(str(payload.get("text", "")))
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:  # noqa: BLE001
                logger.warning(f"⚠️ [events] 进度回调失败: {e}")
        # 落库缓冲（text_delta 等高频事件不落库）
        if self._on_persist is not None and event_type not in REALTIME_ONLY and event_type not in PROGRESS_ONLY:
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
