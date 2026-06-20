"""新闻域同步"""

import logging
import time
from typing import Optional

from .base_domain_sync import BaseDomainSync, DomainSyncResult

logger = logging.getLogger(__name__)


class NewsSync(BaseDomainSync):
    """新闻数据同步"""

    domain = "news"
    description = "A股新闻数据"

    async def sync(
        self,
        symbol: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        **kwargs,
    ) -> DomainSyncResult:
        start = time.monotonic()
        providers = kwargs.get("providers", {})

        if not symbol:
            return DomainSyncResult(
                domain=self.domain, success=False,
                error="必须指定 symbol 参数",
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        try:
            fetch_result = await self._router.fetch(
                self.domain,
                symbol=symbol,
                providers=providers,
            )

            duration_ms = int((time.monotonic() - start) * 1000)

            if fetch_result.success and fetch_result.data is not None:
                records = await self._write_to_mongo(
                    fetch_result.data, fetch_result.source,
                    filter_fields=["symbol", "title"],
                )

                result = DomainSyncResult(
                    domain=self.domain,
                    success=True,
                    source=fetch_result.source,
                    fallback_from=fetch_result.fallback_from,
                    records_synced=records,
                    duration_ms=duration_ms,
                )
            else:
                result = DomainSyncResult(
                    domain=self.domain,
                    success=False,
                    source=fetch_result.source,
                    error=fetch_result.error or "数据获取失败",
                    duration_ms=duration_ms,
                )

        except Exception as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            result = DomainSyncResult(
                domain=self.domain, success=False,
                error=str(e), duration_ms=duration_ms,
            )

        event_type = "SYNC_SUCCESS" if result.success else "SYNC_FAILED"
        await self._write_sync_event(result, event_type)
        await self._write_checkpoint(
            result.source, "success" if result.success else "failed",
            result.records_synced, result.duration_ms,
        )

        return result
