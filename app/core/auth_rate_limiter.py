"""
登录防爆破限流器

针对 `/api/auth/login` 端点的失败计数 + 临时锁定机制，防止暴力破解。
设计目标：
- 基于 IP 和用户名双维度计数，覆盖"单 IP 爆破单账户"和"单 IP 爆破多账户"两类攻击
- 使用 Redis 作为后端（多实例共享、过期自动清理），无 Redis 时降级到进程内字典
- 只对"认证失败"计数，成功登录重置计数
- 锁定期满自动恢复，无需人工干预

阈值（参考 OWASP Authentication Cheat Sheet）：
- 单 IP + 单用户名：5 次失败 / 5 分钟 → 锁定该组合 15 分钟
- 单 IP（不限用户名）：20 次失败 / 5 分钟 → 锁定该 IP 30 分钟
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 默认阈值（可由调用方覆盖）
DEFAULT_USER_MAX_FAILURES = 5
DEFAULT_USER_WINDOW_SECONDS = 300  # 5 分钟
DEFAULT_USER_LOCK_SECONDS = 900  # 15 分钟

DEFAULT_IP_MAX_FAILURES = 20
DEFAULT_IP_WINDOW_SECONDS = 300  # 5 分钟
DEFAULT_IP_LOCK_SECONDS = 1800  # 30 分钟

_REDIS_KEY_PREFIX = "auth:rl"


@dataclass
class _Bucket:
    """进程内降级用的计数桶"""

    failures: List[float] = field(default_factory=list)
    locked_until: float = 0.0


class _InMemoryStore:
    """Redis 不可用时的进程内降级存储（单实例部署足够）"""

    def __init__(self) -> None:
        self._buckets: Dict[str, _Bucket] = defaultdict(_Bucket)
        self._lock = Lock()

    def _purge(self, bucket: _Bucket, now: float, window: int) -> None:
        cutoff = now - window
        bucket.failures = [ts for ts in bucket.failures if ts > cutoff]

    def count_failure(self, key: str, window: int) -> int:
        now = time.time()
        with self._lock:
            bucket = self._buckets[key]
            self._purge(bucket, now, window)
            bucket.failures.append(now)
            if bucket.locked_until < now:
                bucket.locked_until = 0.0
            return len(bucket.failures)

    def set_lock(self, key: str, lock_seconds: int) -> None:
        with self._lock:
            bucket = self._buckets[key]
            bucket.locked_until = time.time() + lock_seconds

    def is_locked(self, key: str) -> bool:
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                return False
            return bucket.locked_until > time.time()

    def reset(self, key: str) -> None:
        with self._lock:
            self._buckets.pop(key, None)


class AuthRateLimiter:
    """
    登录限流器

    两个独立维度：
    - user_key = f"{ip}:{username_lowercase}"：单 IP 针对单用户的失败计数
    - ip_key = f"ip:{ip}"：单 IP 所有用户的失败计数（防用户名枚举/轮换）

    使用：
        limiter = get_auth_rate_limiter()
        # 1. 检查是否已被锁定
        locked, reason, retry_after = limiter.check(ip, username)
        if locked:
            raise HTTPException(429, ...)
        # 2. 认证失败时记录
        limiter.record_failure(ip, username)
        # 3. 认证成功时清除
        limiter.reset(ip, username)
    """

    def __init__(
        self,
        user_max_failures: int = DEFAULT_USER_MAX_FAILURES,
        user_window_seconds: int = DEFAULT_USER_WINDOW_SECONDS,
        user_lock_seconds: int = DEFAULT_USER_LOCK_SECONDS,
        ip_max_failures: int = DEFAULT_IP_MAX_FAILURES,
        ip_window_seconds: int = DEFAULT_IP_WINDOW_SECONDS,
        ip_lock_seconds: int = DEFAULT_IP_LOCK_SECONDS,
    ) -> None:
        self.user_max_failures = user_max_failures
        self.user_window_seconds = user_window_seconds
        self.user_lock_seconds = user_lock_seconds
        self.ip_max_failures = ip_max_failures
        self.ip_window_seconds = ip_window_seconds
        self.ip_lock_seconds = ip_lock_seconds
        self._fallback = _InMemoryStore()

    def _redis(self):
        try:
            from app.core.database import get_redis_client

            client = get_redis_client()
            return client if client is not None else None
        except Exception as e:
            logger.debug(f"Redis 不可用，登录限流降级到进程内存储: {e}")
            return None

    @staticmethod
    def _user_key(ip: str, username: str) -> str:
        return f"{_REDIS_KEY_PREFIX}:u:{ip}:{(username or '').lower()}"

    @staticmethod
    def _ip_key(ip: str) -> str:
        return f"{_REDIS_KEY_PREFIX}:ip:{ip}"

    @staticmethod
    def _lock_key(base_key: str) -> str:
        return f"{base_key}:lock"

    async def check(self, ip: str, username: str) -> Tuple[bool, str, int]:
        """检查是否被锁定。返回 (is_locked, reason, retry_after_seconds)。"""
        redis = self._redis()
        user_key = self._user_key(ip, username)
        ip_key = self._ip_key(ip)

        if redis is not None:
            try:
                pipe = redis.pipeline()
                pipe.ttl(self._lock_key(user_key))
                pipe.ttl(self._lock_key(ip_key))
                user_ttl, ip_ttl = await pipe.execute()
                if user_ttl and user_ttl > 0:
                    return True, "用户名已被临时锁定", int(user_ttl)
                if ip_ttl and ip_ttl > 0:
                    return True, "IP 已被临时锁定", int(ip_ttl)
                return False, "", 0
            except Exception as e:
                logger.warning(f"Redis 检查锁定状态失败，降级内存: {e}")

        if self._fallback.is_locked(self._lock_key(user_key)):
            return True, "用户名已被临时锁定", 0
        if self._fallback.is_locked(self._lock_key(ip_key)):
            return True, "IP 已被临时锁定", 0
        return False, "", 0

    async def record_failure(self, ip: str, username: str) -> Tuple[bool, str, int]:
        """
        记录一次失败。如果触发阈值则锁定，返回 (now_locked, reason, lock_seconds)。
        """
        redis = self._redis()
        user_key = self._user_key(ip, username)
        ip_key = self._ip_key(ip)

        if redis is not None:
            try:
                pipe = redis.pipeline()
                pipe.incr(user_key)
                pipe.expire(user_key, self.user_window_seconds)
                pipe.incr(ip_key)
                pipe.expire(ip_key, self.ip_window_seconds)
                user_count, _, ip_count, _ = await pipe.execute()

                if user_count and int(user_count) >= self.user_max_failures:
                    await redis.set(
                        self._lock_key(user_key), "1", ex=self.user_lock_seconds
                    )
                    logger.warning(
                        f"🚨 登录限流：锁定 用户/IP ({username}/{ip}) "
                        f"{self.user_lock_seconds}s（失败 {user_count}/{self.user_max_failures}）"
                    )
                    return (
                        True,
                        "用户名或密码错误次数过多，已临时锁定",
                        self.user_lock_seconds,
                    )

                if ip_count and int(ip_count) >= self.ip_max_failures:
                    await redis.set(
                        self._lock_key(ip_key), "1", ex=self.ip_lock_seconds
                    )
                    logger.warning(
                        f"🚨 登录限流：锁定 IP {ip} "
                        f"{self.ip_lock_seconds}s（失败 {ip_count}/{self.ip_max_failures}）"
                    )
                    return (
                        True,
                        "该 IP 登录失败次数过多，已临时锁定",
                        self.ip_lock_seconds,
                    )

                return False, "", 0
            except Exception as e:
                logger.warning(f"Redis 记录失败计数异常，降级内存: {e}")

        # 内存降级路径
        user_count = self._fallback.count_failure(user_key, self.user_window_seconds)
        ip_count = self._fallback.count_failure(ip_key, self.ip_window_seconds)

        if user_count >= self.user_max_failures:
            self._fallback.set_lock(self._lock_key(user_key), self.user_lock_seconds)
            return True, "用户名或密码错误次数过多，已临时锁定", self.user_lock_seconds
        if ip_count >= self.ip_max_failures:
            self._fallback.set_lock(self._lock_key(ip_key), self.ip_lock_seconds)
            return True, "该 IP 登录失败次数过多，已临时锁定", self.ip_lock_seconds
        return False, "", 0

    async def reset(self, ip: str, username: str) -> None:
        """认证成功时清除该 IP + 用户名的失败计数。

        设计取舍：仅清 user 维度计数，保留 IP 维度计数。
        原因：攻击者可能用"先成功登录一次，再爆破其他账户"的策略穿插绕过；
        IP 维度的失败窗口（默认 5 分钟）足够短，合法用户偶尔失败不会长期受影响。
        """
        redis = self._redis()
        user_key = self._user_key(ip, username)
        if redis is not None:
            try:
                pipe = redis.pipeline()
                pipe.delete(user_key)
                pipe.delete(self._lock_key(user_key))
                await pipe.execute()
                return
            except Exception as e:
                logger.debug(f"Redis 重置失败计数异常，降级内存: {e}")

        self._fallback.reset(user_key)
        self._fallback.reset(self._lock_key(user_key))


_limiter: Optional[AuthRateLimiter] = None


def get_auth_rate_limiter() -> AuthRateLimiter:
    """获取全局登录限流器（延迟初始化）"""
    global _limiter
    if _limiter is None:
        _limiter = AuthRateLimiter()
    return _limiter


def reset_auth_rate_limiter_for_tests() -> None:
    """测试专用：重置全局单例。"""
    global _limiter
    _limiter = None
