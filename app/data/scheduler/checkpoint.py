"""检查点管理器。"""

import logging
from typing import Optional

from app.data.storage.mongo.repositories.metadata_repo import MetadataRepo

logger = logging.getLogger(__name__)


class CheckpointManager:
    """同步检查点管理。"""

    def __init__(self):
        self._repo = MetadataRepo()

    async def get_checkpoint(self, market: str, domain: str, source: str) -> Optional[str]:
        """获取检查点日期。"""
        cp = await self._repo.get_checkpoint(market, domain, source)
        return cp.get("last_sync_date") if cp else None

    async def get_checkpoint_doc(self, market: str, domain: str, source: str) -> Optional[dict]:
        """获取完整检查点文档（含 last_sync_time/last_sync_date/status 等）。

        供需要时间戳等字段的调用方使用（如 SchedulerMonitor.check_stale_tasks）。
        """
        return await self._repo.get_checkpoint(market, domain, source)

    async def update_checkpoint(
        self, market: str, domain: str, source: str, date: str, count: int
    ) -> None:
        """更新检查点。"""
        await self._repo.update_checkpoint(market, domain, source, date, count)

    async def reset_checkpoint(self, market: str, domain: str, source: str) -> None:
        """重置检查点（强制全量同步）。"""
        await self._repo.update_checkpoint(market, domain, source, "1970-01-01", 0)
