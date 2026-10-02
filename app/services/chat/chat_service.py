"""AI 问答选股助手服务 — 会话 CRUD + settings 读取 + 每日配额。

设置键（system_configs.system_settings 透传，与 screening insight 同范式）：
- chat_enabled          总开关（默认关）
- chat_daily_limit      每用户每日问答轮数上限（默认 20）
- chat_model            指定模型（空 = analyst 默认）
- chat_system_prompt    系统提示词（空 = 内置默认）
- chat_enable_mcp       是否装配 MCP 工具（默认关）

配额口径：chat_usage_audit 中 status=done 的当日条数（失败不扣减）。
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.data.storage.mongo.repositories.chat_repo import ChatRepo
from app.services.chat.prompts import DEFAULT_CHAT_SYSTEM_PROMPT
from app.utils.timezone import now_tz

logger = logging.getLogger(__name__)

SETTING_ENABLED = "chat_enabled"
SETTING_DAILY_LIMIT = "chat_daily_limit"
SETTING_MODEL = "chat_model"
SETTING_PROMPT = "chat_system_prompt"
SETTING_ENABLE_MCP = "chat_enable_mcp"

DEFAULT_DAILY_LIMIT = 20


class QuotaExceededError(Exception):
    """当日问答轮数超出配额。"""


class ChatService:
    """会话/配额门面；LLM 执行在 conversation_runner（避免 service ↔ runner 循环依赖）。"""

    def __init__(self, repo: Optional[ChatRepo] = None):
        self._repo = repo or ChatRepo()

    # ── 设置 ────────────────────────────────────────────────

    async def get_settings(self) -> Dict[str, Any]:
        from app.services.config import config_service

        try:
            stored = await config_service.get_system_settings() or {}
        except Exception as e:
            logger.warning("读取 system_settings 失败，用默认值: %s", e)
            stored = {}
        return {
            "enabled": bool(stored.get(SETTING_ENABLED, False)),
            "daily_limit": int(stored.get(SETTING_DAILY_LIMIT, DEFAULT_DAILY_LIMIT)),
            "model": stored.get(SETTING_MODEL) or "",
            "prompt": stored.get(SETTING_PROMPT) or DEFAULT_CHAT_SYSTEM_PROMPT,
            "enable_mcp": bool(stored.get(SETTING_ENABLE_MCP, False)),
        }

    async def quota_remaining(self, user_id: str) -> int:
        settings = await self.get_settings()
        today = now_tz().strftime("%Y-%m-%d")
        used = await self._repo.count_today_done(user_id, today)
        return max(0, settings["daily_limit"] - used)

    async def check_quota(self, user_id: str) -> int:
        """发消息前的配额检查；不足抛 QuotaExceededError，返回剩余值。"""
        remaining = await self.quota_remaining(user_id)
        if remaining <= 0:
            raise QuotaExceededError("今日 AI 问答配额已用完")
        return remaining

    # ── 会话 CRUD ───────────────────────────────────────────

    async def create_session(self, user_id: str) -> Dict[str, Any]:
        await self._repo.ensure_indexes()
        return await self._repo.create_session(user_id)

    async def list_sessions(
        self,
        user_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[Dict[str, Any]], int]:
        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        return await self._repo.list_sessions(user_id, skip=(page - 1) * page_size, limit=page_size)

    async def get_session(self, session_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """取本人 active 会话；archived（软删）对用户不可见（数据保留在库）。"""
        session = await self._repo.find_session(session_id, user_id)
        if session and session.get("status") != "active":
            return None
        return session

    async def archive_session(self, session_id: str, user_id: str) -> bool:
        return await self._repo.archive_session(session_id, user_id)

    async def list_messages(self, session_id: str) -> List[Dict[str, Any]]:
        return await self._repo.list_all_messages(session_id)

    # ── 问答落库（router 侧后台任务经此触达 repo，避免 router 直连数据层） ──

    async def append_message(
        self,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
        run_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """追加一条消息（append-only，只存 user/assistant 文本）。"""
        await self._repo.insert_message(session_id, user_id, role, content, run_meta)

    async def record_audit(
        self,
        user_id: str,
        session_id: str,
        *,
        status: str,
        model: str = "",
        question_digest: str = "",
        tokens_used: Optional[int] = None,
        error: Optional[str] = None,
    ) -> None:
        """落一轮问答审计；配额只数 status=done。"""
        doc: Dict[str, Any] = {
            "user_id": user_id,
            "session_id": session_id,
            "status": status,
            "model": model,
            "question_digest": question_digest[:50],
            "tokens_used": tokens_used,
            "created_at": now_tz().isoformat(),
        }
        if error:
            doc["error"] = error[:500]
        await self._repo.insert_audit(doc)

    async def touch_session(
        self,
        session_id: str,
        *,
        title: str = "",
        preview: str = "",
    ) -> None:
        """一轮问答完成后更新会话元数据（首条消息定题）。"""
        await self._repo.touch_session(session_id, title=title, preview=preview)
