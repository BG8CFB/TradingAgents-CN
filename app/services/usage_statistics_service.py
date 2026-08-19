"""
使用统计服务
管理模型使用记录和成本统计
"""
# data-access-exempt: 应用层集合（用量统计）

import logging
from datetime import datetime, timedelta
from app.utils.timezone import now_utc
from typing import List, Dict, Optional

from app.core.database import get_mongo_db
from app.models.config import UsageRecord, UsageStatistics

logger = logging.getLogger("app.services.usage_statistics_service")


class UsageStatisticsService:
    """使用统计服务"""

    def __init__(self):
        # 使用 tradingagents 的集合名称
        self.collection_name = "token_usage"

    async def add_usage_record(self, record: UsageRecord) -> bool:
        """添加使用记录"""
        try:
            db = get_mongo_db()
            collection = db[self.collection_name]

            record_dict = record.model_dump(exclude={"id"})
            await collection.insert_one(record_dict)

            logger.info(f"✅ 添加使用记录成功: {record.provider}/{record.model_name}")
            return True
        except Exception as e:
            logger.error(f"❌ 添加使用记录失败: {e}")
            return False

    async def get_usage_records(
        self,
        provider: Optional[str] = None,
        model_name: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        user_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> List[UsageRecord]:
        """获取使用记录。

        当 user_id 提供时，仅返回该用户的记录（普通用户访问）。
        当 user_id 为 None 时，返回所有记录（admin 访问）。
        task_id 可选：按任务过滤。
        """
        try:
            db = get_mongo_db()
            collection = db[self.collection_name]

            # 构建查询条件
            query = {}
            if provider:
                query["provider"] = provider
            if model_name:
                query["model_name"] = model_name
            if user_id:
                query["user_id"] = user_id
            if task_id:
                query["task_id"] = task_id
            if start_date or end_date:
                query["timestamp"] = {}
                if start_date:
                    query["timestamp"]["$gte"] = start_date.isoformat()
                if end_date:
                    query["timestamp"]["$lte"] = end_date.isoformat()

            # 查询记录
            cursor = collection.find(query).sort("timestamp", -1).limit(limit)
            records = []

            async for doc in cursor:
                doc["id"] = str(doc.pop("_id"))
                records.append(UsageRecord(**doc))

            logger.info(f"✅ 获取使用记录成功: {len(records)} 条")
            return records
        except Exception as e:
            logger.error(f"❌ 获取使用记录失败: {e}")
            return []

    async def get_usage_statistics(
        self,
        days: int = 7,
        provider: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> UsageStatistics:
        """获取使用统计"""
        try:
            db = get_mongo_db()
            collection = db[self.collection_name]

            # 计算时间范围
            end_date = now_utc()
            start_date = end_date - timedelta(days=days)

            # 构建查询条件
            query = {
                "timestamp": {
                    "$gte": start_date.isoformat(),
                    "$lte": end_date.isoformat(),
                }
            }
            if provider:
                query["provider"] = provider
            if model_name:
                query["model_name"] = model_name

            # 使用 MongoDB aggregation 服务端聚合，避免全量文档加载到内存
            pipeline = [
                {"$match": query},
                {
                    "$facet": {
                        "overall": [
                            {
                                "$group": {
                                    "_id": "$currency",
                                    "requests": {"$sum": 1},
                                    "input_tokens": {
                                        "$sum": {"$ifNull": ["$input_tokens", 0]}
                                    },
                                    "output_tokens": {
                                        "$sum": {"$ifNull": ["$output_tokens", 0]}
                                    },
                                    "cache_read_input_tokens": {
                                        "$sum": {"$ifNull": ["$cache_read_input_tokens", 0]}
                                    },
                                    "cache_creation_input_tokens": {
                                        "$sum": {"$ifNull": ["$cache_creation_input_tokens", 0]}
                                    },
                                    "cost": {"$sum": {"$ifNull": ["$cost", 0.0]}},
                                }
                            },
                        ],
                        "by_provider": [
                            {
                                "$group": {
                                    "_id": {
                                        "provider": {
                                            "$ifNull": ["$provider", "unknown"]
                                        },
                                        "currency": {"$ifNull": ["$currency", "CNY"]},
                                    },
                                    "requests": {"$sum": 1},
                                    "input_tokens": {
                                        "$sum": {"$ifNull": ["$input_tokens", 0]}
                                    },
                                    "output_tokens": {
                                        "$sum": {"$ifNull": ["$output_tokens", 0]}
                                    },
                                    "cost": {"$sum": {"$ifNull": ["$cost", 0.0]}},
                                }
                            },
                        ],
                        "by_model": [
                            {
                                "$group": {
                                    "_id": {
                                        "provider": {
                                            "$ifNull": ["$provider", "unknown"]
                                        },
                                        "model_name": {
                                            "$ifNull": ["$model_name", "unknown"]
                                        },
                                        "currency": {"$ifNull": ["$currency", "CNY"]},
                                    },
                                    "requests": {"$sum": 1},
                                    "input_tokens": {
                                        "$sum": {"$ifNull": ["$input_tokens", 0]}
                                    },
                                    "output_tokens": {
                                        "$sum": {"$ifNull": ["$output_tokens", 0]}
                                    },
                                    "cost": {"$sum": {"$ifNull": ["$cost", 0.0]}},
                                }
                            },
                        ],
                        "by_date": [
                            {
                                "$group": {
                                    "_id": {
                                        "date": {
                                            "$substrCP": [
                                                {"$ifNull": ["$timestamp", ""]},
                                                0,
                                                10,
                                            ]
                                        },
                                        "currency": {"$ifNull": ["$currency", "CNY"]},
                                    },
                                    "requests": {"$sum": 1},
                                    "input_tokens": {
                                        "$sum": {"$ifNull": ["$input_tokens", 0]}
                                    },
                                    "output_tokens": {
                                        "$sum": {"$ifNull": ["$output_tokens", 0]}
                                    },
                                    "cost": {"$sum": {"$ifNull": ["$cost", 0.0]}},
                                }
                            },
                        ],
                        "by_task": [
                            {
                                "$match": {"task_id": {"$nin": ["", None]}}
                            },
                            {
                                "$group": {
                                    "_id": {
                                        "task_id": "$task_id",
                                        "currency": {"$ifNull": ["$currency", "CNY"]},
                                    },
                                    "requests": {"$sum": 1},
                                    "input_tokens": {"$sum": {"$ifNull": ["$input_tokens", 0]}},
                                    "output_tokens": {"$sum": {"$ifNull": ["$output_tokens", 0]}},
                                    "cache_read_input_tokens": {
                                        "$sum": {"$ifNull": ["$cache_read_input_tokens", 0]}
                                    },
                                    "cost": {"$sum": {"$ifNull": ["$cost", 0.0]}},
                                    "last_ts": {"$max": {"$ifNull": ["$timestamp", ""]}},
                                }
                            },
                            {"$sort": {"last_ts": -1}},
                            {"$limit": 200},
                        ],
                        "by_agent": [
                            {
                                "$group": {
                                    "_id": {
                                        # 空/缺失 agent_key 归为 (unattributed)
                                        "agent_key": {
                                            "$cond": [
                                                {"$in": [{"$ifNull": ["$agent_key", ""]}, ["", None]]},
                                                "(unattributed)",
                                                "$agent_key",
                                            ]
                                        },
                                        "currency": {"$ifNull": ["$currency", "CNY"]},
                                    },
                                    "requests": {"$sum": 1},
                                    "input_tokens": {"$sum": {"$ifNull": ["$input_tokens", 0]}},
                                    "output_tokens": {"$sum": {"$ifNull": ["$output_tokens", 0]}},
                                    "cache_read_input_tokens": {
                                        "$sum": {"$ifNull": ["$cache_read_input_tokens", 0]}
                                    },
                                    "cost": {"$sum": {"$ifNull": ["$cost", 0.0]}},
                                }
                            },
                        ],
                    }
                },
            ]

            facet_result = await collection.aggregate(pipeline).to_list(length=1)
            facet = facet_result[0] if facet_result else {}

            # 构建 UsageStatistics 结果
            stats = UsageStatistics()
            stats.total_requests = sum(
                doc.get("requests", 0) for doc in facet.get("overall", [])
            )
            stats.total_input_tokens = sum(
                doc.get("input_tokens", 0) for doc in facet.get("overall", [])
            )
            stats.total_output_tokens = sum(
                doc.get("output_tokens", 0) for doc in facet.get("overall", [])
            )
            stats.total_cache_read_tokens = sum(
                doc.get("cache_read_input_tokens", 0) for doc in facet.get("overall", [])
            )
            stats.total_cache_creation_tokens = sum(
                doc.get("cache_creation_input_tokens", 0) for doc in facet.get("overall", [])
            )
            stats.total_cost = sum(
                doc.get("cost", 0.0) for doc in facet.get("overall", [])
            )
            stats.cost_by_currency = {
                doc["_id"]: doc.get("cost", 0.0)
                for doc in facet.get("overall", [])
                if doc.get("_id")
            }

            # 按供应商聚合（合并不同货币到 cost_by_currency 子字典）
            by_provider: Dict[str, Dict] = {}
            for doc in facet.get("by_provider", []):
                key = doc["_id"]["provider"]
                currency = doc["_id"].get("currency", "CNY")
                entry = by_provider.setdefault(
                    key,
                    {
                        "requests": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cost": 0.0,
                        "cost_by_currency": {},
                    },
                )
                entry["requests"] += doc.get("requests", 0)
                entry["input_tokens"] += doc.get("input_tokens", 0)
                entry["output_tokens"] += doc.get("output_tokens", 0)
                cost = doc.get("cost", 0.0)
                entry["cost"] += cost
                entry["cost_by_currency"][currency] = (
                    entry["cost_by_currency"].get(currency, 0.0) + cost
                )
            stats.by_provider = by_provider

            # 按模型聚合
            by_model: Dict[str, Dict] = {}
            for doc in facet.get("by_model", []):
                key = f"{doc['_id']['provider']}/{doc['_id']['model_name']}"
                currency = doc["_id"].get("currency", "CNY")
                entry = by_model.setdefault(
                    key,
                    {
                        "requests": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cost": 0.0,
                        "cost_by_currency": {},
                    },
                )
                entry["requests"] += doc.get("requests", 0)
                entry["input_tokens"] += doc.get("input_tokens", 0)
                entry["output_tokens"] += doc.get("output_tokens", 0)
                cost = doc.get("cost", 0.0)
                entry["cost"] += cost
                entry["cost_by_currency"][currency] = (
                    entry["cost_by_currency"].get(currency, 0.0) + cost
                )
            stats.by_model = by_model

            # 按日期聚合
            by_date: Dict[str, Dict] = {}
            for doc in facet.get("by_date", []):
                date_key = doc["_id"].get("date", "")
                if not date_key:
                    continue
                currency = doc["_id"].get("currency", "CNY")
                entry = by_date.setdefault(
                    date_key,
                    {
                        "requests": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cost": 0.0,
                        "cost_by_currency": {},
                    },
                )
                entry["requests"] += doc.get("requests", 0)
                entry["input_tokens"] += doc.get("input_tokens", 0)
                entry["output_tokens"] += doc.get("output_tokens", 0)
                cost = doc.get("cost", 0.0)
                entry["cost"] += cost
                entry["cost_by_currency"][currency] = (
                    entry["cost_by_currency"].get(currency, 0.0) + cost
                )
            stats.by_date = by_date

            # 按任务聚合（top 200，按最近活动排序）
            by_task: Dict[str, Dict] = {}
            for doc in facet.get("by_task", []):
                key = doc["_id"]["task_id"]
                currency = doc["_id"].get("currency", "CNY")
                entry = by_task.setdefault(
                    key,
                    {
                        "requests": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cache_read_tokens": 0,
                        "cost": 0.0,
                        "cost_by_currency": {},
                        "last_timestamp": doc.get("last_ts", ""),
                    },
                )
                entry["requests"] += doc.get("requests", 0)
                entry["input_tokens"] += doc.get("input_tokens", 0)
                entry["output_tokens"] += doc.get("output_tokens", 0)
                entry["cache_read_tokens"] += doc.get("cache_read_input_tokens", 0)
                cost = doc.get("cost", 0.0)
                entry["cost"] += cost
                entry["cost_by_currency"][currency] = (
                    entry["cost_by_currency"].get(currency, 0.0) + cost
                )
            stats.by_task = by_task

            # 按智能体聚合
            by_agent: Dict[str, Dict] = {}
            for doc in facet.get("by_agent", []):
                key = doc["_id"]["agent_key"]
                currency = doc["_id"].get("currency", "CNY")
                entry = by_agent.setdefault(
                    key,
                    {
                        "requests": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cache_read_tokens": 0,
                        "cost": 0.0,
                        "cost_by_currency": {},
                    },
                )
                entry["requests"] += doc.get("requests", 0)
                entry["input_tokens"] += doc.get("input_tokens", 0)
                entry["output_tokens"] += doc.get("output_tokens", 0)
                entry["cache_read_tokens"] += doc.get("cache_read_input_tokens", 0)
                cost = doc.get("cost", 0.0)
                entry["cost"] += cost
                entry["cost_by_currency"][currency] = (
                    entry["cost_by_currency"].get(currency, 0.0) + cost
                )
            stats.by_agent = by_agent

            logger.info(f"✅ 获取使用统计成功: {stats.total_requests} 条记录")
            return stats
        except Exception as e:
            logger.error(f"❌ 获取使用统计失败: {e}")
            return UsageStatistics()

    async def get_task_usage(self, task_id: str) -> Dict:
        """按任务聚合 token 用量（总览 + 按 agent_key/phase 分摊明细）。

        Returns:
            Dict: {task_id, owner_user_id, totals: {...}, by_agent: [...], by_phase: [...]}
        """
        result: Dict = {"task_id": task_id, "owner_user_id": "", "totals": {}, "by_agent": [], "by_phase": []}
        try:
            db = get_mongo_db()
            collection = db[self.collection_name]

            # 任务归属（analysis_tasks 存有 user_id，供路由层做越权校验）
            task_doc = await db["analysis_tasks"].find_one(
                {"task_id": task_id}, {"user_id": 1}
            )
            if task_doc:
                result["owner_user_id"] = str(task_doc.get("user_id") or "")

            group_fields = {
                "requests": {"$sum": 1},
                "input_tokens": {"$sum": {"$ifNull": ["$input_tokens", 0]}},
                "output_tokens": {"$sum": {"$ifNull": ["$output_tokens", 0]}},
                "cache_read_tokens": {"$sum": {"$ifNull": ["$cache_read_input_tokens", 0]}},
                "cache_creation_tokens": {"$sum": {"$ifNull": ["$cache_creation_input_tokens", 0]}},
                "cost": {"$sum": {"$ifNull": ["$cost", 0.0]}},
            }
            pipeline = [
                {"$match": {"task_id": task_id}},
                {
                    "$facet": {
                        "totals": [{"$group": {"_id": None, **group_fields}}],
                        "by_agent": [
                            {"$group": {"_id": "$agent_key", **group_fields}},
                            {"$sort": {"input_tokens": -1}},
                        ],
                        "by_phase": [
                            {"$group": {"_id": "$phase", **group_fields}},
                            {"$sort": {"input_tokens": -1}},
                        ],
                    }
                },
            ]
            facet_result = await collection.aggregate(pipeline).to_list(length=1)
            facet = facet_result[0] if facet_result else {}

            totals = (facet.get("totals") or [{}])[0]
            totals.pop("_id", None)
            result["totals"] = totals

            def _rows(facet_rows, key_name: str):
                out = []
                for r in facet_rows or []:
                    r = dict(r)
                    r[key_name] = r.pop("_id", "")
                    out.append(r)
                return out

            result["by_agent"] = _rows(facet.get("by_agent"), "agent_key")
            result["by_phase"] = _rows(facet.get("by_phase"), "phase")
            return result
        except Exception as e:
            logger.error(f"❌ 获取任务用量失败: {e}")
            return result

    async def get_cost_by_provider(self, days: int = 7) -> Dict[str, float]:
        """获取按供应商的成本统计"""
        stats = await self.get_usage_statistics(days=days)
        return {provider: data["cost"] for provider, data in stats.by_provider.items()}

    async def get_cost_by_model(self, days: int = 7) -> Dict[str, float]:
        """获取按模型的成本统计"""
        stats = await self.get_usage_statistics(days=days)
        return {model: data["cost"] for model, data in stats.by_model.items()}

    async def get_daily_cost(self, days: int = 7) -> Dict[str, float]:
        """获取每日成本统计"""
        stats = await self.get_usage_statistics(days=days)
        return {date: data["cost"] for date, data in stats.by_date.items()}

    async def delete_old_records(self, days: int = 90) -> int:
        """删除旧记录"""
        try:
            db = get_mongo_db()
            collection = db[self.collection_name]

            # 计算截止日期
            cutoff_date = now_utc() - timedelta(days=days)

            # 删除旧记录
            result = await collection.delete_many(
                {"timestamp": {"$lt": cutoff_date.isoformat()}}
            )

            deleted_count = result.deleted_count
            logger.info(f"✅ 删除旧记录成功: {deleted_count} 条")
            return deleted_count
        except Exception as e:
            logger.error(f"❌ 删除旧记录失败: {e}")
            return 0


# 创建全局实例
usage_statistics_service = UsageStatisticsService()

