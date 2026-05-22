"""异步刷新队列 — Redis list 实现。"""

import json
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# 内存降级队列
_memory_queues: Dict[str, list] = {}


class RefreshQueue:
    """异步刷新消息队列。"""

    async def publish_refresh(self, market: str, symbol: str, domain: str) -> None:
        """发布刷新任务到队列。"""
        message = json.dumps({
            "market": market,
            "symbol": symbol,
            "domain": domain,
        })
        queue_key = f"queue:refresh:{market}"

        try:
            redis = None
            try:
                redis = __import__("app.data.storage.redis.client", fromlist=["get_redis"]).get_redis()
            except Exception:
                pass

            if redis:
                await redis.rpush(queue_key, message)
                return
        except Exception as e:
            logger.debug(f"Redis 队列写入失败，降级内存: {e}")

        # 内存降级
        if queue_key not in _memory_queues:
            _memory_queues[queue_key] = []
        _memory_queues[queue_key].append(message)

    async def pop_refresh(self, market: str) -> Optional[Dict]:
        """从队列弹出一个刷新任务。"""
        queue_key = f"queue:refresh:{market}"

        try:
            redis = None
            try:
                redis = __import__("app.data.storage.redis.client", fromlist=["get_redis"]).get_redis()
            except Exception:
                pass

            if redis:
                msg = await redis.lpop(queue_key)
                if msg:
                    return json.loads(msg)
                return None
        except Exception as e:
            logger.debug(f"Redis 队列读取失败: {e}")

        # 内存降级
        if queue_key in _memory_queues and _memory_queues[queue_key]:
            msg = _memory_queues[queue_key].pop(0)
            return json.loads(msg)
        return None
