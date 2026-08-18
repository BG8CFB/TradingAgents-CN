"""域级同步基类"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.data.processor.fallback_router import FallbackRouter
from app.data.storage.mongo.collections import get_collection_name
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)


@dataclass
class DomainSyncResult:
    """单个域的同步结果"""
    domain: str
    success: bool = False
    source: str = ""
    fallback_from: Optional[str] = None
    records_synced: int = 0
    records_failed: int = 0
    duration_ms: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "success": self.success,
            "source": self.source,
            "fallback_from": self.fallback_from,
            "records_synced": self.records_synced,
            "records_failed": self.records_failed,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


class BaseDomainSync(ABC):
    """
    域级同步基类

    每个数据域独立实现 sync() 方法，内部通过 FallbackRouter
    自动选择最优数据源、处理重试和降级。
    """

    domain: str = ""
    description: str = ""

    def __init__(self, router: Optional[FallbackRouter] = None):
        if router is None:
            # 使用进程级单例，与其他 sync_job 共享熔断器 + 限流器
            router = FallbackRouter.get_instance()
        self._router = router

    async def _get_incremental_start_date(self, symbol: str) -> str:
        """
        计算增量同步起始日期。

        策略：sync_checkpoints → stock_basic_info.list_date → 兜底 30 天前
        """
        try:
            from app.core.database import get_mongo_db
            db = get_mongo_db()
        except Exception as e:
            logger.debug(f"获取数据库连接失败，使用默认30天前: {e}")
            return (now_utc() - timedelta(days=30)).strftime("%Y-%m-%d")

        # 1. 查 sync_checkpoints
        try:
            cp_collection = db[get_collection_name("sync_checkpoints", "CN")]
            checkpoint = await cp_collection.find_one(
                {"domain": self.domain},
                {"last_sync_date": 1},
                sort=[("last_sync_time", -1)],
            )
            if checkpoint and checkpoint.get("last_sync_date"):
                last = checkpoint["last_sync_date"]
                try:
                    last_dt = datetime.strptime(last, "%Y-%m-%d")
                    return (last_dt + timedelta(days=1)).strftime("%Y-%m-%d")
                except ValueError:
                    return last
        except Exception as e:
            logger.debug(f"查询同步检查点失败: {e}")
            pass

        # 2. 查 stock_basic_info 的 list_date
        try:
            bi_collection = db[get_collection_name("basic_info", "CN")]
            stock_info = await bi_collection.find_one(
                {"symbol": symbol},
                {"list_date": 1},
            )
            if stock_info and stock_info.get("list_date"):
                ld = stock_info["list_date"]
                if isinstance(ld, str):
                    if len(ld) == 8 and ld.isdigit():
                        return f"{ld[:4]}-{ld[4:6]}-{ld[6:]}"
                    return ld
                return ld.strftime("%Y-%m-%d")
        except Exception as e:
            logger.debug(f"查询上市日期失败: {symbol}: {e}")
            pass

        # 3. 兜底 30 天前
        return (now_utc() - timedelta(days=30)).strftime("%Y-%m-%d")

    @abstractmethod
    async def sync(
        self,
        symbol: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        **kwargs,
    ) -> DomainSyncResult:
        """执行同步（子类实现）"""

    async def _write_to_mongo(
        self, data: Any, source: str,
        filter_fields: Optional[List[str]] = None,
    ) -> int:
        """通用 MongoDB 写入"""
        import pandas as pd

        if data is None:
            return 0

        if isinstance(data, pd.DataFrame):
            if data.empty:
                return 0
            records = data.to_dict("records")
        elif isinstance(data, list):
            records = data
        elif isinstance(data, dict):
            records = [data]
        else:
            return 0

        if not records:
            return 0

        try:
            from app.core.database import get_mongo_db
            db = get_mongo_db()
        except Exception as e:
            logger.warning(f"无法连接 MongoDB，跳过写入: {e}")
            return 0

        collection_name = get_collection_name(self.domain, "CN")
        collection = db[collection_name]

        filter_fields = filter_fields or ["symbol", "trade_date"]

        from pymongo import UpdateOne

        now_iso = now_utc().isoformat()
        operations = []

        for rec in records:
            filter_doc = {}
            for f in filter_fields:
                if f in rec:
                    filter_doc[f] = rec[f]

            if not filter_doc:
                continue

            rec["data_source"] = source
            rec["updated_at"] = now_iso

            operations.append(UpdateOne(filter_doc, {"$set": rec}, upsert=True))

        if operations:
            try:
                result = await collection.bulk_write(operations, ordered=False)
                return result.upserted_count + result.modified_count
            except Exception as e:
                logger.error("写入 %s 失败: %s", collection_name, e)

        return 0

    async def _write_checkpoint(
        self, source: str, status: str, record_count: int, duration_ms: int,
    ) -> None:
        """写入同步检查点。

        通过 MetadataRepo 统一入口写入，确保 market 字段存在（历史 bug：
        旧实现直接 update_one 未写 market，被 get_all_checkpoints 的
        ``{market: "CN"}`` 过滤漏掉，导致 Dashboard 从不更新）。
        """
        try:
            from app.data.storage.mongo.repositories.metadata_repo import MetadataRepo

            now_iso = now_utc().isoformat()
            await MetadataRepo().update_checkpoint(
                market="CN",
                domain=self.domain,
                source=source,
                last_sync_date=now_iso[:10],
                record_count=record_count,
                status=status,
                duration_ms=duration_ms,
                scope="market",
                trigger="scheduled",
            )
        except Exception as e:
            logger.debug("写入检查点失败: %s", e)

    async def _write_sync_event(
        self, result: DomainSyncResult, event_type: str = "SYNC_SUCCESS",
    ) -> None:
        """写入同步事件"""
        try:
            from app.core.database import get_mongo_db
            db = get_mongo_db()
        except Exception as e:
            logger.debug(f"获取数据库连接失败，跳过写入同步事件: {e}")
            return

        collection_name = get_collection_name("sync_events", "CN")
        collection = db[collection_name]

        event = {
            "event_type": event_type,
            "domain": result.domain,
            "source": result.source,
            "symbol": None,
            "record_count": result.records_synced,
            "duration_ms": result.duration_ms,
            "error_message": result.error,
            "fallback_from": result.fallback_from,
            "data_source": "domain_sync",
            "updated_at": now_utc().isoformat(),
        }

        try:
            await collection.insert_one(event)
        except Exception as e:
            logger.debug(f"写入同步事件失败: {e}")
