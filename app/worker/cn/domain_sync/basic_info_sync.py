"""基础信息域同步"""

import logging
import time
from typing import Any, Dict, List, Optional

from .base_domain_sync import BaseDomainSync, DomainSyncResult
from app.data.processor.fallback_router import FallbackRouter

logger = logging.getLogger(__name__)


class BasicInfoSync(BaseDomainSync):
    """股票基础信息同步"""

    domain = "basic_info"
    description = "A股股票基础信息（名称、行业、上市日期等）"

    async def sync(
        self,
        symbol: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        **kwargs,
    ) -> DomainSyncResult:
        start = time.monotonic()
        providers = kwargs.get("providers", {})

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
                    filter_fields=["symbol"],
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
