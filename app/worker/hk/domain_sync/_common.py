"""港股域同步通用辅助函数。

通过 :class:`BaseMarketDomainSync` 子类化实现，避免与 US 的实现重复。
Provider/Adapter 的获取统一收敛在 FallbackRouter（与 CN 侧共享工厂与四件套）。
"""

import logging
from typing import Any, Callable, Dict, Optional

from app.worker.base_market_sync import BaseMarketDomainSync

logger = logging.getLogger(__name__)


class HKDomainSync(BaseMarketDomainSync):
    """港股域同步通用实现。"""

    market = "HK"

    def __init__(self, domain: str):
        self.domain = domain


async def sync_domain(
    domain: str,
    provider_method: str,
    provider_kwargs_fn: Optional[Callable] = None,
) -> Dict[str, Any]:
    """通用港股域同步（委托给 BaseMarketDomainSync）。

    Args:
        domain: 数据域名称
        provider_method: Provider 上的方法名
        provider_kwargs_fn: 可选的函数，返回传递给 provider 方法的 kwargs
    """
    syncer = HKDomainSync(domain=domain)
    return await syncer.sync(
        provider_method=provider_method,
        provider_kwargs_fn=provider_kwargs_fn,
    )
