"""多源对账服务 — 如公司行为多源交叉验证。"""

import logging
from datetime import date
from typing import Dict, List, Optional

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name

logger = logging.getLogger(__name__)


class ReconciliationService:
    """多源对账。

    状态：尚未集成 — 当前未被路由/服务/调度器调用，属于预留功能。
    """

    async def reconcile_corporate_actions(
        self, market: str, symbol: str,
        start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> Dict:
        """对账公司行为数据 — 检查同一事件在不同数据源之间的一致性。

        Returns:
            {total, matched, mismatched, missing_sources, details}
        """
        if not end_date:
            end_date = date.today().isoformat()
        if not start_date:
            start_date = "1970-01-01"

        db = get_motor_db()
        coll_name = get_collection_name("corporate_actions", market)

        # 按日期+类型分组
        docs = await db[coll_name].find(
            {
                "symbol": symbol,
                "ex_date": {"$gte": start_date, "$lte": end_date},
            },
            {"_id": 0}
        ).to_list(length=None)

        if not docs:
            return {"total": 0, "matched": 0, "mismatched": 0, "details": []}

        # 按 (ex_date, action_type) 分组
        groups: Dict[str, List[Dict]] = {}
        for doc in docs:
            key = f"{doc.get('ex_date')}_{doc.get('action_type')}"
            if key not in groups:
                groups[key] = []
            groups[key].append(doc)

        matched = 0
        mismatched = 0
        details = []

        for key, group in groups.items():
            if len(group) <= 1:
                matched += 1
                continue

            # 比较关键字段
            first = group[0]
            is_consistent = True
            for other in group[1:]:
                if first.get("data_source") == other.get("data_source"):
                    continue
                # 比较金额和比例
                if abs((first.get("amount") or 0) - (other.get("amount") or 0)) > 0.01:
                    is_consistent = False
                    break
                ratio_from = first.get("ratio_from") or 0
                other_ratio_from = other.get("ratio_from") or 0
                if abs(ratio_from - other_ratio_from) > 0.001:
                    is_consistent = False
                    break

            if is_consistent:
                matched += 1
            else:
                mismatched += 1
                details.append({
                    "key": key,
                    "sources": [d.get("data_source") for d in group],
                    "amounts": [d.get("amount") for d in group],
                })

        result = {
            "total": len(groups),
            "matched": matched,
            "mismatched": mismatched,
            "details": details,
        }

        if mismatched > 0:
            logger.warning(
                f"对账发现不一致: {market}/{symbol} "
                f"{mismatched}/{len(groups)} 条事件不匹配"
            )

        return result

    async def reconcile_quotes(
        self, market: str, symbol: str, trade_date: str
    ) -> Dict:
        """对账日线行情 — 与快照数据交叉验证。"""
        db = get_motor_db()
        quotes_coll = get_collection_name("daily_quotes", market)
        quotes_doc = await db[quotes_coll].find_one(
            {"symbol": symbol, "trade_date": trade_date},
            {"_id": 0}
        )

        if not quotes_doc:
            return {"status": "missing", "message": f"无 {trade_date} 行情数据"}

        return {
            "status": "ok",
            "symbol": symbol,
            "trade_date": trade_date,
            "close": quotes_doc.get("close"),
            "volume": quotes_doc.get("volume"),
        }
