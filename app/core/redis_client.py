"""
Redis客户端配置和连接管理
"""

import json
import logging
import threading
import uuid
from typing import Optional
from redis.asyncio import Redis

logger = logging.getLogger(__name__)


def get_redis():
    """获取 Redis 客户端（统一从 database.py 获取）"""
    from app.core.database import get_redis_client
    client = get_redis_client()
    if client is None:
        raise RuntimeError("Redis 未初始化，请先调用 init_database()")
    return client


class RedisKeys:
    """Redis键名常量"""
    
    # 队列相关
    USER_PENDING_QUEUE = "user:{user_id}:pending"
    USER_PROCESSING_SET = "user:{user_id}:processing"
    GLOBAL_PENDING_QUEUE = "global:pending"
    GLOBAL_PROCESSING_SET = "global:processing"
    
    # 任务相关
    TASK_PROGRESS = "task:{task_id}:progress"
    TASK_RESULT = "task:{task_id}:result"
    TASK_LOCK = "task:{task_id}:lock"
    
    # 批次相关
    BATCH_PROGRESS = "batch:{batch_id}:progress"
    BATCH_TASKS = "batch:{batch_id}:tasks"
    BATCH_LOCK = "batch:{batch_id}:lock"
    
    # 用户相关
    USER_SESSION = "session:{session_id}"
    USER_RATE_LIMIT = "rate_limit:{user_id}:{endpoint}"
    USER_DAILY_QUOTA = "quota:{user_id}:{date}"
    
    # 系统相关
    QUEUE_STATS = "queue:stats"
    SYSTEM_CONFIG = "system:config"
    WORKER_HEARTBEAT = "worker:{worker_id}:heartbeat"
    
    # 缓存相关
    SCREENING_CACHE = "screening:{cache_key}"
    ANALYSIS_CACHE = "analysis:{cache_key}"


class RedisService:
    """Redis服务封装类"""

    def __init__(self):
        self._redis: Optional[Redis] = None

    @property
    def redis(self) -> Redis:
        """始终返回当前全局 Redis 客户端，避免重连后持有过期实例"""
        current_client = get_redis()
        if self._redis is not current_client:
            self._redis = current_client
        return self._redis
    
    async def set_with_ttl(self, key: str, value: str, ttl: int = 3600):
        """设置带TTL的键值"""
        await self.redis.setex(key, ttl, value)
    
    async def get_json(self, key: str):
        """获取JSON格式的值"""
        value = await self.redis.get(key)
        if value:
            return json.loads(value)
        return None

    async def set_json(self, key: str, value: dict, ttl: int = None):
        """设置JSON格式的值"""
        json_str = json.dumps(value, ensure_ascii=False)
        if ttl:
            await self.redis.setex(key, ttl, json_str)
        else:
            await self.redis.set(key, json_str)
    
    async def increment_with_ttl(self, key: str, ttl: int = 3600) -> int:
        """递增计数器，仅在首次创建时设置 TTL（Lua 脚本保证原子性）"""
        lua_script = """
        local count = redis.call('INCR', KEYS[1])
        if count == 1 then
            redis.call('EXPIRE', KEYS[1], ARGV[1])
        end
        return count
        """
        result = await self.redis.eval(lua_script, 1, key, ttl)
        return int(result)
    
    async def add_to_queue(self, queue_key: str, item: dict):
        """添加项目到队列"""
        await self.redis.lpush(queue_key, json.dumps(item, ensure_ascii=False))

    async def pop_from_queue(self, queue_key: str, timeout: int = 1):
        """从队列弹出项目"""
        result = await self.redis.brpop(queue_key, timeout=timeout)
        if result:
            return json.loads(result[1])
        return None
    
    async def get_queue_length(self, queue_key: str):
        """获取队列长度"""
        return await self.redis.llen(queue_key)
    
    async def add_to_set(self, set_key: str, value: str):
        """添加到集合"""
        await self.redis.sadd(set_key, value)
    
    async def remove_from_set(self, set_key: str, value: str):
        """从集合移除"""
        await self.redis.srem(set_key, value)
    
    async def is_in_set(self, set_key: str, value: str):
        """检查是否在集合中"""
        return await self.redis.sismember(set_key, value)
    
    async def get_set_size(self, set_key: str):
        """获取集合大小"""
        return await self.redis.scard(set_key)
    
    async def acquire_lock(self, lock_key: str, timeout: int = 30):
        """获取分布式锁（带自动续约）"""
        lock_value = str(uuid.uuid4())
        acquired = await self.redis.set(lock_key, lock_value, nx=True, ex=timeout)
        if acquired:
            return lock_value
        return None

    async def extend_lock(self, lock_key: str, lock_value: str, additional_seconds: int = 30) -> bool:
        """续约分布式锁（仅当值匹配时续约）"""
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("expire", KEYS[1], ARGV[2])
        else
            return 0
        end
        """
        result = await self.redis.eval(lua_script, 1, lock_key, lock_value, additional_seconds)
        return bool(result)
    
    async def release_lock(self, lock_key: str, lock_value: str):
        """释放分布式锁"""
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        return await self.redis.eval(lua_script, 1, lock_key, lock_value)

    async def ping(self) -> bool:
        """健康检查：返回 Redis 是否可达。供 rate_limit 中间件自愈逻辑使用。"""
        try:
            return bool(await self.redis.ping())
        except Exception:
            return False


# 全局Redis服务实例
redis_service: Optional[RedisService] = None
_redis_service_lock = threading.Lock()


def get_redis_service() -> RedisService:
    """获取Redis服务实例（线程安全单例）"""
    global redis_service
    if redis_service is None:
        with _redis_service_lock:
            if redis_service is None:
                redis_service = RedisService()
    return redis_service
