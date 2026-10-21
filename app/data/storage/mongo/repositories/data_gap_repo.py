"""数据缺口登记仓储（PRD FR-12）。

缺口是**有生命周期**的状态对象（open → filled / abandoned），不是日志：
- `sync_events` 是追加式审计，无法承载「这条缺口已经补了几轮」；
- 故独立集合 `data_gaps`，唯一键 `(market, domain, gap_date)` 原地累加。

状态机：
```
open ──补采成功──▶ filled
  │
  └──轮次达上限──▶ abandoned（不再自动补，转人工；可被运维重置为 open）
```
"""

from typing import Dict, List, Optional

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.utils.timezone import now_utc

_DOMAIN = "data_gaps"

STATUS_OPEN = "open"
STATUS_FILLED = "filled"
STATUS_ABANDONED = "abandoned"


class DataGapRepo:
    """data_gaps 集合仓储（元数据集合，无市场后缀）。"""

    def _coll(self):
        return get_motor_db()[get_collection_name(_DOMAIN, "CN")]

    async def register(
        self, market: str, domain: str, gap_date: str, reason: str = "",
    ) -> bool:
        """登记缺口；已存在则**不覆盖**已有轮次与状态（幂等）。

        Returns:
            是否发生新建（True = 本次首次发现该缺口）。
        """
        coll = self._coll()
        now = now_utc().isoformat()
        existing = await coll.find_one(
            {"market": market, "domain": domain, "gap_date": gap_date},
            {"_id": 1},
        )
        if existing:
            return False
        await coll.update_one(
            {"market": market, "domain": domain, "gap_date": gap_date},
            {"$setOnInsert": {
                "market": market,
                "domain": domain,
                "gap_date": gap_date,
                "status": STATUS_OPEN,
                "attempts": 0,
                "first_seen_at": now,
                "last_error": reason or None,
            }},
            upsert=True,
        )
        return True

    async def open_gaps(
        self, market: str, domain: Optional[str] = None,
        limit: int = 500,
    ) -> List[Dict]:
        """待补缺口（按日期升序，先补旧的）。"""
        query: Dict = {"market": market, "status": STATUS_OPEN}
        if domain:
            query["domain"] = domain
        cursor = (
            self._coll()
            .find(query, {"_id": 0})
            .sort("gap_date", 1)
            .limit(int(limit))
        )
        return await cursor.to_list(length=None)

    async def mark_filled(
        self, market: str, domain: str, gap_date: str, source: str,
    ) -> None:
        await self._coll().update_one(
            {"market": market, "domain": domain, "gap_date": gap_date},
            {"$set": {
                "status": STATUS_FILLED,
                "filled_at": now_utc().isoformat(),
                "filled_by": source,
                "last_error": None,
            }},
        )

    async def bump_attempt(
        self, market: str, domain: str, gap_date: str,
        error: str, max_attempts: int,
    ) -> Dict:
        """记一次失败尝试；达到上限转 `abandoned`（防死循环，FR-12 规则 2）。

        读改写而非原子 `$inc`：补采是每日一次、`max_instances=1` 的单写者任务，
        竞态窗口可忽略；换成 `find_one_and_update` 会要求测试替身实现更多
        算子，收益不成比例。

        Returns:
            ``{"attempts": int, "status": str, "abandoned": bool}``
        """
        coll = self._coll()
        key = {"market": market, "domain": domain, "gap_date": gap_date}
        doc = await coll.find_one(key, {"attempts": 1})
        attempts = int((doc or {}).get("attempts", 0)) + 1
        update: Dict = {
            "attempts": attempts,
            "last_attempt_at": now_utc().isoformat(),
            "last_error": error,
        }
        abandoned = attempts >= int(max_attempts)
        if abandoned:
            update["status"] = STATUS_ABANDONED
            update["abandoned_at"] = now_utc().isoformat()
        await coll.update_one(key, {"$set": update})
        return {
            "attempts": attempts,
            "status": STATUS_ABANDONED if abandoned else STATUS_OPEN,
            "abandoned": abandoned,
        }

    async def reset(self, market: str, domain: str, gap_date: str) -> None:
        """运维重置：把 abandoned 缺口放回 open 并清零轮次。"""
        await self._coll().update_one(
            {"market": market, "domain": domain, "gap_date": gap_date},
            {"$set": {"status": STATUS_OPEN, "attempts": 0,
                      "last_error": None}},
        )
