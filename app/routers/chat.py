"""AI 问答选股助手路由 — 会话 CRUD / 发消息 / 停止 / 配额 / 实时 WS。

- 消息执行链：POST messages 归属校验(404) → 开关(503) → 配额(429) →
  会话锁占用(409) → create_task 即刻返回 202 {run_id, quota_remaining}
- 实时通道：WS /api/chat/ws/{session_id}（子协议 token 鉴权，与 analysis 同款）；
  run_conversation 事件经 ChatEventBridge 转发为 {type:"chat_event", ...}，
  不落库（回放走 chat_messages），轮次边界由 turn_done/failed/cancelled 标记
"""

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, Set

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.response import ok, safe_error_message
from app.routers.auth_db import get_current_user

router = APIRouter(prefix="/api/chat", tags=["Chat"])
logger = logging.getLogger(__name__)


# ── WS 连接管理（自建轻量版，按 session_id 维护） ─────────────


class ChatWSManager:
    """chat 会话实时连接管理：{session_id: {websocket}}；与任务 WS 互不共享。"""

    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, session_id: str) -> None:
        async with self._lock:
            self.active_connections.setdefault(session_id, set()).add(websocket)
        # 客户端经子协议 ['bearer', token] 传 token 时必须回显，否则握手立即失败
        offered = websocket.headers.get("sec-websocket-protocol", "")
        subprotocol = "bearer" if "bearer" in offered.split(",") else None
        await websocket.accept(subprotocol=subprotocol)
        logger.info("🔌 [chat-ws] 连接建立: session=%s", session_id)

    async def disconnect(self, websocket: WebSocket, session_id: str) -> None:
        async with self._lock:
            conns = self.active_connections.get(session_id)
            if conns is not None:
                conns.discard(websocket)
                if not conns:
                    self.active_connections.pop(session_id, None)
        logger.info("🔌 [chat-ws] 连接断开: session=%s", session_id)

    async def send(self, session_id: str, payload: Dict[str, Any]) -> None:
        """向订阅该会话的所有连接下发 JSON；失效连接就地剔除。"""
        conns = self.active_connections.get(session_id)
        if not conns:
            return
        text = json.dumps(payload, ensure_ascii=False)
        for conn in list(conns):
            try:
                await conn.send_text(text)
            except Exception as e:  # noqa: BLE001 - 单连接失败不影响其余
                logger.warning(f"[chat-ws] 发送失败: {e}")
                async with self._lock:
                    conns.discard(conn)
                    if not conns:
                        self.active_connections.pop(session_id, None)


chat_ws_manager = ChatWSManager()


class ChatEventBridge:
    """run_conversation 事件 → ChatWSManager 实时下发；事件不落库（无 on_persist）。

    同时累积 text_delta 流式文本：stop_run 取消后 RunResult 不可得，
    用它保留已生成的部分正文。
    """

    def __init__(self, run_id: str, session_id: str):
        self.run_id = run_id
        self.session_id = session_id
        self.captured_text = ""
        from app.llm.events import EventSink

        self.sink = EventSink(task_id=run_id, on_event=self._on_event)

    async def _on_event(self, ev) -> None:
        if ev.event_type == "text_delta":
            self.captured_text += str(ev.payload.get("text") or "")
        await chat_ws_manager.send(
            self.session_id,
            {
                "type": "chat_event",
                "event_type": ev.event_type,
                "run_id": self.run_id,
                "session_id": self.session_id,
                "seq": ev.seq,
                "ts": ev.ts,
                "payload": ev.payload,
            },
        )


# ── 请求模型 ────────────────────────────────────────────────


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000, description="用户提问内容")


def _svc():
    from app.services.chat import ChatService

    return ChatService()


# ── 会话 CRUD ───────────────────────────────────────────────


@router.post("/sessions")
async def create_session(user: dict = Depends(get_current_user)):
    """创建空会话（title 待首条消息定题）。"""
    try:
        session = await _svc().create_session(str(user["id"]))
        return ok({"session_id": session["session_id"], "title": ""})
    except Exception as e:
        logger.error("[chat] 创建会话失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=safe_error_message(e, "创建会话失败"))


@router.get("/sessions")
async def list_sessions(
    page: int = 1,
    page_size: int = 20,
    user: dict = Depends(get_current_user),
):
    """本人会话列表（updated_at 倒序，只含 active）。"""
    try:
        items, total = await _svc().list_sessions(str(user["id"]), page, page_size)
        return ok({"sessions": items, "total": total, "page": page, "page_size": page_size})
    except Exception as e:
        logger.error("[chat] 会话列表失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=safe_error_message(e, "获取会话列表失败"))


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, user: dict = Depends(get_current_user)):
    """会话详情 + 全部消息回放（非本人或不存在 → 404）。"""
    svc = _svc()
    session = await svc.get_session(session_id, str(user["id"]))
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = await svc.list_messages(session_id)
    return ok({"session": session, "messages": messages})


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, user: dict = Depends(get_current_user)):
    """软删会话（status=archived，消息保留）。"""
    try:
        deleted = await _svc().archive_session(session_id, str(user["id"]))
        if not deleted:
            raise HTTPException(status_code=404, detail="会话不存在")
        return ok({"session_id": session_id, "status": "archived"})
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[chat] 删除会话失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=safe_error_message(e, "删除会话失败"))


