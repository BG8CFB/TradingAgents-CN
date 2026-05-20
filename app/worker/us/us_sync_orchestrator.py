"""
美股同步编排器

参照港股 HKSyncOrchestrator 结构。
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from app.data.processor.fallback_router import FallbackRouter
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)


@dataclass
class USSyncResult:
    success: bool = False
    domains: Dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0


class USSyncOrchestrator:
    """美股同步编排器"""

    def __init__(self, router: Optional[FallbackRouter] = None):
        self._router = router or FallbackRouter()

    async def sync_basic_info(self) -> USSyncResult:
        """同步美股基础信息"""
        import asyncio
        start = now_utc()
        try:
            from app.data.processor.capability_registry import CapabilityRegistry
            registry = CapabilityRegistry(market="US")
            sources = registry.get_ordered_sources("basic_info")

            for source_name in sources:
                provider = self._get_provider(source_name)
                if not provider:
                    continue
                try:
                    df = await provider.get_stock_list()
                    if df is None or df.empty:
                        continue
                    elapsed = (now_utc() - start).total_seconds() * 1000
                    return USSyncResult(
                        success=True,
                        domains={"basic_info": {"source": source_name, "count": len(df)}},
                        duration_ms=int(elapsed),
                    )
                except Exception as e:
                    logger.warning(f"US basic_info {source_name} 失败: {e}")
                    continue

            elapsed = (now_utc() - start).total_seconds() * 1000
            return USSyncResult(success=False, duration_ms=int(elapsed))
        except Exception as e:
            elapsed = (now_utc() - start).total_seconds() * 1000
            return USSyncResult(success=False, domains={"error": str(e)}, duration_ms=int(elapsed))

    def _get_provider(self, source_name: str):
        if source_name == "yfinance_us":
            from app.data.sources.us.yfinance_us.provider import YFinanceUSProvider
            return YFinanceUSProvider()
        elif source_name == "finnhub_us":
            from app.data.sources.us.finnhub_us.provider import FinnhubUSProvider
            return FinnhubUSProvider()
        return None
