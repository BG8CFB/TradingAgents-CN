import logging
from datetime import datetime, time as dtime, timedelta
from typing import Dict, Optional, Tuple
from zoneinfo import ZoneInfo
from collections import deque

from pymongo import UpdateOne

from app.core.config import settings
from app.core.database import get_mongo_db
from app.data.storage.mongo.collections import get_collection_name
from app.utils.time_utils import now_config_tz, format_date_compact

logger = logging.getLogger(__name__)


class QuotesIngestionService:
    """
    定时从数据源适配层获取全市场近实时行情，入库到 MongoDB 集合 `market_quotes`。

    核心特性：
    - 调度频率：由 settings.QUOTES_INGEST_INTERVAL_SECONDS 控制（默认360秒=6分钟）
    - 接口轮换：Tushare → AKShare东方财富 → AKShare新浪财经（避免单一接口被限流）
    - 智能限流：Tushare免费用户每小时最多2次，付费用户自动切换到高频模式（5秒）
    - 休市时间：跳过任务，保持上次收盘数据；必要时执行一次性兜底补数
    - 字段：symbol(6位)、close、pct_chg、amount、open、high、low、pre_close、trade_date、data_source、updated_at
    """

    def __init__(self, collection_name: Optional[str] = None) -> None:

        self._market = "CN"
        self.collection_name = collection_name or get_collection_name("market_quotes", self._market)
        self.status_collection_name = "quotes_ingestion_status"  # 状态记录集合
        self.tz = ZoneInfo(settings.TIMEZONE)

        # Tushare 权限检测相关属性
        self._tushare_permission_checked = False  # 是否已检测过权限
        self._tushare_has_premium = False  # 是否有付费权限
        self._tushare_last_call_time = None  # 上次调用时间（用于免费用户限流）
        self._tushare_hourly_limit = 2  # 免费用户每小时最多调用次数
        self._tushare_call_count = 0  # 当前小时内调用次数
        self._tushare_call_times = deque()  # 记录调用时间的队列（用于限流）

        # 接口轮换相关属性
        self._rotation_sources = ["tushare", "akshare_eastmoney", "akshare_sina"]
        self._rotation_index = 0  # 当前轮换索引

    def _find_latest_trade_date(self) -> Optional[str]:
        """获取最新交易日期（YYYYMMDD 格式），基于新架构。"""
        try:
            import asyncio
            from app.data.storage.mongo.repositories.daily_quotes_repo import DailyQuotesRepo
            repo = DailyQuotesRepo()
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(repo.get_latest_date("__all__", "CN"))
        except Exception as e:
            logger.warning(f"获取最新交易日失败: {e}")
            return None

    def _get_realtime_quotes(self) -> Tuple[Optional[Dict], Optional[str]]:
        """获取全市场实时行情快照，基于新架构。"""
        try:
            import asyncio
            from app.data.core.interface import DataInterface

            async def _fetch():
                di = DataInterface.get_instance()
                result = await di.read("CN", "market_quotes", symbol="__all__")
                return result.get("data")

            loop = asyncio.get_event_loop()
            data = loop.run_until_complete(_fetch())
            if data is not None:
                return data, "data_interface"
            return None, None
        except Exception as e:
            logger.warning(f"获取实时行情失败: {e}")
            return None, None

    @staticmethod
    def _normalize_stock_code(code: str) -> str:
        """
        标准化股票代码为6位数字

        处理以下情况：
        - sz000001 -> 000001
        - sh600036 -> 600036
        - 000001 -> 000001
        - 1 -> 000001

        Args:
            code: 原始股票代码

        Returns:
            str: 标准化后的6位股票代码
        """
        if not code:
            return ""

        code_str = str(code).strip()

        # 如果代码长度超过6位，去掉前面的交易所前缀（如 sz, sh）
        if len(code_str) > 6:
            # 提取所有数字字符
            code_str = ''.join(filter(str.isdigit, code_str))

        # 如果是纯数字，补齐到6位
        if code_str.isdigit():
            code_clean = code_str.lstrip('0') or '0'  # 移除前导0，如果全是0则保留一个0
            return code_clean.zfill(6)  # 补齐到6位

        # 如果不是纯数字，尝试提取数字部分
        code_digits = ''.join(filter(str.isdigit, code_str))
        if code_digits:
            return code_digits.zfill(6)

        # 无法提取有效代码，返回空字符串
        return ""

    async def ensure_indexes(self) -> None:
        db = get_mongo_db()
        coll = db[self.collection_name]
        try:
            await coll.create_index("symbol", unique=True)
            await coll.create_index("updated_at")
        except Exception as e:
            logger.warning(f"创建行情表索引失败（忽略）: {e}")

    async def _record_sync_status(
        self,
        success: bool,
        source: Optional[str] = None,
        records_count: int = 0,
        error_msg: Optional[str] = None
    ) -> None:
        """
        记录同步状态

        Args:
            success: 是否成功
            source: 数据源名称
            records_count: 记录数量
            error_msg: 错误信息
        """
        try:
            db = get_mongo_db()
            status_coll = db[self.status_collection_name]

            now = now_config_tz()

            status_doc = {
                "job": "quotes_ingestion",
                "last_sync_time": now,
                "last_sync_time_iso": now.isoformat(),
                "success": success,
                "data_source": source,
                "records_count": records_count,
                "interval_seconds": settings.QUOTES_INGEST_INTERVAL_SECONDS,
                "error_message": error_msg,
                "updated_at": now,
            }

            await status_coll.update_one(
                {"job": "quotes_ingestion"},
                {"$set": status_doc},
                upsert=True
            )

        except Exception as e:
            logger.warning(f"记录同步状态失败（忽略）: {e}")

    async def get_sync_status(self) -> Dict[str, any]:
        """
        获取同步状态

        Returns:
            {
                "last_sync_time": "2025-10-28 15:06:00",
                "last_sync_time_iso": "2025-10-28T15:06:00+08:00",
                "interval_seconds": 360,
                "interval_minutes": 6,
                "data_source": "tushare",
                "success": True,
                "records_count": 5440,
                "error_message": None
            }
        """
        try:
            db = get_mongo_db()
            status_coll = db[self.status_collection_name]

            doc = await status_coll.find_one({"job": "quotes_ingestion"})

            if not doc:
                return {
                    "last_sync_time": None,
                    "last_sync_time_iso": None,
                    "interval_seconds": settings.QUOTES_INGEST_INTERVAL_SECONDS,
                    "interval_minutes": settings.QUOTES_INGEST_INTERVAL_SECONDS / 60,
                    "data_source": None,
                    "success": None,
                    "records_count": 0,
                    "error_message": "尚未执行过同步"
                }

            # 移除 _id 字段
            doc.pop("_id", None)
            doc.pop("job", None)

            # 添加分钟数
            doc["interval_minutes"] = doc.get("interval_seconds", 0) / 60

            # 🔥 格式化时间（确保转换为本地时区）
            if "last_sync_time" in doc and doc["last_sync_time"]:
                dt = doc["last_sync_time"]
                # MongoDB 返回的是 UTC 时间的 datetime 对象（aware 或 naive）
                # 如果是 naive，添加 UTC 时区；如果是 aware，转换为本地时区
                if dt.tzinfo is None:
                    # naive datetime，假设是 UTC
                    dt = dt.replace(tzinfo=ZoneInfo("UTC"))
                # 转换为本地时区
                dt_local = dt.astimezone(self.tz)
                doc["last_sync_time"] = dt_local.strftime("%Y-%m-%d %H:%M:%S")

            return doc

        except Exception as e:
            logger.error(f"获取同步状态失败: {e}")
            return {
                "last_sync_time": None,
                "last_sync_time_iso": None,
                "interval_seconds": settings.QUOTES_INGEST_INTERVAL_SECONDS,
                "interval_minutes": settings.QUOTES_INGEST_INTERVAL_SECONDS / 60,
                "data_source": None,
                "success": None,
                "records_count": 0,
                "error_message": f"获取状态失败: {str(e)}"
            }

    def _check_tushare_permission(self) -> bool:
        """
        检测 Tushare rt_k 接口权限

        Returns:
            True: 有付费权限（可高频调用）
            False: 免费用户（每小时最多2次）
        """
        if self._tushare_permission_checked:
            return self._tushare_has_premium or False

        try:
            from app.utils.ds_key_utils import get_datasource_api_key
            token = get_datasource_api_key("tushare")
            if not token or not token.strip():
                logger.info("Tushare 未配置 Token，跳过权限检测")
                self._tushare_has_premium = False
                self._tushare_permission_checked = True
                return False

            try:
                import tushare as ts
                ts.set_token(token)
                pro = ts.pro_api()
                df = pro.daily(ts_code='000001.SZ', limit=1)
                if df is not None and not getattr(df, 'empty', True):
                    logger.info("✅ 检测到 Tushare rt_k 接口权限（付费用户）")
                    self._tushare_has_premium = True
                else:
                    logger.info("⚠️ Tushare rt_k 接口返回空数据（可能是免费用户或接口限制）")
                    self._tushare_has_premium = False
            except Exception as e:
                error_msg = str(e).lower()
                if "权限" in error_msg or "permission" in error_msg or "没有访问" in error_msg:
                    logger.info("⚠️ Tushare rt_k 接口无权限（免费用户）")
                    self._tushare_has_premium = False
                else:
                    logger.warning(f"⚠️ Tushare rt_k 接口测试失败: {e}")
                    self._tushare_has_premium = False

            self._tushare_permission_checked = True
            return self._tushare_has_premium or False

        except Exception as e:
            logger.warning(f"Tushare 权限检测失败: {e}")
            self._tushare_has_premium = False
            self._tushare_permission_checked = True
            return False

    def _can_call_tushare(self) -> bool:
        """
        判断是否可以调用 Tushare rt_k 接口

        Returns:
            True: 可以调用
            False: 超过限制，不能调用
        """
        # 如果是付费用户，不限制调用次数
        if self._tushare_has_premium:
            return True

        # 免费用户：检查每小时调用次数
        now = now_config_tz()
        one_hour_ago = now - timedelta(hours=1)

        # 清理1小时前的记录
        while self._tushare_call_times and self._tushare_call_times[0] < one_hour_ago:
            self._tushare_call_times.popleft()

        # 检查是否超过限制
        if len(self._tushare_call_times) >= self._tushare_hourly_limit:
            logger.warning(
                f"⚠️ Tushare rt_k 接口已达到每小时调用限制 ({self._tushare_hourly_limit}次)，"
                f"跳过本次调用，使用 AKShare 备用接口"
            )
            return False

        return True

    def _record_tushare_call(self) -> None:
        """记录 Tushare 调用时间"""
        self._tushare_call_times.append(now_config_tz())

    def _get_next_source(self) -> Tuple[str, Optional[str]]:
        """
        获取下一个数据源（轮换机制）

        Returns:
            (source_type, akshare_api):
                - source_type: "tushare" | "akshare"
                - akshare_api: "eastmoney" | "sina" (仅当 source_type="akshare" 时有效)
        """
        if not settings.QUOTES_ROTATION_ENABLED:
            # 未启用轮换，使用默认优先级
            return "tushare", None

        # 轮换逻辑：0=Tushare, 1=AKShare东方财富, 2=AKShare新浪财经
        current_source = self._rotation_sources[self._rotation_index]

        # 更新轮换索引（下次使用下一个接口）
        self._rotation_index = (self._rotation_index + 1) % len(self._rotation_sources)

        if current_source == "tushare":
            return "tushare", None
        elif current_source == "akshare_eastmoney":
            return "akshare", "eastmoney"
        else:  # akshare_sina
            return "akshare", "sina"

    def _is_trading_time(self, now: Optional[datetime] = None) -> bool:
        """
        判断是否在交易时间或收盘后缓冲期

        交易时间：
        - 上午：9:30-11:30
        - 下午：13:00-15:00
        - 收盘后缓冲期：15:00-15:30（确保获取到收盘价）

        收盘后缓冲期说明：
        - 交易时间结束后继续获取30分钟
        - 假设6分钟一次，可以增加3次同步机会（15:06, 15:12, 15:18）
        - 大大降低错过收盘价的风险
        """
        now = now or now_config_tz()
        # 工作日 Mon-Fri
        if now.weekday() > 4:
            return False
        t = now.time()
        # 上交所/深交所常规交易时段
        morning = dtime(9, 30)
        noon = dtime(11, 30)
        afternoon_start = dtime(13, 0)
        # 收盘后缓冲期（延长30分钟到15:30）
        buffer_end = dtime(15, 30)

        return (morning <= t <= noon) or (afternoon_start <= t <= buffer_end)

    async def _collection_empty(self) -> bool:
        db = get_mongo_db()
        coll = db[self.collection_name]
        try:
            count = await coll.estimated_document_count()
            return count == 0
        except Exception as e:
            logger.debug(f"检查集合是否为空失败: {e}")
            return True

    async def _collection_stale(self, latest_trade_date: Optional[str]) -> bool:
        if not latest_trade_date:
            return False
        db = get_mongo_db()
        coll = db[self.collection_name]
        try:
            cursor = coll.find({}, {"trade_date": 1}).sort("trade_date", -1).limit(1)
            docs = await cursor.to_list(length=1)
            if not docs:
                return True
            doc_td = str(docs[0].get("trade_date") or "")
            return doc_td < str(latest_trade_date)
        except Exception as e:
            logger.debug(f"检查集合数据时效失败: {e}")
            return True

    async def _bulk_upsert(self, quotes_map: Dict[str, Dict], trade_date: str, source: Optional[str] = None) -> None:
        db = get_mongo_db()
        coll = db[self.collection_name]
        ops = []
        updated_at = now_config_tz()
        for code, q in quotes_map.items():
            if not code:
                continue
            symbol6 = self._normalize_stock_code(code)
            if not symbol6:
                continue

            volume = q.get("volume")
            if symbol6 in ["300750", "000001", "600000"]:
                logger.info(f"📊 [写入market_quotes] {symbol6} - volume={volume}, amount={q.get('amount')}, source={source}")

            # 仅写入非 None 的字段，避免覆盖已有值
            set_doc = {
                "symbol": symbol6,
                "trade_date": trade_date,
                "data_source": source,
                "updated_at": updated_at,
            }
            for field, raw_val in [
                ("close", q.get("close")),
                ("pct_chg", q.get("pct_chg")),
                ("amount", q.get("amount")),
                ("volume", volume),
                ("open", q.get("open")),
                ("high", q.get("high")),
                ("low", q.get("low")),
                ("pre_close", q.get("pre_close")),
            ]:
                if raw_val is not None:
                    set_doc[field] = raw_val

            ops.append(
                UpdateOne(
                    {"symbol": symbol6},
                    {"$set": set_doc},
                    upsert=True,
                )
            )
        if not ops:
            logger.info("无可写入的数据，跳过")
            return
        result = await coll.bulk_write(ops, ordered=False)
        logger.info(
            f"✅ 行情入库完成 source={source}, matched={result.matched_count}, upserted={len(result.upserted_ids) if result.upserted_ids else 0}, modified={result.modified_count}"
        )

    async def _fix_missing_fields(self) -> None:
        """修复 market_quotes 中缺失的字段（pct_chg、turnover_rate 等），从 daily_quotes 补齐。"""
        db = get_mongo_db()
        coll = db[self.collection_name]

        # 查找缺少 pct_chg 的记录（字段不存在或为 null）
        cursor = coll.find({"pct_chg": None}, {"symbol": 1})
        missing_symbols = [doc["symbol"] for doc in await cursor.to_list(length=None)]

        if not missing_symbols:
            logger.info("✅ market_quotes 所有记录均包含 pct_chg，无需修复")
            return

        logger.info(f"📊 需要修复 {len(missing_symbols)} 条记录的缺失字段")

        # 从 daily_quotes 获取最新数据补齐
        daily_coll = db[get_collection_name("daily_quotes", self._market)]
        ops = []
        for symbol in missing_symbols:
            dq = await daily_coll.find_one(
                {"symbol": symbol},
                sort=[("trade_date", -1)],
            )
            if not dq:
                continue
            ops.append(UpdateOne(
                {"symbol": symbol},
                {"$set": {
                    "pct_chg": dq.get("pct_chg"),
                    "pre_close": dq.get("pre_close"),
                    "turnover_rate": dq.get("turnover_rate"),
                    "trade_date": dq.get("trade_date"),
                }},
            ))
        if ops:
            result = await coll.bulk_write(ops, ordered=False)
            logger.info(f"✅ 修复完成: modified={result.modified_count}")

    async def backfill_from_historical_data(self) -> None:
        """
        从历史数据集合导入前一天的收盘数据到 market_quotes
        - 如果 market_quotes 集合为空，导入所有数据
        - 如果 market_quotes 集合不为空，检查并修复缺失的字段
        """
        try:
            # 检查 market_quotes 是否为空
            is_empty = await self._collection_empty()

            if not is_empty:
                # 集合不为空，检查是否有成交量缺失的记录
                logger.info("✅ market_quotes 集合不为空，检查是否需要修复成交量...")
                await self._fix_missing_fields()
                return

            logger.info("📊 market_quotes 集合为空，开始从历史数据导入")

            db = get_mongo_db()

            # 获取最新交易日
            try:
                latest_trade_date = self._find_latest_trade_date()
                if not latest_trade_date:
                    logger.warning("⚠️ 无法获取最新交易日，跳过历史数据导入")
                    return
            except Exception as e:
                logger.warning(f"⚠️ 获取最新交易日失败: {e}，跳过历史数据导入")
                return

            logger.info(f"📊 从历史数据集合导入 {latest_trade_date} 的收盘数据到 market_quotes")

            # 从 stock_daily_quotes 集合查询最新交易日的数据
            daily_quotes_collection = db[get_collection_name("daily_quotes", self._market)]
            cursor = daily_quotes_collection.find({
                "trade_date": latest_trade_date,
                "period": "daily"
            })

            docs = await cursor.to_list(length=None)

            if not docs:
                logger.debug(f"⚠️ 历史数据集合中未找到 {latest_trade_date} 的数据")
                logger.debug("⚠️ market_quotes 和历史数据集合都为空，请先同步历史数据或实时行情")
                return

            logger.info(f"✅ 从历史数据集合找到 {len(docs)} 条记录")

            # 转换为 quotes_map 格式
            quotes_map = {}
            for doc in docs:
                code = doc.get("symbol") or doc.get("code")
                if not code:
                    continue
                symbol6 = str(code).zfill(6)

                # 🔥 获取成交量，优先使用 volume 字段
                volume_value = doc.get("volume") or doc.get("vol")
                data_source = doc.get("data_source", "")

                if symbol6 in ["300750", "000001", "600000"]:
                    logger.info(f"📊 [回填] {symbol6} - volume={doc.get('volume')}, vol={doc.get('vol')}, data_source={data_source}")

                quotes_map[symbol6] = {
                    "close": doc.get("close"),
                    "pct_chg": doc.get("pct_chg"),
                    "amount": doc.get("amount"),
                    "volume": volume_value,
                    "open": doc.get("open"),
                    "high": doc.get("high"),
                    "low": doc.get("low"),
                    "pre_close": doc.get("pre_close"),
                }

            if quotes_map:
                await self._bulk_upsert(quotes_map, latest_trade_date, "historical_data")
                logger.info(f"✅ 成功从历史数据导入 {len(quotes_map)} 条收盘数据到 market_quotes")
            else:
                logger.warning("⚠️ 历史数据转换后为空，无法导入")

        except Exception as e:
            logger.error(f"❌ 从历史数据导入失败: {e}")
            import traceback
            logger.error(f"堆栈跟踪:\n{traceback.format_exc()}")

    async def backfill_last_close_snapshot(self) -> None:
        """一次性补齐上一笔收盘快照（用于冷启动或数据陈旧）。允许在休市期调用。"""
        try:
            # 使用近实时快照作为兜底，休市期返回的即为最后收盘数据
            quotes_map, source = self._get_realtime_quotes()
            if not quotes_map:
                logger.warning("backfill: 未获取到行情数据，跳过")
                return
            try:
                trade_date = self._find_latest_trade_date() or format_date_compact(now_config_tz())
            except Exception as e:
                logger.debug(f"获取最新交易日失败，使用当前日期: {e}")
                trade_date = format_date_compact(now_config_tz())
            await self._bulk_upsert(quotes_map, trade_date, source)
        except Exception as e:
            logger.error(f"❌ backfill 行情补数失败: {e}")

    async def backfill_last_close_snapshot_if_needed(self) -> None:
        """若集合为空或 trade_date 落后于最新交易日，则执行一次 backfill"""
        try:
            is_empty = await self._collection_empty()

            # 如果集合为空，优先从历史数据导入
            if is_empty:
                logger.info("🔁 market_quotes 集合为空，尝试从历史数据导入")
                await self.backfill_from_historical_data()
                return

            # 如果集合不为空但数据陈旧，使用实时接口更新
            latest_td = self._find_latest_trade_date()
            if await self._collection_stale(latest_td):
                logger.info("🔁 触发休市期/启动期 backfill 以填充最新收盘数据")
                await self.backfill_last_close_snapshot()
        except Exception as e:
            logger.warning(f"backfill 触发检查失败（忽略）: {e}")

    def _fetch_quotes_from_source(self, source_type: str, akshare_api: Optional[str] = None) -> Tuple[Optional[Dict], Optional[str]]:
        """
        从指定数据源获取行情

        Args:
            source_type: "tushare" | "akshare"
            akshare_api: "eastmoney" | "sina" (仅当 source_type="akshare" 时有效)

        Returns:
            (quotes_map, source_name)
        """
        try:
            import asyncio
            from app.data.core.interface import DataInterface

            if source_type == "tushare":
                # 检查是否可以调用 Tushare
                if not self._can_call_tushare():
                    return None, None

                logger.info("📊 使用 Tushare 接口获取实时行情")

                async def _fetch_tushare():
                    di = DataInterface.get_instance()
                    result = await di.read("CN", "market_quotes", symbol="__all__")
                    return result.get("data")

                loop = asyncio.get_event_loop()
                data = loop.run_until_complete(_fetch_tushare())
                if data is not None:
                    self._record_tushare_call()
                    if isinstance(data, dict):
                        return data, "tushare"
                    elif isinstance(data, list) and data:
                        quotes_map = {}
                        for doc in data:
                            sym = str(doc.get("symbol", "")).zfill(6)
                            if sym:
                                quotes_map[sym] = doc
                        return quotes_map, "tushare"
                logger.warning("Tushare 返回空数据")
                return None, None

            elif source_type == "akshare":
                api_name = akshare_api or "eastmoney"
                logger.info(f"📊 使用 AKShare {api_name} 接口获取实时行情")

                async def _fetch_akshare():
                    di = DataInterface.get_instance()
                    result = await di.read("CN", "market_quotes", symbol="__all__")
                    return result.get("data")

                loop = asyncio.get_event_loop()
                data = loop.run_until_complete(_fetch_akshare())
                if data is not None:
                    if isinstance(data, dict):
                        return data, f"akshare_{api_name}"
                    elif isinstance(data, list) and data:
                        quotes_map = {}
                        for doc in data:
                            sym = str(doc.get("symbol", "")).zfill(6)
                            if sym:
                                quotes_map[sym] = doc
                        return quotes_map, f"akshare_{api_name}"
                logger.warning(f"AKShare {api_name} 返回空数据")
                return None, None

            else:
                logger.error(f"未知数据源类型: {source_type}")
                return None, None

        except Exception as e:
            logger.error(f"从 {source_type} 获取行情失败: {e}")
            return None, None

    async def run_once(self) -> None:
        """
        执行一次采集与入库

        核心逻辑：
        1. 检测 Tushare 权限（首次运行）
        2. 按轮换顺序尝试获取行情：Tushare → AKShare东方财富 → AKShare新浪财经
        3. 任意一个接口成功即入库，失败则跳过本次采集
        """
        # 非交易时段处理
        if not self._is_trading_time():
            if settings.QUOTES_BACKFILL_ON_OFFHOURS:
                await self.backfill_last_close_snapshot_if_needed()
            else:
                logger.info("⏭️ 非交易时段，跳过行情采集")
            return

        try:
            # 首次运行：检测 Tushare 权限
            if settings.QUOTES_AUTO_DETECT_TUSHARE_PERMISSION and not self._tushare_permission_checked:
                logger.info("🔍 首次运行，检测 Tushare rt_k 接口权限...")
                has_premium = self._check_tushare_permission()

                if has_premium:
                    logger.info(
                        "✅ 检测到 Tushare 付费权限！建议将 QUOTES_INGEST_INTERVAL_SECONDS 设置为 5-60 秒以充分利用权限"
                    )
                else:
                    logger.info(
                        f"ℹ️ Tushare 免费用户，每小时最多调用 {self._tushare_hourly_limit} 次 rt_k 接口。"
                        f"当前采集间隔: {settings.QUOTES_INGEST_INTERVAL_SECONDS} 秒"
                    )

            # 获取下一个数据源
            source_type, akshare_api = self._get_next_source()

            # 尝试获取行情
            quotes_map, source_name = self._fetch_quotes_from_source(source_type, akshare_api)

            if not quotes_map:
                logger.warning(f"⚠️ {source_name or source_type} 未获取到行情数据，跳过本次入库")
                # 记录失败状态
                await self._record_sync_status(
                    success=False,
                    source=source_name or source_type,
                    records_count=0,
                    error_msg="未获取到行情数据"
                )
                return

            # 获取交易日
            try:
                trade_date = self._find_latest_trade_date() or format_date_compact(now_config_tz())
            except Exception as e:
                logger.debug(f"获取最新交易日失败，使用当前日期: {e}")
                trade_date = format_date_compact(now_config_tz())

            # 入库
            await self._bulk_upsert(quotes_map, trade_date, source_name)

            # 记录成功状态
            await self._record_sync_status(
                success=True,
                source=source_name,
                records_count=len(quotes_map),
                error_msg=None
            )

        except Exception as e:
            logger.error(f"❌ 行情入库失败: {e}")
            # 记录失败状态
            await self._record_sync_status(
                success=False,
                source=None,
                records_count=0,
                error_msg=str(e)
            )

    async def get_latest_daily_quote(self, symbol: str) -> Optional[Dict]:
        """
        获取 stock_daily_quotes 集合中指定股票的最新一条记录

        Args:
            symbol: 股票代码（6位）

        Returns:
            最新行情文档，不存在返回 None
        """
        try:
            db = get_mongo_db()
            symbol6 = str(symbol).zfill(6)

            doc = await db[get_collection_name("daily_quotes", self._market)].find_one(
                {"symbol": symbol6},
                sort=[("trade_date", -1)]
            )
            return doc

        except Exception as e:
            logger.error(f"获取最新日线数据失败 symbol={symbol}: {e}")
            return None

    async def get_market_quote(self, symbol: str) -> Optional[Dict]:
        """
        获取 market_quotes 集合中指定股票的行情

        Args:
            symbol: 股票代码（6位）

        Returns:
            行情文档，不存在返回 None
        """
        try:
            db = get_mongo_db()
            symbol6 = str(symbol).zfill(6)

            doc = await db[self.collection_name].find_one({"symbol": symbol6})
            return doc

        except Exception as e:
            logger.error(f"获取行情数据失败 symbol={symbol}: {e}")
            return None

    async def upsert_market_quote(self, symbol: str, quote_data: Dict) -> bool:
        """
        更新或插入 market_quotes 集合中的行情数据

        Args:
            symbol: 股票代码（6位）
            quote_data: 行情数据字典

        Returns:
            是否更新成功
        """
        try:
            db = get_mongo_db()
            symbol6 = str(symbol).zfill(6)

            result = await db[self.collection_name].update_one(
                {"symbol": symbol6},
                {"$set": quote_data},
                upsert=True
            )
            return result.modified_count > 0 or result.upserted_id is not None

        except Exception as e:
            logger.error(f"更新行情数据失败 symbol={symbol}: {e}")
            return False

    async def sync_latest_to_market_quotes(self, symbol: str) -> None:
        """
        将 stock_daily_quotes 中的最新数据同步到 market_quotes

        智能判断逻辑：
        - 如果 market_quotes 中已有更新的数据（trade_date 更新），则不覆盖
        - 如果 market_quotes 中没有数据或数据较旧，则更新

        Args:
            symbol: 股票代码（6位）
        """
        symbol6 = str(symbol).zfill(6)

        # 从 stock_daily_quotes 获取最新数据
        latest_doc = await self.get_latest_daily_quote(symbol6)

        if not latest_doc:
            logger.warning(f"⚠️ {symbol6}: stock_daily_quotes 中没有数据")
            return

        historical_trade_date = latest_doc.get("trade_date")

        # 检查 market_quotes 中是否已有更新的数据
        existing_quote = await self.get_market_quote(symbol6)

        if existing_quote:
            existing_trade_date = existing_quote.get("trade_date")

            # 如果 market_quotes 中的数据日期更新或相同，则不覆盖
            if existing_trade_date and historical_trade_date:
                # 比较日期字符串（格式：YYYY-MM-DD 或 YYYYMMDD）
                existing_date_str = str(existing_trade_date).replace("-", "")
                historical_date_str = str(historical_trade_date).replace("-", "")

                if existing_date_str >= historical_date_str:
                    logger.info(
                        f"⏭️ {symbol6}: market_quotes 中的数据日期 >= 历史数据日期 "
                        f"(market_quotes: {existing_trade_date}, historical: {historical_trade_date})，跳过覆盖"
                    )
                    return

        # 提取需要的字段
        quote_data = {
            "symbol": symbol6,
            "close": latest_doc.get("close"),
            "open": latest_doc.get("open"),
            "high": latest_doc.get("high"),
            "low": latest_doc.get("low"),
            "volume": latest_doc.get("volume"),
            "amount": latest_doc.get("amount"),
            "pct_chg": latest_doc.get("pct_chg"),
            "pre_close": latest_doc.get("pre_close"),
            "trade_date": latest_doc.get("trade_date"),
            "updated_at": now_config_tz()
        }

        logger.info(
            f"📊 [同步到market_quotes] {symbol6} - "
            f"volume={quote_data['volume']}, amount={quote_data['amount']}, trade_date={quote_data['trade_date']}"
        )

        # 更新 market_quotes
        await self.upsert_market_quote(symbol6, quote_data)

