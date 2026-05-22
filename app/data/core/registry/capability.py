"""能力注册表 — market × domain × source 能力管理。"""

import logging
from typing import Dict, List, Optional, Tuple

from app.data.schema.base.enums import SupportLevel

logger = logging.getLogger(__name__)


class CapabilityRegistry:
    """数据源能力注册表。

    内部存储: Dict[Tuple[market, domain], Dict[source, SupportLevel]]
    """

    def __init__(self):
        self._capabilities: Dict[Tuple[str, str], Dict[str, SupportLevel]] = {}

    def register(self, market: str, domain: str, source: str, level: SupportLevel) -> None:
        """注册数据源能力。"""
        key = (market, domain)
        if key not in self._capabilities:
            self._capabilities[key] = {}
        self._capabilities[key][source] = level
        logger.debug(f"注册能力: {market}/{domain}/{source} = {level.value}")

    def load_from_yaml(self, yaml_data: dict) -> None:
        """从 capability_matrix.yaml 加载全部能力。"""
        for market, domains in yaml_data.items():
            for domain, sources in domains.items():
                for source, level_str in sources.items():
                    level = SupportLevel(level_str)
                    self.register(market, domain, source, level)

    def get_sources(self, market: str, domain: str) -> List[Tuple[str, SupportLevel]]:
        """获取某域所有可用数据源及其支持级别。"""
        key = (market, domain)
        if key not in self._capabilities:
            return []
        return list(self._capabilities[key].items())

    def get_ordered_sources(
        self,
        market: str,
        domain: str,
        user_priority: Optional[List[str]] = None,
        disabled_sources: Optional[List[str]] = None,
    ) -> List[str]:
        """获取按优先级排序的可用数据源列表。

        1. 过滤掉 disabled_sources
        2. 过滤掉 SupportLevel.NONE
        3. 按用户优先级排序（若提供）
        """
        sources = self.get_sources(market, domain)
        disabled = set(disabled_sources or [])

        # 过滤
        available = [(s, level) for s, level in sources if s not in disabled and level != SupportLevel.NONE]

        if user_priority:
            priority_set = {s: i for i, s in enumerate(user_priority)}
            available.sort(key=lambda x: priority_set.get(x[0], 999))

        return [s for s, _ in available]

    def remove_source(self, market: str, domain: str, source: str) -> None:
        """移除某数据源的能力（积分不足时使用）。"""
        key = (market, domain)
        if key in self._capabilities and source in self._capabilities[key]:
            del self._capabilities[key][source]
            logger.info(f"移除能力: {market}/{domain}/{source}")

    def is_supported(self, market: str, domain: str, source: str) -> bool:
        """检查某数据源是否支持某域。"""
        key = (market, domain)
        return key in self._capabilities and source in self._capabilities[key] and self._capabilities[key][source] != SupportLevel.NONE
