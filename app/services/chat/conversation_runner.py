"""AI 问答会话执行器 — run_conversation 封装 + 运行注册表 + stop。

并发控制三层：
- 会话锁（get_session_lock）：同一 session 同时只允许一个 run
  （router 侧 non-blocking acquire，占用即 409）
- 全局信号量（_GLOBAL_SEM=5）：全服务同时至多 5 个 chat run，防 LLM 并发打爆
- 运行注册表（_running：run_id → asyncio.Task）：stop_run 按 run_id cancel

MCP 工具：服务级缓存 + TTL 失效（发现失败 log warning 不阻塞对话）。
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from app.data.storage.mongo.repositories.chat_repo import ChatRepo
from app.llm.core.types import Message, Role

logger = logging.getLogger(__name__)

CHAT_MAX_TURNS = 16
HISTORY_MESSAGES = 20  # 多轮上下文：最近 20 条 user/assistant 消息

# MCP 工具服务级缓存（进程内共享，TTL 失效；失败也刷新时间戳防每轮重试）
_MCP_CACHE_TTL = 300.0
_mcp_cache: Dict[str, Any] = {"tools": [], "ts": 0.0}

# 运行注册表与会话锁（模块级单例；session 数量有限，锁不主动回收）
_running: Dict[str, asyncio.Task] = {}
_session_locks: Dict[str, asyncio.Lock] = {}
_GLOBAL_SEM = asyncio.Semaphore(5)


def get_session_lock(session_id: str) -> asyncio.Lock:
    """取会话级互斥锁（同一会话同时只跑一轮）。"""
    lock = _session_locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _session_locks[session_id] = lock
    return lock


def start_run(run_id: str, coro) -> asyncio.Task:
    """注册并启动一个 run；任务结束自动出表。"""
    task = asyncio.create_task(coro)
    _running[run_id] = task
    task.add_done_callback(lambda _t: _running.pop(run_id, None))
    return task


def stop_run(run_id: str) -> bool:
    """取消指定 run（幂等）；返回是否命中运行中的任务。"""
    task = _running.get(run_id)
    if task is None:
        return False
    task.cancel()
    _running.pop(run_id, None)
    return True


def is_running(run_id: str) -> bool:
    return run_id in _running


# ── 内部 ────────────────────────────────────────────────────


async def _resolve_bundle(model_name: str):
    """设置指定模型 → 任务级覆盖 bundle；解析失败或未指定回落 analyst 默认。"""
    from app.llm.providers import get_engine_clients, resolve_task_override_bundle

    if model_name:
        try:
            bundle = await resolve_task_override_bundle(model_name)
            if bundle is not None:
                return bundle
        except Exception as e:  # noqa: BLE001 - 解析失败回落默认
            logger.warning("chat 模型 %s 解析失败，回落 analyst 默认: %s", model_name, e)
    bundle = (await get_engine_clients()).get("analyst")
    if bundle is None:
        raise RuntimeError("未配置任何 LLM 模型（请先在设置页配置）")
    return bundle


async def _discover_mcp_tools_cached() -> List[Any]:
    """MCP 工具发现（共享 manager + 服务级 TTL 缓存）；失败返回空列表不阻塞。"""
    if time.monotonic() - _mcp_cache["ts"] < _MCP_CACHE_TTL:
        return _mcp_cache["tools"]
    try:
        from app.llm.mcp.service import get_shared_manager
        from app.llm.mcp.tools import discover_mcp_tools

        tools = await discover_mcp_tools(get_shared_manager())
        _mcp_cache.update(tools=tools, ts=time.monotonic())
        logger.info("[chat] MCP 工具发现: %d 个", len(tools))
        return tools
    except Exception as e:  # noqa: BLE001 - MCP 不可用不阻断对话
        logger.warning("[chat] MCP 工具发现失败，跳过: %s", e)
        _mcp_cache["ts"] = time.monotonic()
        return []


async def _build_history(session_id: str) -> List[Message]:
    """最近 HISTORY_MESSAGES 条 user/assistant 文本 → run_conversation history。

    repo 按时间倒序取，reverse 回升序；run_conversation 会原地 append 本轮消息，
    故必须构造新列表（repo 返回值即新列表，直接用）。
    """
    rows = await ChatRepo().list_messages(session_id, limit=HISTORY_MESSAGES)
    rows.reverse()
    return [
        Message(role=Role.USER if r.get("role") == "user" else Role.ASSISTANT, content=r.get("content") or "")
        for r in rows
    ]


# ── 入口 ────────────────────────────────────────────────────


async def run_chat_turn(
    session_id: str,
    user_id: str,
    content: str,
    run_id: str,
    event_sink: Optional[Any],
    settings: Dict[str, Any],
) -> Dict[str, Any]:
    """执行一轮问答（多工具循环 + 事件流），返回 {"text", "run_meta"}。

    被 cancel（stop_run）时 CancelledError 向上抛，由调用方在 finally 落
    cancelled 消息（部分文本从事件桥的流式累积中取）。
    """
    from app.llm.runner import run_conversation
    from app.llm.skills.skill_tool import make_skill_tool
    from app.services.chat.tools import CHAT_TOOLS

    bundle = await _resolve_bundle(settings.get("model") or "")

    tools: List[Any] = [make_skill_tool(), *CHAT_TOOLS]
    if settings.get("enable_mcp"):
        tools = tools + await _discover_mcp_tools_cached()

    history = await _build_history(session_id)

    async with _GLOBAL_SEM:
        result = await run_conversation(
            bundle.primary,
            content,
            system=settings.get("prompt"),
            tools=tools,
            fallback_client=bundle.fallback,
            retry_times=bundle.retry_times,
            max_tokens=bundle.max_tokens,
            temperature=bundle.temperature,
            max_turns=CHAT_MAX_TURNS,
            history=history,
            event_sink=event_sink,
            task_id=run_id,
            agent_key="chat",
            user_id=user_id,
            enable_skill_listing=True,
        )

    run_meta = {
        "turns": result.turns,
        "tool_calls_executed": result.tool_calls_executed,
        "total_tokens": result.total_tokens,
        "stop_reason": result.stop_reason,
        "model": getattr(bundle.primary, "model", "") or "",
        "run_id": run_id,
    }
    return {"text": result.final_text, "run_meta": run_meta}
