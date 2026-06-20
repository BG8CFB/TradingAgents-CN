"""缓存服务 — 封装 Redis + 内存 TTLCache 访问，供 routers 调用。

设计目标：
- routers 不再直接 import ``app.data.storage.*``，所有存储操作走本 service；
- 集中维护禁止通过 API 删除的系统内部键前缀；
- TTLCache 实例通过 ``register_memory_cache`` 注入（由 app 启动时调用）。
"""

from typing import Dict, List, Optional, Tuple

from app.data.storage.cache.memory_cache import TTLCache
from app.data.storage.redis.client import get_redis

# 系统内部缓存键前缀：禁止通过 /items/{key} 接口删除
# 这些前缀承载认证状态、会话、限流配额等关键状态；误删会让用户被锁死或绕过限流
FORBIDDEN_KEY_PREFIXES: Tuple[str, ...] = (
    "token_blacklist:",     # logout 后吊销的 access_token
    "system_secrets:",      # JWT/CSRF 等系统密钥
    "session:",             # 用户会话
    "ratelimit:",           # 限流配额
    "auth:",                # 认证中间件状态
    "lock:",                # 分布式锁（避免误删导致并发保护失效）
)

# 应用层缓存的业务前缀；router 清理 / 清空操作针对此前缀做 scan
BUSINESS_CACHE_PATTERN = "foreign_stock:*"


class CacheService:
    """Redis + 内存 TTLCache 统一访问入口。"""

    _instance: Optional["CacheService"] = None
    _memory_cache: Optional[TTLCache] = None

    @classmethod
    def get_instance(cls) -> "CacheService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def register_memory_cache(cls, cache: TTLCache) -> None:
        """注入全局 TTLCache 实例（app 启动时调用一次）。"""
        cls._memory_cache = cache

    @classmethod
    def reset_instance(cls) -> None:
        """测试场景下重置（生产代码不应调用）。"""
        cls._instance = None
        cls._memory_cache = None

    @staticmethod
    def is_forbidden_key(key: str) -> bool:
        """判断是否禁止通过 cache API 删除的系统内部键。"""
        if not key:
            return False
        return any(key.startswith(prefix) for prefix in FORBIDDEN_KEY_PREFIXES)

    @staticmethod
    def _get_redis():
        """获取 Redis 客户端（可能返回 None）。"""
        try:
            return get_redis()
        except Exception:
            return None

    def get_memory_cache(self) -> Optional[TTLCache]:
        return self._memory_cache

    async def get_stats(self) -> Dict:
        """返回 Redis 与内存缓存的汇总统计。"""
        redis = self._get_redis()
        redis_info: Dict = {}
        total_keys = 0
        if redis:
            try:
                total_keys = await redis.dbsize()
                info = await redis.info("memory")
                redis_info = {
                    "used_memory_human": info.get("used_memory_human", "N/A"),
                    "used_memory_peak_human": info.get(
                        "used_memory_peak_human", "N/A"
                    ),
                }
            except Exception:
                pass

        memory_size = self._memory_cache.size() if self._memory_cache else 0
        return {
            "redis": {"totalKeys": total_keys, **redis_info},
            "memoryCache": {"size": memory_size},
            "totalSize": 0,
            "maxSize": 1024 * 1024 * 1024,
            "stockDataCount": 0,
            "newsDataCount": 0,
            "analysisDataCount": 0,
        }

    async def cleanup_old_cache(self) -> int:
        """清理 ``BUSINESS_CACHE_PATTERN`` 下未设置 TTL 的键。"""
        redis = self._get_redis()
        deleted = 0
        if not redis:
            return 0
        try:
            cursor = 0
            while True:
                cursor, keys = await redis.scan(
                    cursor, match=BUSINESS_CACHE_PATTERN, count=100
                )
                if keys:
                    for key in keys:
                        ttl = await redis.ttl(key)
                        if ttl == -1:
                            await redis.delete(key)
                            deleted += 1
                if cursor == 0:
                    break
        except Exception:
            pass
        return deleted

    async def clear_all(self) -> int:
        """清空 ``BUSINESS_CACHE_PATTERN`` 下所有键 + 内存缓存。"""
        redis = self._get_redis()
        deleted = 0
        if redis:
            try:
                cursor = 0
                while True:
                    cursor, keys = await redis.scan(
                        cursor, match=BUSINESS_CACHE_PATTERN, count=100
                    )
                    if keys:
                        await redis.delete(*keys)
                        deleted += len(keys)
                    if cursor == 0:
                        break
            except Exception:
                pass
        if self._memory_cache:
            self._memory_cache.clear()
        return deleted

    async def list_details(self, page: int, page_size: int) -> Dict:
        """分页列出 ``BUSINESS_CACHE_PATTERN`` 下键的详情。"""
        redis = self._get_redis()
        items: List[Dict] = []
        total = 0
        if not redis:
            return {"items": items, "total": total, "page": page, "page_size": page_size}

        try:
            all_keys = []
            cursor = 0
            while True:
                cursor, keys = await redis.scan(
                    cursor, match=BUSINESS_CACHE_PATTERN, count=100
                )
                all_keys.extend(keys)
                if cursor == 0:
                    break

            total = len(all_keys)
            start = (page - 1) * page_size
            end = start + page_size
            for key in all_keys[start:end]:
                key_str = key if isinstance(key, str) else key.decode()
                ttl = await redis.ttl(key)
                key_type = await redis.type(key)
                items.append({"key": key_str, "ttl": ttl, "type": key_type})
        except Exception:
            pass

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def delete_item(self, key: str) -> Tuple[bool, bool, bool]:
        """删除单个缓存条目，返回 ``(existed, redis_deleted, memory_deleted)``。

        若键被 ``FORBIDDEN_KEY_PREFIXES`` 命中则拒绝删除，抛 ``PermissionError``。
        """
        if self.is_forbidden_key(key):
            raise PermissionError("forbidden system cache key")

        redis_deleted = False
        redis = self._get_redis()
        if redis:
            try:
                deleted = await redis.delete(key)
                redis_deleted = deleted > 0
            except Exception:
                pass

        memory_deleted = False
        if self._memory_cache:
            memory_deleted = self._memory_cache.invalidate(key)

        existed = redis_deleted or memory_deleted
        return existed, redis_deleted, memory_deleted
