"""
自选股服务
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
from bson import ObjectId

from app.core.database import get_mongo_db
from app.utils.timezone import now_utc


class FavoritesService:
    """自选股服务类"""

    # 交易所代码 → 中文名映射
    _EXCHANGE_MAP = {
        "SSE": "上海证券交易所",
        "SZSE": "深圳证券交易所",
        "BSE": "北京证券交易所",
        "HKEX": "香港交易所",
        "NYSE": "纽约证券交易所",
        "NASDAQ": "纳斯达克",
        "AMEX": "美国证券交易所",
    }

    @staticmethod
    def _infer_board(code: str) -> str:
        """根据股票代码前缀推断板块。"""
        if not code:
            return "-"
        c = str(code).zfill(6)
        if c.startswith("60"):
            return "主板"
        elif c.startswith("00"):
            return "主板"
        elif c.startswith("30"):
            return "创业板"
        elif c.startswith("68"):
            return "科创板"
        elif c.startswith(("4", "8")):
            return "北交所"
        return "主板"

    @classmethod
    def _exchange_display(cls, code: str) -> str:
        """将交易所代码转为中文显示名。"""
        if not code or code == "-":
            return "-"
        return cls._EXCHANGE_MAP.get(code.upper(), code)
    
    def __init__(self):
        self.db = None
    
    async def _get_db(self):
        """获取数据库连接"""
        if self.db is None:
            self.db = get_mongo_db()
        return self.db

    def _is_valid_object_id(self, user_id: str) -> bool:
        """
        检查是否是有效的ObjectId格式
        注意：这里只检查格式，不代表数据库中实际存储的是ObjectId类型
        为了兼容性，我们统一使用 user_favorites 集合存储自选股
        """
        return ObjectId.is_valid(user_id)

    def _format_favorite(self, favorite: Dict[str, Any]) -> Dict[str, Any]:
        """格式化收藏条目（仅基础信息，不包含实时行情）。
        行情将在 get_user_favorites 中批量富集。
        """
        added_at = favorite.get("added_at")
        if isinstance(added_at, datetime):
            added_at = added_at.isoformat()
        return {
            "stock_code": favorite.get("stock_code"),
            "stock_name": favorite.get("stock_name"),
            "market": favorite.get("market", "A股"),
            "added_at": added_at,
            "tags": favorite.get("tags", []),
            "notes": favorite.get("notes", ""),
            "alert_price_high": favorite.get("alert_price_high"),
            "alert_price_low": favorite.get("alert_price_low"),
            # 行情占位，稍后填充
            "current_price": None,
            "change_percent": None,
            "volume": None,
        }

    async def get_user_favorites(self, user_id: str) -> List[Dict[str, Any]]:
        """获取用户自选股列表，并批量拉取实时行情进行富集（兼容字符串ID与ObjectId）。"""
        db = await self._get_db()

        favorites: List[Dict[str, Any]] = []
        if self._is_valid_object_id(user_id):
            # 先尝试使用 ObjectId 查询
            user = await db.users.find_one({"_id": ObjectId(user_id)})
            # 如果 ObjectId 查询失败，尝试使用字符串查询
            if user is None:
                user = await db.users.find_one({"_id": user_id})
            favorites = (user or {}).get("favorite_stocks", [])
        else:
            doc = await db.user_favorites.find_one({"user_id": user_id})
            favorites = (doc or {}).get("favorites", [])

        # 先格式化基础字段
        items = [self._format_favorite(fav) for fav in favorites]

        # 批量获取股票基础信息（板块等）
        codes = [it.get("stock_code") for it in items if it.get("stock_code")]
        if codes:
            try:
                # 获取数据源优先级配置
                from app.data.core.registry.priority import PriorityConfig
                pc = PriorityConfig()
                enabled_sources = await pc.get_priority("CN", "basic_info")
                preferred_source = enabled_sources[0] if enabled_sources else 'tushare'

                # 从 stock_basic_info 获取板块信息（只查询优先级最高的数据源）
                basic_info_coll = db["stock_basic_info"]
                cursor = basic_info_coll.find(
                    {"symbol": {"$in": codes}, "data_source": preferred_source},
                    {"symbol": 1, "exchange": 1, "market": 1, "_id": 0}
                )
                basic_docs = await cursor.to_list(length=None)
                basic_map = {str(d.get("symbol")).zfill(6): d for d in (basic_docs or [])}

                for it in items:
                    code = it.get("stock_code")
                    basic = basic_map.get(code)
                    if basic:
                        raw_market = basic.get("market", "-")
                        if raw_market in ("CN", "HK", "US", ""):
                            it["board"] = self._infer_board(code)
                        else:
                            it["board"] = raw_market
                        it["exchange"] = self._exchange_display(basic.get("exchange", "-"))
                    else:
                        it["board"] = self._infer_board(code)
                        it["exchange"] = "-"
            except Exception as e:
                # 查询失败时设置默认值
                for it in items:
                    it["board"] = "-"
                    it["exchange"] = "-"

        # 批量获取行情（优先使用入库的 market_quotes，30秒更新）
        if codes:
            try:
                # 1) 从 market_quotes 获取最新价格
                mq_coll = db["market_quotes"]
                mq_cursor = mq_coll.find(
                    {"symbol": {"$in": codes}},
                    {"symbol": 1, "last_price": 1, "last_volume": 1, "last_updated": 1},
                )
                mq_docs = await mq_cursor.to_list(length=None)
                mq_map = {str(d.get("symbol")).zfill(6): d for d in (mq_docs or [])}

                # 2) 从 daily_quotes 获取最新交易日的收盘价和涨跌幅
                from app.data.storage.mongo.collections import get_collection_name
                dq_coll_name = get_collection_name("daily_quotes", "CN")
                dq_coll = db[dq_coll_name]

                # 获取每只股票最新一条行情（包含 pct_chg）
                pct_map = {}
                for code in codes:
                    try:
                        latest = await dq_coll.find_one(
                            {"symbol": code},
                            {"symbol": 1, "close": 1, "pct_chg": 1, "trade_date": 1},
                            sort=[("trade_date", -1)],
                        )
                        if latest:
                            pct_map[code] = latest
                    except Exception as e:
                        pass

                for it in items:
                    code = it.get("stock_code")
                    # 价格：优先 market_quotes 的实时价，其次 daily_quotes 最新收盘价
                    mq = mq_map.get(code)
                    dq = pct_map.get(code)
                    if mq and mq.get("last_price") is not None:
                        it["current_price"] = mq["last_price"]
                    elif dq and dq.get("close") is not None:
                        it["current_price"] = dq["close"]

                    # 涨跌幅：从 daily_quotes 获取
                    if dq and dq.get("pct_chg") is not None:
                        it["change_percent"] = dq["pct_chg"]

                # 3) 兜底：对未命中的代码通过 DataInterface 刷新
                missing = [c for c in codes if c not in mq_map and c not in pct_map]
                if missing:
                    try:
                        from app.data.core.interface import DataInterface
                        di = DataInterface.get_instance()
                        quotes_online = {}
                        for code in missing:
                            try:
                                await di.refresh("CN", code, ["market_quotes"])
                                r = await di.read("CN", "market_quotes", symbol=code)
                                d = r.get("data")
                                if d:
                                    doc = d[0] if isinstance(d, list) and d else d
                                    quotes_online[code] = {
                                        "close": doc.get("last_price") or doc.get("close"),
                                        "pct_chg": doc.get("pct_chg"),
                                    }
                            except Exception as e:
                                logger.debug(f"获取行情数据失败: {e}")
                        for it in items:
                            code = it.get("stock_code")
                            if it.get("current_price") is None:
                                q2 = quotes_online.get(code, {})
                                it["current_price"] = q2.get("close")
                                it["change_percent"] = q2.get("pct_chg")
                    except Exception as e:
                        pass
            except Exception as e:
                pass

        return items

    async def add_favorite(
        self,
        user_id: str,
        stock_code: str,
        stock_name: str,
        market: str = "A股",
        tags: List[str] = None,
        notes: str = "",
        alert_price_high: Optional[float] = None,
        alert_price_low: Optional[float] = None
    ) -> bool:
        """添加股票到自选股（兼容字符串ID与ObjectId）"""
        import logging
        logger = logging.getLogger("webapi")

        try:
            logger.info(f"🔧 [add_favorite] 开始添加自选股: user_id={user_id}, stock_code={stock_code}")

            db = await self._get_db()
            logger.info("🔧 [add_favorite] 数据库连接获取成功")

            favorite_stock = {
                "stock_code": stock_code,
                "stock_name": stock_name,
                "market": market,
                "added_at": now_utc(),
                "tags": tags or [],
                "notes": notes,
                "alert_price_high": alert_price_high,
                "alert_price_low": alert_price_low
            }

            logger.info(f"🔧 [add_favorite] 自选股数据构建完成: {favorite_stock}")

            is_oid = self._is_valid_object_id(user_id)
            logger.info(f"🔧 [add_favorite] 用户ID类型检查: is_valid_object_id={is_oid}")

            if is_oid:
                logger.info("🔧 [add_favorite] 使用 ObjectId 方式添加到 users 集合")

                # 先尝试使用 ObjectId 查询
                result = await db.users.update_one(
                    {"_id": ObjectId(user_id)},
                    {"$push": {"favorite_stocks": favorite_stock}}
                )
                logger.info(f"🔧 [add_favorite] ObjectId查询结果: matched_count={result.matched_count}, modified_count={result.modified_count}")

                # 如果 ObjectId 查询失败，尝试使用字符串查询
                if result.matched_count == 0:
                    logger.info("🔧 [add_favorite] ObjectId查询失败，尝试使用字符串ID查询")
                    result = await db.users.update_one(
                        {"_id": user_id},
                        {
                            "$push": {"favorite_stocks": favorite_stock}
                        }
                    )
                    logger.info(f"🔧 [add_favorite] 字符串ID查询结果: matched_count={result.matched_count}, modified_count={result.modified_count}")

                success = result.matched_count > 0
                logger.info(f"🔧 [add_favorite] 返回结果: {success}")
                return success
            else:
                logger.info("🔧 [add_favorite] 使用字符串ID方式添加到 user_favorites 集合")
                result = await db.user_favorites.update_one(
                    {"user_id": user_id},
                    {
                        "$setOnInsert": {"user_id": user_id, "created_at": now_utc()},
                        "$push": {"favorites": favorite_stock},
                        "$set": {"updated_at": now_utc()}
                    },
                    upsert=True
                )
                logger.info(f"🔧 [add_favorite] 更新结果: matched_count={result.matched_count}, modified_count={result.modified_count}, upserted_id={result.upserted_id}")
                logger.info("🔧 [add_favorite] 返回结果: True")
                return True
        except Exception as e:
            logger.error(f"❌ [add_favorite] 添加自选股异常: {type(e).__name__}: {str(e)}", exc_info=True)
            raise

    async def remove_favorite(self, user_id: str, stock_code: str) -> bool:
        """从自选股中移除股票（兼容字符串ID与ObjectId）"""
        db = await self._get_db()

        if self._is_valid_object_id(user_id):
            # 先尝试使用 ObjectId 查询
            result = await db.users.update_one(
                {"_id": ObjectId(user_id)},
                {"$pull": {"favorite_stocks": {"stock_code": stock_code}}}
            )
            # 如果 ObjectId 查询失败，尝试使用字符串查询
            if result.matched_count == 0:
                result = await db.users.update_one(
                    {"_id": user_id},
                    {"$pull": {"favorite_stocks": {"stock_code": stock_code}}}
                )
            return result.modified_count > 0
        else:
            result = await db.user_favorites.update_one(
                {"user_id": user_id},
                {
                    "$pull": {"favorites": {"stock_code": stock_code}},
                    "$set": {"updated_at": now_utc()}
                }
            )
            return result.modified_count > 0

    async def update_favorite(
        self,
        user_id: str,
        stock_code: str,
        tags: Optional[List[str]] = None,
        notes: Optional[str] = None,
        alert_price_high: Optional[float] = None,
        alert_price_low: Optional[float] = None
    ) -> bool:
        """更新自选股信息（兼容字符串ID与ObjectId）"""
        db = await self._get_db()

        # 统一构建更新字段（根据不同集合的字段路径设置前缀）
        is_oid = self._is_valid_object_id(user_id)
        prefix = "favorite_stocks.$." if is_oid else "favorites.$."
        update_fields: Dict[str, Any] = {}
        if tags is not None:
            update_fields[prefix + "tags"] = tags
        if notes is not None:
            update_fields[prefix + "notes"] = notes
        if alert_price_high is not None:
            update_fields[prefix + "alert_price_high"] = alert_price_high
        if alert_price_low is not None:
            update_fields[prefix + "alert_price_low"] = alert_price_low

        if not update_fields:
            return True

        if is_oid:
            result = await db.users.update_one(
                {
                    "_id": ObjectId(user_id),
                    "favorite_stocks.stock_code": stock_code
                },
                {"$set": update_fields}
            )
            return result.modified_count > 0
        else:
            result = await db.user_favorites.update_one(
                {
                    "user_id": user_id,
                    "favorites.stock_code": stock_code
                },
                {
                    "$set": {
                        **update_fields,
                        "updated_at": now_utc()
                    }
                }
            )
            return result.modified_count > 0

    async def is_favorite(self, user_id: str, stock_code: str) -> bool:
        """检查股票是否在自选股中（兼容字符串ID与ObjectId）"""
        import logging
        logger = logging.getLogger("webapi")

        try:
            logger.info(f"🔧 [is_favorite] 检查自选股: user_id={user_id}, stock_code={stock_code}")

            db = await self._get_db()

            is_oid = self._is_valid_object_id(user_id)
            logger.info(f"🔧 [is_favorite] 用户ID类型: is_valid_object_id={is_oid}")

            if is_oid:
                # 先尝试使用 ObjectId 查询
                user = await db.users.find_one(
                    {
                        "_id": ObjectId(user_id),
                        "favorite_stocks.stock_code": stock_code
                    }
                )

                # 如果 ObjectId 查询失败，尝试使用字符串查询
                if user is None:
                    logger.info("🔧 [is_favorite] ObjectId查询未找到，尝试使用字符串ID查询")
                    user = await db.users.find_one(
                        {
                            "_id": user_id,
                            "favorite_stocks.stock_code": stock_code
                        }
                    )

                result = user is not None
                logger.info(f"🔧 [is_favorite] 查询结果: {result}")
                return result
            else:
                doc = await db.user_favorites.find_one(
                    {
                        "user_id": user_id,
                        "favorites.stock_code": stock_code
                    }
                )
                result = doc is not None
                logger.info(f"🔧 [is_favorite] 字符串ID查询结果: {result}")
                return result
        except Exception as e:
            logger.error(f"❌ [is_favorite] 检查自选股异常: {type(e).__name__}: {str(e)}", exc_info=True)
            raise

    async def get_user_tags(self, user_id: str) -> List[str]:
        """获取用户使用的所有标签（兼容字符串ID与ObjectId）"""
        db = await self._get_db()

        if self._is_valid_object_id(user_id):
            pipeline = [
                {"$match": {"_id": ObjectId(user_id)}},
                {"$unwind": "$favorite_stocks"},
                {"$unwind": "$favorite_stocks.tags"},
                {"$group": {"_id": "$favorite_stocks.tags"}},
                {"$sort": {"_id": 1}}
            ]
            result = await db.users.aggregate(pipeline).to_list(None)
        else:
            pipeline = [
                {"$match": {"user_id": user_id}},
                {"$unwind": "$favorites"},
                {"$unwind": "$favorites.tags"},
                {"$group": {"_id": "$favorites.tags"}},
                {"$sort": {"_id": 1}}
            ]
            result = await db.user_favorites.aggregate(pipeline).to_list(None)

        return [item["_id"] for item in result if item.get("_id")]


# 创建全局实例
favorites_service = FavoritesService()
