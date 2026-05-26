"""市场状态缓存。"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 内存降级
_memory_state: dict = {}


class MarketStateCache:
    """市场开市状态与当前会话缓存。"""

    async def is_market_open(self, market: str) -> bool:
        state = await self._get_state(market)
        return state.get("is_open", False) if state else False

    async def get_session(self, market: str) -> str:
        state = await self._get_state(market)
        return state.get("session", "closed") if state else "closed"

    async def set_market_state(self, market: str, is_open: bool, session: str) -> None:
        key = f"market_state:{market}"
        state = {"is_open": is_open, "session": session}

        try:
            redis = None
            try:
                # 使用 __import__ 避免模块级别循环导入，运行时按需获取 Redis 客户端
                redis = __import__("app.data.storage.redis.client", fromlist=["get_redis"]).get_redis()
            except Exception:
                pass

            if redis:
                await redis.hset(key, mapping=state)
                await redis.expire(key, 3600)
                return
        except Exception as e:
            logger.debug(f"Redis 市场状态写入失败: {e}")

        _memory_state[key] = state

    async def _get_state(self, market: str) -> Optional[dict]:
        key = f"market_state:{market}"

        try:
            redis = None
            try:
                # 使用 __import__ 避免模块级别循环导入，运行时按需获取 Redis 客户端
                redis = __import__("app.data.storage.redis.client", fromlist=["get_redis"]).get_redis()
            except Exception:
                pass

            if redis:
                data = await redis.hgetall(key)
                if data:
                    return {"is_open": data.get("is_open") == "True", "session": data.get("session", "closed")}
        except Exception:
            pass

        return _memory_state.get(key)