# ── 问答执行 ────────────────────────────────────────────────


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: str,
    req: SendMessageRequest,
    user: dict = Depends(get_current_user),
):
    """发送一条消息并即刻返回 run_id（回答经 WS 实时推送）。

    错误分支：404 会话不存在 / 503 功能未启用 / 429 配额用完 / 409 会话占用中。
    """
    from app.services.chat import QuotaExceededError
    from app.services.chat.conversation_runner import (
        get_session_lock,
        start_run,
    )

    user_id = str(user["id"])
    svc = _svc()
    session = await svc.get_session(session_id, user_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    settings = await svc.get_settings()
    if not settings["enabled"]:
        raise HTTPException(status_code=503, detail="AI 问答助手未启用")

    try:
        quota_remaining = await svc.check_quota(user_id)
    except QuotaExceededError as e:
        raise HTTPException(status_code=429, detail=str(e))

    lock = get_session_lock(session_id)
    if lock.locked():
        raise HTTPException(status_code=409, detail="该会话正在回答上一条问题，请等待完成或先停止")

    run_id = f"run_{uuid.uuid4().hex[:12]}"
    start_run(run_id, _run_and_persist(session_id, user_id, run_id, req.content, settings))
    return JSONResponse(
        status_code=202,
        content=ok(
            {
                "run_id": run_id,
                "quota_remaining": quota_remaining - 1,
            },
            message="accepted",
        ),
    )


async def _run_and_persist(
    session_id: str,
    user_id: str,
    run_id: str,
    content: str,
    settings: Dict[str, Any],
) -> None:
    """后台执行一轮问答：锁会话 → run_chat_turn → 落 user/assistant 消息与审计。

    - 成功：user + assistant 两条消息、done 审计、turn_done 事件、会话元数据
    - 失败：user 消息、failed 审计（不扣配额）、turn_failed 事件；assistant 不落
    - 取消（stop_run）：user + assistant（流式部分文本，缺省固定文案）、
      done 审计（已消耗 token）、turn_cancelled 事件
    user 消息统一在 run 结束后落库：run_chat_turn 构造多轮 history 时读库，
    提前落会把本轮提问重复带入上下文。
    """
    from app.services.chat.conversation_runner import (
        get_session_lock,
        run_chat_turn,
    )

    svc = _svc()
    bridge = ChatEventBridge(run_id, session_id)

    async with get_session_lock(session_id):
        try:
            outcome = await run_chat_turn(session_id, user_id, content, run_id, bridge.sink, settings)
        except asyncio.CancelledError:
            text = bridge.captured_text.strip() or "（本轮回答已被用户停止）"
            run_meta = {
                "turns": 0,
                "tool_calls_executed": 0,
                "total_tokens": 0,
                "stop_reason": "cancelled",
                "model": "",
                "run_id": run_id,
            }
            await svc.append_message(session_id, user_id, "user", content)
            await svc.append_message(session_id, user_id, "assistant", text, run_meta=run_meta)
            await svc.record_audit(user_id, session_id, status="done", question_digest=content)
            await svc.touch_session(session_id, title=content, preview=text)
            await chat_ws_manager.send(
                session_id,
                {
                    "type": "chat_event",
                    "event_type": "turn_cancelled",
                    "run_id": run_id,
                    "session_id": session_id,
                    "assistant_text": text,
                    "run_meta": run_meta,
                },
            )
            raise
        except Exception as e:  # noqa: BLE001 - 失败路径兜底，不向上抛
            logger.error("[chat] run %s 失败: %s", run_id, e, exc_info=True)
            try:
                await svc.append_message(session_id, user_id, "user", content)
                await svc.record_audit(user_id, session_id, status="failed", question_digest=content, error=str(e))
            except Exception as log_err:  # noqa: BLE001
                logger.error("[chat] 失败审计落库异常: %s", log_err, exc_info=True)
            await chat_ws_manager.send(
                session_id,
                {
                    "type": "chat_event",
                    "event_type": "turn_failed",
                    "run_id": run_id,
                    "session_id": session_id,
                    "error": safe_error_message(e, "回答生成失败"),
                },
            )
            return

        text = outcome["text"].strip() or "（模型未返回内容，请重试或检查模型配置）"
        run_meta = outcome["run_meta"]
        await svc.append_message(session_id, user_id, "user", content)
        await svc.append_message(session_id, user_id, "assistant", text, run_meta=run_meta)
        await svc.record_audit(
            user_id,
            session_id,
            status="done",
            model=run_meta.get("model") or "",
            question_digest=content,
            tokens_used=run_meta.get("total_tokens"),
        )
        await svc.touch_session(session_id, title=content, preview=text)
        await chat_ws_manager.send(
            session_id,
            {
                "type": "chat_event",
                "event_type": "turn_done",
                "run_id": run_id,
                "session_id": session_id,
                "assistant_text": text,
                "run_meta": run_meta,
            },
        )


@router.post("/runs/{run_id}/stop")
async def stop_run_endpoint(run_id: str, user: dict = Depends(get_current_user)):
    """停止正在回答的一轮（幂等；未运行返回 stopped=false）。"""
    from app.services.chat.conversation_runner import stop_run

    stopped = stop_run(run_id)
    return ok({"run_id": run_id, "stopped": stopped})


@router.get("/quota")
async def get_quota(user: dict = Depends(get_current_user)):
    """当前用户今日剩余问答轮数。"""
    try:
        return ok({"quota_remaining": await _svc().quota_remaining(str(user["id"]))})
    except Exception as e:
        logger.error("[chat] 查询配额失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=safe_error_message(e, "查询配额失败"))


# ── WebSocket 实时通道 ─────────────────────────────────────


@router.websocket("/ws/{session_id}")
async def websocket_chat(websocket: WebSocket, session_id: str):
    """会话实时事件流（鉴权与 analysis WS 同款：子协议 token → verify → 归属校验）。

    关闭码约定：4404 缺 token / 4401 鉴权失败 / 4404 会话不存在或无权 / 1011 异常。
    上行消息：{"type":"stop","run_id":...} 停止指定轮次；{"type":"ping"} 心跳。
    """
    from app.routers.websocket_notifications import _extract_token_from_websocket

    token = _extract_token_from_websocket(websocket)
    if not token:
        await _accept_and_close(websocket, 4404, "session authentication required")
        return

    from app.services.auth_service import AuthService

    token_data = AuthService.verify_token(token)
    if not token_data:
        await _accept_and_close(websocket, 4401, "authentication failed")
        return

    try:
        from app.services.user_service import user_service

        ws_user = await user_service.get_user_by_username(token_data.sub)
        if not ws_user:
            await _accept_and_close(websocket, 4401, "authentication failed")
            return
        user_id = str(ws_user.id)
    except Exception as e:  # noqa: BLE001 - fail-closed：用户查询异常拒绝连接
        logger.warning("[chat-ws] 用户查询异常，拒绝连接: %s", e)
        await _accept_and_close(websocket, 1011, "鉴权服务异常")
        return

    session = await _svc().get_session(session_id, user_id)
    if not session:
        # 不泄露存在性：无权与不存在同一返回
        await _accept_and_close(websocket, 4404, "session not found")
        return

    try:
        await chat_ws_manager.connect(websocket, session_id)
        await websocket.send_text(
            json.dumps(
                {
                    "type": "connection_established",
                    "session_id": session_id,
                    "message": "WebSocket 连接已建立",
                },
                ensure_ascii=False,
            )
        )
        from app.services.chat.conversation_runner import stop_run as stop_run_fn

        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue
            msg_type = msg.get("type")
            if msg_type == "stop":
                run_id = str(msg.get("run_id") or "")
                stopped = stop_run_fn(run_id) if run_id else False
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "stop_result",
                            "run_id": run_id,
                            "stopped": stopped,
                        },
                        ensure_ascii=False,
                    )
                )
            elif msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}, ensure_ascii=False))
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001 - 连接级异常兜底
        logger.warning("[chat-ws] 连接异常退出: %s", e)
    finally:
        await chat_ws_manager.disconnect(websocket, session_id)


async def _accept_and_close(websocket: WebSocket, code: int, reason: str) -> None:
    """握手未完成时直接 close 会退化为 HTTP 403；先 accept 再 close 让关闭码可达浏览器。"""
    try:
        await websocket.accept()
        await websocket.close(code=code, reason=reason)
    except Exception:  # noqa: BLE001 - accept/close 失败由 Starlette 兜底 403
        pass
