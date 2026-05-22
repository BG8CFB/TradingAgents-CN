"""告警分发服务 — 日志 / SSE / 邮件（可选）。"""

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class AlertLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertService:
    """告警分发。"""

    def __init__(self):
        self._sse_enabled = False

    async def send_alert(
        self,
        title: str,
        message: str,
        level: AlertLevel = AlertLevel.INFO,
        market: Optional[str] = None,
        domain: Optional[str] = None,
        source: Optional[str] = None,
    ):
        """发送告警。"""
        alert_data = {
            "title": title,
            "message": message,
            "level": level.value,
            "market": market,
            "domain": domain,
            "source": source,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # 日志输出
        log_method = {
            AlertLevel.INFO: logger.info,
            AlertLevel.WARNING: logger.warning,
            AlertLevel.ERROR: logger.error,
            AlertLevel.CRITICAL: logger.critical,
        }
        log_method[level](f"[告警] {title}: {message}")

        # SSE 推送
        if self._sse_enabled:
            await self._push_sse(alert_data)

        # 记录到 sync_events
        await self._record_event(alert_data)

    async def _push_sse(self, alert_data: dict):
        """通过 SSE 推送告警到前端。"""
        try:
            from app.data.storage.redis.pubsub import RefreshQueue
            RefreshQueue()
            # 将告警数据序列化为 JSON 字符串推送到专用告警通道
            import json
            message = json.dumps({
                "type": "alert",
                **alert_data,
            })
            queue_key = "queue:alerts"
            try:
                redis = None
                try:
                    redis = __import__("app.data.storage.redis.client", fromlist=["get_redis"]).get_redis()
                except Exception:
                    pass
                if redis:
                    await redis.rpush(queue_key, message)
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"SSE 推送失败: {e}")

    async def _record_event(self, alert_data: dict):
        """记录到 sync_events。"""
        try:
            from app.data.storage.mongo.repositories.metadata_repo import MetadataRepo
            meta = MetadataRepo()
            await meta.insert_event({
                "event_type": "ALERT",
                "market": alert_data.get("market"),
                "domain": alert_data.get("domain"),
                "source": alert_data.get("source"),
                "level": alert_data.get("level"),
                "title": alert_data.get("title"),
                "message": alert_data.get("message"),
            })
        except Exception as e:
            logger.debug(f"告警事件记录失败: {e}")

    def enable_sse(self, enabled: bool = True):
        self._sse_enabled = enabled
