"""Mongo 业务仓储基类 — 收敛同构模板方法。

各业务域仓储的 upsert_many / get_by_symbol_and_range / get_latest_date
此前逐域复制同一模板（仅 domain 字符串与排序方向不同），本基类将其收敛：
子类只需声明 ``domain`` 与 ``range_sort_direction``，专属方法留在子类。
upsert filter 一律经 key_spec.build_filter（域唯一键注册表）构造。
"""

from typing import Dict, List, Optional

from pymongo import UpdateOne

from app.data.storage.mongo.bulk_utils import batched_bulk_write
from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.repositories.key_spec import build_filter


class MongoBaseRepo:
    """业务域仓储基类（模板方法收敛，行为与迁移前逐域实现保持一致）。

    类属性:
        domain: 业务域标识（集合命名与唯一键注册表的查键），子类必须声明。
        range_sort_direction: 基类 get_by_symbol_and_range 的 trade_date 排序方向。
            子类使用基类区间方法时必须显式声明，把历史上的静默分歧变成可见契约：

            - 1（升序，时间自然序）: daily_quotes / index_quotes / adj_factors —— K 线
              取尾部最新、周期聚合、基准走势等消费方按时间正序遍历；展示层的
              "最新优先"由查看器路由统一处理。
            - -1（降序，最新优先）: money_flow / margin_trading / daily_indicators /
              southbound_holding / pre_post_market / factor_scores —— 展示与增量
              同步类消费方依赖"最新在前"的行序。

            改动任一域的方向都会改变其消费方拿到的行序，须逐一排查调用方。
            区间方法被子类专有实现覆盖（如 corporate_actions 按 ex_date、
            intraday_quotes 按 datetime）时本属性不生效。
    """

    domain: str = ""
    range_sort_direction: int = 1

    def _coll(self, market: str):
        """按 domain + market 解析集合（A 股基础名，HK/US 加后缀）。"""
        return get_motor_db()[get_collection_name(self.domain, market)]

    async def upsert_many(self, records: List[Dict], market: str) -> int:
        """按域唯一键幂等覆盖写入（$set + upsert）；缺少唯一键字段的记录跳过。"""
        if not records:
            return 0
        coll = self._coll(market)
        ops = []
        for rec in records:
            try:
                filter_doc = build_filter(self.domain, rec)
            except KeyError:
                continue  # 缺少唯一键字段的记录跳过
            ops.append(UpdateOne(
                filter_doc,
                {"$set": rec},
                upsert=True,
            ))
        if not ops:
            return 0
        return await batched_bulk_write(coll, ops)

    async def get_by_symbol_and_range(
        self, symbol: str, market: str, start_date: str, end_date: str,
        *, extra_query: Optional[Dict] = None,
    ) -> List[Dict]:
        """按 symbol + trade_date 闭区间读取（投影剔除 _id，方向见类属性）。

        extra_query: 子类透传的额外等值查询键（如 period / session_type）。
        """
        query: Dict = {"symbol": symbol, "trade_date": {"$gte": start_date, "$lte": end_date}}
        if extra_query:
            query.update(extra_query)
        cursor = self._coll(market).find(query, {"_id": 0}).sort(
            "trade_date", self.range_sort_direction
        )
        return await cursor.to_list(length=None)

    async def get_latest_date(self, symbol: str, market: str) -> Optional[str]:
        """该 symbol 在库中的最新 trade_date；无数据返回 None。"""
        doc = await self._coll(market).find_one(
            {"symbol": symbol}, {"trade_date": 1}, sort=[("trade_date", -1)]
        )
        return doc["trade_date"] if doc else None
