"""美股域同步通用辅助函数。

通过 :class:`BaseMarketDomainSync` 子类化实现，避免与 HK 的实现重复。
"""

import logging
from typing import Any, Callable, Dict, List, Optional

from app.data.sources.us import get_us_provider, get_us_adapter
from app.worker.base_market_sync import BaseMarketDomainSync

logger = logging.getLogger(__name__)


class USDomainSync(BaseMarketDomainSync):
    """美股域同步通用实现。"""

    market = "US"

    def __init__(self, domain: str):
        self.domain = domain

    def get_provider(self, source_name: str) -> Any:
        return get_us_provider(source_name)

    def get_adapter(self, source_name: str) -> Any:
        return get_us_adapter(source_name)

    def get_default_filter_fields(self) -> List[str]:
        return ["symbol"]


async def sync_domain(
    domain: str,
    provider_method: str,
    adapter_method: str,
    provider_kwargs_fn: Optional[Callable] = None,
    filter_fields: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """通用美股域同步（委托给 BaseMarketDomainSync）。

    Args:
        domain: 数据域名称
        provider_method: Provider 上的方法名
        adapter_method: Adapter 上的方法名
        provider_kwargs_fn: 可选的函数，返回传递给 provider 方法的 kwargs
        filter_fields: MongoDB upsert 过滤字段
    """
    syncer = USDomainSync(domain=domain)
    return await syncer.sync(
        provider_method=provider_method,
        adapter_method=adapter_method,
        provider_kwargs_fn=provider_kwargs_fn,
        filter_fields=filter_fields,
    )
