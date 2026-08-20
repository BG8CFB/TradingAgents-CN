"""分析过程事件服务（Phase C1/C2）

- 为每个分析任务构建 EventSink：实时事件经 WebSocketManager 下发（type=agent_event），
  批量事件落库 Mongo analysis_events（append-only，text_delta 不落库）
- 维护 task → EventSink 活动注册表，供 WS 上行 user_message 校验 running 状态
- 历史回放：GET /api/analysis/tasks/{id}/events（分页/过滤）从 Mongo 读取
"""
# data-access-exempt: 应用层集合（analysis_events 事件持久化）

import asyncio
import time
from typing import Any, Dict, List, Optional

import logging

logger = logging.getLogger("app.services.analysis_events")

EVENTS_COLLECTION = "analysis_events"

# task_id → EventSink（活动任务注册表）
_active_sinks: Dict[str, Any] = {}


def get_active_sink(task_id: str):
    """取活动任务的 EventSink（无则 None）"""
    return _active_sinks.get(task_id)


def is_agent_running(task_id: str, agent_key: str) -> bool:
    sink = _active_sinks.get(task_id)
    return bool(sink) and sink.is_running(agent_key)


def running_agents(task_id: str) -> List[str]:
    sink = _active_sinks.get(task_id)
    return sink.running_agents if sink else []


def create_event_sink(task_id: str, server_loop=None, on_progress=None):
    """创建并注册事件汇聚点（propagate 传入；finally 必须调 release_event_sink）

    Args:
        server_loop: FastAPI 主事件循环。分析在工作线程的事件循环中执行，
            WS 发送与 Mongo 写入必须调度回主循环（asyncio.run_coroutine_threadsafe），
            避免跨事件循环操作连接/客户端对象。
        on_progress: 结构化进度回调（payload: completed/total/percent/step_text），
            由服务层写入 progress_tracker 供轮询兜底。
    """
    from app.llm.events import EventSink
    from app.services.websocket_manager import get_websocket_manager

    ws_manager = get_websocket_manager()

    def _schedule(coro):
        if server_loop is not None and server_loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(coro, server_loop)
            fut.add_done_callback(
                lambda f: (
                    logger.warning(f"⚠️ [analysis_events] 回调失败: {f.exception()}")
                    if f.exception()
                    else None
                )
            )
        else:
            # 无主循环（脚本/测试）：直接在当前循环执行
            async def _run():
                try:
                    await co
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"⚠️ [analysis_events] 回调失败: {e}")

            co = coro
            try:
                asyncio.get_running_loop().create_task(_run())
            except RuntimeError:
                asyncio.run(co)

    def _on_event(ev) -> None:
        # 实时下发到该任务的所有 WS 订阅者（前端 ProcessPanel 消费 agent_event）
        _schedule(ws_manager.send_progress_update(task_id, {"type": "agent_event", **ev.to_dict()}))

    def _on_persist(batch) -> None:
        _schedule(persist_events([e.to_dict() for e in batch]))

    sink = EventSink(
        task_id=task_id,
        on_event=_on_event,
        on_persist=_on_persist,
        on_progress=on_progress,
        persist_batch=20,
        persist_interval=2.0,
    )
    _active_sinks[task_id] = sink
    return sink


def release_event_sink(task_id: str, server_loop=None, timeout: float = 15.0) -> None:
    """任务结束：flush 剩余事件并注销注册表（在工作线程中调用，同步等待完成）"""
    import asyncio as _asyncio

    sink = _active_sinks.pop(task_id, None)
    if sink is not None:
        try:
            if server_loop is not None and server_loop.is_running():
                fut = _asyncio.run_coroutine_threadsafe(sink.flush(), server_loop)
                fut.result(timeout=timeout)
            else:
                _asyncio.run(sink.flush())
        except Exception as e:  # noqa: BLE001
            logger.warning(f"⚠️ [analysis_events] flush 失败 task={task_id}: {e}")
    # 清理用户消息队列残留（防泄漏；agent 已结束不再投递）
    try:
        from app.llm.message_queue import message_queues

        message_queues.clear_task(task_id)
    except Exception:  # noqa: BLE001
        pass


async def persist_events(events: List[Dict[str, Any]]) -> None:
    """批量落库（append-only）"""
    if not events:
        return
    try:
        from app.core.database import get_mongo_db

        db = get_mongo_db()
        await db[EVENTS_COLLECTION].insert_many([dict(e) for e in events])
    except Exception as e:  # noqa: BLE001 - 落库失败不阻断分析
        logger.warning(f"⚠️ [analysis_events] 落库失败（丢弃 {len(events)} 条）: {e}")


async def load_events(
    task_id: str,
    *,
    agent_key: Optional[str] = None,
    event_type: Optional[str] = None,
    after_seq: int = 0,
    limit: int = 500,
    before_seq: Optional[int] = None,
    order: str = "asc",
) -> List[Dict[str, Any]]:
    """读取任务事件（回放）；asc 升序 + after_seq 增量拉取（默认，行为不变），
    desc 降序 + before_seq 支持详情页『最近优先 + 向前翻页』"""
    from app.core.database import get_mongo_db

    db = get_mongo_db()
    if order.lower() == "desc":
        # desc：取 seq 小于 before_seq 的（未给则全部），最新在前
        seq_cond = {"$lt": before_seq} if before_seq is not None else {"$gte": 0}
        sort_dir = -1
    else:
        seq_cond = {"$gt": after_seq}
        sort_dir = 1
    query: Dict[str, Any] = {"task_id": task_id, "seq": seq_cond}
    if agent_key:
        query["agent_key"] = agent_key
    if event_type:
        query["event_type"] = event_type

    cursor = db[EVENTS_COLLECTION].find(query).sort("seq", sort_dir).limit(max(1, min(limit, 5000)))
    out: List[Dict[str, Any]] = []
    async for doc in cursor:
        doc.pop("_id", None)
        out.append(doc)
    return out


def enqueue_user_message(task_id: str, agent_key: str, text: str) -> bool:
    """WS 上行入口：仅 running 的 agent 可入队。返回是否成功。"""
    if not is_agent_running(task_id, agent_key):
        return False
    from app.llm.message_queue import message_queues

    message_queues.enqueue(task_id, agent_key, text)
    return True


def utc_now() -> float:  # pragma: no cover - 供测试对时
    return time.time()
