"""用户优先级配置 — YAML 默认 + MongoDB 用户覆盖 + 30s TTL 缓存。"""

import logging
from typing import Dict, List, Optional

from app.data.storage.cache.memory_cache import TTLCache
from app.data.config import load_yaml

logger = logging.getLogger(__name__)

_cache = TTLCache(default_ttl=30)


class PriorityConfig:
    """用户优先级配置管理。"""

    def __init__(self):
        self._defaults: Dict[str, Dict[str, List[str]]] = {}
        self._load_defaults()

    def _load_defaults(self) -> None:
        data = load_yaml("default_priorities.yaml")
        for market, domains in data.items():
            self._defaults[market] = {}
            for domain, sources in domains.items():
                if isinstance(sources, list):
                    self._defaults[market][domain] = sources

    async def get_priority(self, market: str, domain: str) -> List[str]:
        """获取最终优先级列表（用户覆盖 > 默认）。"""
        cache_key = f"priority:{market}:{domain}"
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached

        # 尝试从 MongoDB 加载用户配置
        user_priority = await self._load_user_config(market, domain)
        if user_priority:
            _cache.set(cache_key, user_priority)
            return user_priority

        # 回退到默认
        default = self._defaults.get(market, {}).get(domain, [])
        _cache.set(cache_key, default)
        return default

    async def _load_user_config(self, market: str, domain: str) -> Optional[List[str]]:
        try:
            from app.data.storage.mongo.repositories.metadata_repo import MetadataRepo
            repo = MetadataRepo()
            config = await repo.get_config("data_source_priority", market, domain)
            if config and "value" in config and "sources" in config["value"]:
                return config["value"]["sources"]
        except Exception as e:
            logger.debug(f"获取数据源优先级配置失败: {e}")
            pass
        return None

    def get_default_sources(self, market: str, domain: str = "basic_info") -> List[str]:
        """获取默认数据源优先级列表（同步，仅读取 YAML 默认值，不查 MongoDB）。"""
        return self._defaults.get(market, {}).get(domain, [])

    def invalidate_cache(self, market: str, domain: Optional[str] = None) -> None:
        if domain:
            _cache.invalidate(f"priority:{market}:{domain}")
        else:
            _cache.invalidate_pattern(f"priority:{market}:")
