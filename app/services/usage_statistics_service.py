"""
使用统计服务
管理模型使用记录和成本统计
"""

import logging
from datetime import datetime, timedelta
from app.utils.timezone import now_utc, now_config_tz
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
    ) -> List[UsageRecord]:
        """获取使用记录。

        当 user_id 提供时，仅返回该用户的记录（普通用户访问）。
        当 user_id 为 None 时，返回所有记录（admin 访问）。
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

            logger.info(f"✅ 获取使用统计成功: {stats.total_requests} 条记录")
            return stats
        except Exception as e:
            logger.error(f"❌ 获取使用统计失败: {e}")
            return UsageStatistics()

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


# ==================== 同步 Token 跟踪器 ====================
# 供 LLM 适配器使用的同步 token 跟踪器
# 从 app.engine.config.config_manager.TokenTracker 迁移而来

import json  # noqa: E402 (intentional late import)
from pathlib import Path  # noqa: E402 (intentional late import)
from dataclasses import asdict  # noqa: E402 (intentional late import)


class SyncTokenTracker:
    """同步 Token 使用跟踪器（供 LLM 适配器使用）"""

    def __init__(self):
        self._pricing_cache: list = []
        self._pricing_loaded = False

    def _load_pricing(self) -> list:
        """加载定价配置"""
        if self._pricing_loaded:
            return self._pricing_cache
        try:
            pricing_file = Path("config/pricing.json")
            if pricing_file.exists():
                with open(pricing_file, "r", encoding="utf-8") as f:
                    self._pricing_cache = json.load(f)
            self._pricing_loaded = True
        except Exception as e:
            logger.warning(f"加载定价配置失败: {e}")
        return self._pricing_cache

    def calculate_cost(
        self, provider: str, model_name: str, input_tokens: int, output_tokens: int
    ) -> tuple:
        """
        计算使用成本

        Returns:
            tuple[float, str]: (成本, 货币单位)
        """
        pricing_configs = self._load_pricing()

        for pricing in pricing_configs:
            p = (
                pricing.get("provider", "")
                if isinstance(pricing, dict)
                else getattr(pricing, "provider", "")
            )
            m = (
                pricing.get("model_name", "")
                if isinstance(pricing, dict)
                else getattr(pricing, "model_name", "")
            )
            if p == provider and m == model_name:
                inp = (
                    pricing.get("input_price_per_1k", 0)
                    if isinstance(pricing, dict)
                    else getattr(pricing, "input_price_per_1k", 0)
                )
                out = (
                    pricing.get("output_price_per_1k", 0)
                    if isinstance(pricing, dict)
                    else getattr(pricing, "output_price_per_1k", 0)
                )
                cur = (
                    pricing.get("currency", "CNY")
                    if isinstance(pricing, dict)
                    else getattr(pricing, "currency", "CNY")
                )
                total = (input_tokens / 1000) * inp + (output_tokens / 1000) * out
                return round(total, 6), cur

        return 0.0, "CNY"

    def track_usage(
        self,
        provider: str,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        session_id: str = None,
        analysis_type: str = "stock_analysis",
    ):
        """
        跟踪 Token 使用量并保存到 MongoDB

        Returns:
            UsageRecord or dict: 使用记录
        """
        if session_id is None:
            session_id = f"session_{now_config_tz().strftime('%Y%m%d_%H%M%S')}"

        # 计算成本
        cost, currency = self.calculate_cost(
            provider, model_name, input_tokens, output_tokens
        )

        # 尝试同步写入 MongoDB
        try:
            from app.core.database import get_mongo_db_sync

            db = get_mongo_db_sync()
            if db is not None:
                record_doc = {
                    "timestamp": now_config_tz().isoformat(),
                    "provider": provider,
                    "model_name": model_name,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost": cost,
                    "currency": currency,
                    "session_id": session_id,
                    "analysis_type": analysis_type,
                }
                result = db["token_usage"].insert_one(record_doc)
                # 确认 result 不是 coroutine（PyMongo 同步客户端应返回 InsertOneResult）
                if hasattr(result, "__await__"):
                    logger.warning(
                        "get_mongo_db_sync() 返回了 Motor 异步数据库，跳过同步写入"
                    )
                logger.info(
                    f"💾 [Token记录] MongoDB保存成功: {provider}/{model_name}, 成本={cost:.6f}"
                )
                # 返回一个简单的类 dict 对象兼容旧的 UsageRecord 接口
                record_doc["cost"] = cost
                return _SimpleRecord(**record_doc)
        except Exception as e:
            logger.warning(f"⚠️ [Token记录] MongoDB保存失败，回退到JSON: {e}")

        # 回退到 JSON 文件存储
        try:
            from app.engine.config.usage_models import UsageRecord

            record = UsageRecord(
                timestamp=now_config_tz().isoformat(),
                provider=provider,
                model_name=model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=cost,
                currency=currency,
                session_id=session_id,
                analysis_type=analysis_type,
            )
            usage_file = Path("config/usage.json")
            records = []
            if usage_file.exists():
                with open(usage_file, "r", encoding="utf-8") as f:
                    records = json.load(f)
            records.append(asdict(record))
            with open(usage_file, "w", encoding="utf-8") as f:
                json.dump(records[-10000:], f, ensure_ascii=False, indent=2)
            logger.info(f"💾 [Token记录] JSON文件保存成功: {provider}/{model_name}")
            return record
        except Exception as e:
            logger.error(f"❌ [Token记录] 保存失败: {e}")
            return None


class _SimpleRecord:
    """简单的记录对象，兼容旧 UsageRecord 的属性访问"""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


# 全局同步 token_tracker 实例
token_tracker = SyncTokenTracker()
