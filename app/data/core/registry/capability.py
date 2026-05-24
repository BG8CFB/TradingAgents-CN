"""能力注册表 — market × domain × source 能力管理。"""

import logging
from typing import Dict, List, Optional, Tuple

from app.data.schema.base.enums import SupportLevel
from app.data.storage.cache.memory_cache import TTLCache

logger = logging.getLogger(__name__)

_user_priority_cache = TTLCache(default_ttl=30)


class CapabilityRegistry:
    """数据源能力注册表。

    内部存储: Dict[Tuple[market, domain], Dict[source, SupportLevel]]
    """

    def __init__(self):
        self._capabilities: Dict[Tuple[str, str], Dict[str, SupportLevel]] = {}
        self._load_from_default_yaml()

    def _load_from_default_yaml(self) -> None:
        """启动时从 capability_matrix.yaml 加载默认能力。"""
        from app.data.config import load_yaml
        data = load_yaml("capability_matrix.yaml")
        if data:
            self.load_from_yaml(data)

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

    def get_available_sources(self, domain: str, market: Optional[str] = None) -> List[str]:
        """获取指定域在特定市场或所有市场中可用的数据源。"""
        sources = set()
        for (m, d), src_map in self._capabilities.items():
            if d == domain and (market is None or m == market):
                for s, level in src_map.items():
                    if level != SupportLevel.NONE:
                        sources.add(s)
        return sorted(sources)

    def get_support_level(self, domain: str, source: str, market: Optional[str] = None) -> SupportLevel:
        """获取某源对某域的支持级别。若指定 market 则精确匹配，否则全市场搜索。"""
        for (m, d), src_map in self._capabilities.items():
            if d == domain and source in src_map and (market is None or m == market):
                return src_map[source]
        return SupportLevel.NONE

    def set_user_priority(self, market: str, domain: str, sources: List[str]) -> None:
        """用户自定义优先级（暂存内存，由 PriorityConfig 持久化）。

        将用户优先级写入内存缓存（30s TTL），并同步更新
        get_ordered_sources 中各市场的排序结果。
        """
        cache_key = f"priority:{market}:{domain}"
        _user_priority_cache.set(cache_key, sources)
        logger.info(f"用户优先级已更新: {market}/{domain} → {sources}")

    def get_matrix_summary(self, market: Optional[str] = None) -> Dict[str, Dict[str, str]]:
        """获取能力矩阵摘要 {domain: {source: level}}。若指定 market 则仅返回该市场。"""
        summary: Dict[str, Dict[str, str]] = {}
        for (m, domain), src_map in self._capabilities.items():
            if market is not None and m != market:
                continue
            if domain not in summary:
                summary[domain] = {}
            for source, level in src_map.items():
                summary[domain][source] = level.value
        return summary
