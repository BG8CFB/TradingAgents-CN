"""
用户消息定向队列（参考 claude-code messageQueueManager + attachments.ts + messages.ts）

- 用户在智能体运行中发消息 → 入队（不打断当前工具）
- runner 在工具结果产生后、下一次 LLM 调用前 drain，包装成
  <system-reminder> 包裹的 user 消息与 tool_result 同批 concat（对齐 queued_command attachment）
- 引导语对齐参考模板；队列按 agent_key 定向，完成的 agent 不再投递
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.utils.logging_init import get_logger

from .core.types import Message, Role

logger = get_logger("app.llm.queue")

# 对齐 claude-code wrapCommandText 的人类消息模板
USER_MESSAGE_TEMPLATE = (
    "The user sent a new message while you were working:\n"
    "{text}\n\n"
    "IMPORTANT: After completing your current task, you MUST address the user's "
    "message above. Do not ignore it."
)


def wrap_user_message(text: str) -> str:
    return f"<system-reminder>\n{USER_MESSAGE_TEMPLATE.format(text=text)}\n</system-reminder>"


@dataclass
class QueuedMessage:
    text: str
    agent_key: str = ""
    priority: str = "next"  # now > next > later（对齐参考项目优先级）
    pending: bool = field(default=True)


class MessageQueueManager:
    """进程内单例：task 级 → agent 级定向队列"""

    def __init__(self) -> None:
        self._queues: Dict[str, Dict[str, List[QueuedMessage]]] = {}

    def enqueue(self, task_id: str, agent_key: str, text: str, priority: str = "next") -> None:
        self._queues.setdefault(task_id, {}).setdefault(agent_key, []).append(
            QueuedMessage(text=text, agent_key=agent_key, priority=priority)
        )
        logger.info(f"📩 [queue] 用户消息入队 task={task_id} agent={agent_key}")

    def drain(self, task_id: str, agent_key: str) -> List[QueuedMessage]:
        """取走并清空该 agent 的全部排队消息"""
        msgs = self._queues.get(task_id, {}).pop(agent_key, [])
        return msgs

    def clear_task(self, task_id: str) -> None:
        self._queues.pop(task_id, None)


# 进程级全局队列（对齐参考项目的模块级单例）
message_queues = MessageQueueManager()


def to_injected_messages(msgs: List[QueuedMessage]) -> List[Message]:
    """排队消息 → 注入用 user Message 列表（system-reminder 包装）"""
    return [Message(role=Role.USER, content=wrap_user_message(m.text)) for m in msgs]


class AgentMessageInbox:
    """单个运行中智能体的消息绑定（runner 持有；非阻塞 drain）"""

    def __init__(self, task_id: str, agent_key: str, manager: Optional[MessageQueueManager] = None):
        self.task_id = task_id
        self.agent_key = agent_key
        self._manager = manager or message_queues

    def drain(self) -> List[Message]:
        msgs = self._manager.drain(self.task_id, self.agent_key)
        if msgs:
            logger.info(f"📩 [queue] 注入 {len(msgs)} 条用户消息到 {self.agent_key}")
        return to_injected_messages(msgs)

    async def drain_async(self) -> List[Message]:
        return self.drain()  # drain 为同步非阻塞，异步签名便于 runner 统一 await


__all__ = [
    "MessageQueueManager",
    "AgentMessageInbox",
    "message_queues",
    "to_injected_messages",
    "wrap_user_message",
    "QueuedMessage",
]
