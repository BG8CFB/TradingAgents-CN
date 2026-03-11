from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional
import os

from app.services.config_service import config_service
from app.utils.time_utils import now_utc


class ConfigProvider:
    """Effective configuration provider with simple env→DB merge and TTL cache.

    - Priority: ENV > DB
    - Cache TTL: configurable (default 60s)
    - Invalidate on writes: caller should invoke `invalidate()` after writes
    - Version tracking: each config update increments version to detect changes
    """

    def __init__(self, ttl_seconds: int = 60) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._cache_settings: Optional[Dict[str, Any]] = None
        self._cache_time: Optional[datetime] = None
        self._cache_version: int = 0  # 🔧 添加版本号追踪配置变更

    def invalidate(self) -> None:
        """失效缓存并递增版本号"""
        self._cache_settings = None
        self._cache_time = None
        self._cache_version += 1  # 🔧 版本号递增，确保所有服务感知到变更

    @property
    def current_version(self) -> int:
        """获取当前配置版本号"""
        return self._cache_version

    def _is_cache_valid(self) -> bool:
        return (
            self._cache_settings is not None
            and self._cache_time is not None
            and now_utc() - self._cache_time < self._ttl
        )

    async def get_effective_system_settings(self) -> Dict[str, Any]:
        if self._is_cache_valid():
            # 🔧 返回配置的副本，避免外部修改缓存
            return {
                "config": dict(self._cache_settings or {}),
                "version": self._cache_version,
                "cached_at": self._cache_time.isoformat() if self._cache_time else None
            }

        # Load DB settings
        cfg = await config_service.get_system_config()
        base: Dict[str, Any] = {}
        if cfg and getattr(cfg, "system_settings", None):
            try:
                base = dict(cfg.system_settings)
            except Exception:
                base = {}

        # Merge ENV over DB (best-effort heuristics):
        # - if ENV with exact key exists -> override
        # - try uppercased and dot/space to underscore variants
        merged: Dict[str, Any] = dict(base)
        for k, v in list(base.items()):
            candidates = [
                k,
                k.upper(),
                str(k).replace(".", "_").replace(" ", "_").upper(),
            ]
            found = None
            for ek in candidates:
                if ek in os.environ:
                    found = os.environ.get(ek)
                    break
            if found is not None:
                merged[k] = found

        # Cache
        self._cache_settings = dict(merged)
        self._cache_time = now_utc()

        # 🔧 返回配置和版本号
        return {
            "config": dict(merged),
            "version": self._cache_version,
            "cached_at": self._cache_time.isoformat()
        }
    async def get_system_settings_meta(self) -> Dict[str, Dict[str, Any]]:
        """Return metadata for system settings keys including sensitivity, editability and source.
        Fields per key:
          - sensitive: bool (by keyword patterns)
          - editable: bool (False if sensitive or source is environment; True otherwise)
          - source: 'environment' | 'database' | 'default'
          - has_value: bool (effective value is not None/empty)
        """
        # Load DB settings raw
        cfg = await config_service.get_system_config()
        db_settings: Dict[str, Any] = {}
        if cfg and getattr(cfg, "system_settings", None):
            try:
                db_settings = dict(cfg.system_settings)
            except Exception:
                db_settings = {}

        def _env_override_for_key(key: str) -> Optional[Any]:
            candidates = [
                key,
                key.upper(),
                str(key).replace(".", "_").replace(" ", "_").upper(),
            ]
            for ek in candidates:
                if ek in os.environ:
                    return os.environ.get(ek)
            return None

        sens_patterns = ("key", "secret", "password", "token", "client_secret")
        meta: Dict[str, Dict[str, Any]] = {}
        for k, v in db_settings.items():
            env_v = _env_override_for_key(k)
            source = "environment" if env_v is not None else ("database" if v is not None else "default")
            sensitive = isinstance(k, str) and any(p in k.lower() for p in sens_patterns)
            editable = not sensitive and source != "environment"
            effective_val = env_v if env_v is not None else v
            has_value = effective_val not in (None, "")
            meta[k] = {
                "sensitive": bool(sensitive),
                "editable": bool(editable),
                "source": source,
                "has_value": bool(has_value),
            }
        return meta



# Module-level singleton
provider = ConfigProvider(ttl_seconds=60)

