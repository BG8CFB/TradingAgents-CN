"""手动 L1 研判审计日志仓储 — append-only，(user_id, created_at) 唯一。"""

from typing import Dict

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name


class ScreeningInsightsRepo:

    async def insert_one(self, doc: Dict) -> None:
        db = get_motor_db()
        coll = db[get_collection_name("screening_insights", "CN")]
        await coll.insert_one(doc)

    async def count_today_done(self, user_id: str, date_str: str) -> int:
        """按 (user_id, 自然日) 统计成功研判次数 — 手动配额计数口径。

        created_at 统一存 app.utils.timezone.now_tz() 的 ISO 字符串，
        其日期部分与调用方传入的本地自然日一致；status=failed 不计数
        （失败不扣配额）。
        """
        db = get_motor_db()
        coll = db[get_collection_name("screening_insights", "CN")]
        return await coll.count_documents({
            "user_id": user_id,
            "status": "done",
            "created_at": {"$regex": f"^{date_str}"},
        })
