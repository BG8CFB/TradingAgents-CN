"""AI 问答会话仓储 — 应用层集合（与 analysis_events 同款，不进市场后缀体系）。

- chat_sessions: 用户会话元数据（软删 status=archived）
- chat_messages: append-only 消息（只存 user/assistant 文本，不存过程事件）
- chat_usage_audit: 每轮问答审计（配额只数 status=done，与 screening_insights 同口径）
"""

import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.data.storage.mongo.client import get_motor_db
from app.utils.timezone import now_tz

SESSIONS_COLLECTION = "chat_sessions"
MESSAGES_COLLECTION = "chat_messages"
AUDIT_COLLECTION = "chat_usage_audit"


def new_session_id() -> str:
    """生成会话标识：sess_<uuid8>。"""
    return f"sess_{uuid.uuid4().hex[:8]}"


class ChatRepo:
    """chat 三集合读写。所有查询按 user_id 过滤（归属校验在 repo 层兜底）。"""

    async def ensure_indexes(self) -> None:
        db = get_motor_db()
        await db[SESSIONS_COLLECTION].create_index([("user_id", 1), ("updated_at", -1)])
        await db[MESSAGES_COLLECTION].create_index([("session_id", 1), ("created_at", 1)])
        await db[AUDIT_COLLECTION].create_index([("user_id", 1), ("created_at", -1)])

    # ── 会话 ────────────────────────────────────────────────

    async def create_session(self, user_id: str) -> Dict[str, Any]:
        doc = {
            "session_id": new_session_id(),
            "user_id": user_id,
            "title": "",
            "message_count": 0,
            "last_message_preview": "",
            "status": "active",
            "created_at": now_tz().isoformat(),
            "updated_at": now_tz().isoformat(),
        }
        await get_motor_db()[SESSIONS_COLLECTION].insert_one(dict(doc))
        return doc

    async def list_sessions(
        self,
        user_id: str,
        skip: int = 0,
        limit: int = 20,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """本人 active 会话，updated_at 倒序。返回 (items, total)。"""
        db = get_motor_db()
        query = {"user_id": user_id, "status": "active"}
        total = await db[SESSIONS_COLLECTION].count_documents(query)
        cursor = db[SESSIONS_COLLECTION].find(query, {"_id": 0}).sort("updated_at", -1).skip(skip).limit(limit)
        items = await cursor.to_list(length=limit)
        return items, total

    async def find_session(
        self,
        session_id: str,
        user_id: str,
    ) -> Optional[Dict[str, Any]]:
        """按 (session_id, user_id) 取会话；不存在或非本人返回 None。"""
        return await get_motor_db()[SESSIONS_COLLECTION].find_one(
            {"session_id": session_id, "user_id": user_id}, {"_id": 0}
        )

    async def archive_session(self, session_id: str, user_id: str) -> bool:
        """软删（status=archived）。返回是否命中。"""
        result = await get_motor_db()[SESSIONS_COLLECTION].update_one(
            {"session_id": session_id, "user_id": user_id, "status": "active"},
            {"$set": {"status": "archived", "updated_at": now_tz().isoformat()}},
        )
        return result.modified_count > 0

    async def touch_session(
        self,
        session_id: str,
        *,
        title: str = "",
        preview: str = "",
    ) -> None:
        """一轮问答完成后更新会话元数据（每轮固定 +2 条消息）。

        标题采用「首条消息定题」：仅当库中标题仍为空时写入 title 前 20 字。
        """
        db = get_motor_db()
        base_set = {"updated_at": now_tz().isoformat(), "last_message_preview": preview[:50]}
        if title:
            result = await db[SESSIONS_COLLECTION].update_one(
                {"session_id": session_id, "title": ""},
                {"$set": {**base_set, "title": title[:20]}, "$inc": {"message_count": 2}},
            )
            if result.modified_count:
                return
        await db[SESSIONS_COLLECTION].update_one(
            {"session_id": session_id}, {"$set": base_set, "$inc": {"message_count": 2}}
        )

    # ── 消息（append-only） ─────────────────────────────────

    async def insert_message(
        self,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
        run_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        doc = {
            "session_id": session_id,
            "user_id": user_id,
            "role": role,
            "content": content,
            "created_at": now_tz().isoformat(),
        }
        if run_meta is not None:
            doc["run_meta"] = run_meta
        await get_motor_db()[MESSAGES_COLLECTION].insert_one(doc)
        doc.pop("_id", None)
        return doc

    async def list_messages(
        self,
        session_id: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """最近 limit 条消息（created_at 倒序取，返回保持倒序；调用方自行反转）。"""
        cursor = (
            get_motor_db()[MESSAGES_COLLECTION]
            .find({"session_id": session_id}, {"_id": 0})
            .sort("created_at", -1)
            .limit(limit)
        )
        return await cursor.to_list(length=limit)

    async def list_all_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """会话全部消息（回放用，created_at 升序）。"""
        cursor = get_motor_db()[MESSAGES_COLLECTION].find({"session_id": session_id}, {"_id": 0}).sort("created_at", 1)
        return await cursor.to_list(length=None)

    # ── 审计与配额 ──────────────────────────────────────────

    async def insert_audit(self, doc: Dict[str, Any]) -> None:
        await get_motor_db()[AUDIT_COLLECTION].insert_one(doc)

    async def count_today_done(self, user_id: str, date_str: str) -> int:
        """按 (user_id, 自然日) 统计成功轮次 — 配额计数口径，failed 不计。

        created_at 统一存 app.utils.timezone.now_tz() 的 ISO 字符串，
        其日期部分与调用方传入的本地自然日一致（与 screening_insights 同款）。
        """
        return await get_motor_db()[AUDIT_COLLECTION].count_documents(
            {
                "user_id": user_id,
                "status": "done",
                "created_at": {"$regex": f"^{date_str}"},
            }
        )
