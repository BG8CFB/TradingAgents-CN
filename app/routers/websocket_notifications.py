"""
WebSocket 通知系统
替代 SSE + Redis PubSub，解决连接泄漏问题
"""
import asyncio
import json
import logging
from typing import Dict, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from app.services.auth_service import AuthService
from app.services.user_service import user_service
from app.utils.time_utils import now_utc, format_iso

router = APIRouter(prefix="/api/ws", tags=["WebSocket"])
logger = logging.getLogger("webapi.websocket")


async def _resolve_authenticated_user_id(token: str) -> str | None:
    """验证 token 并解析通知系统使用的真实用户 ID。"""
    token_data = AuthService.verify_token(token)
    if not token_data or not getattr(token_data, "sub", None):
        return None

    user = await user_service.get_user_by_username(token_data.sub)
    if not user or not user.is_active:
        return None

    return str(user.id)

# 🔥 全局 WebSocket 连接管理器
class ConnectionManager:
    """WebSocket 连接管理器"""
    
    def __init__(self):
        # user_id -> Set[WebSocket]
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()
    
    async def connect(self, websocket: WebSocket, user_id: str):
        """连接 WebSocket"""
        await websocket.accept()
        
        async with self._lock:
            if user_id not in self.active_connections:
                self.active_connections[user_id] = set()
            self.active_connections[user_id].add(websocket)
            
            total_connections = sum(len(conns) for conns in self.active_connections.values())
            logger.info(f"✅ [WS] 新连接: user={user_id}, "
                       f"该用户连接数={len(self.active_connections[user_id])}, "
                       f"总连接数={total_connections}")
    
    async def disconnect(self, websocket: WebSocket, user_id: str):
        """断开 WebSocket"""
        async with self._lock:
            if user_id in self.active_connections:
                self.active_connections[user_id].discard(websocket)
                if not self.active_connections[user_id]:
                    del self.active_connections[user_id]
            
            total_connections = sum(len(conns) for conns in self.active_connections.values())
            logger.info(f"🔌 [WS] 断开连接: user={user_id}, 总连接数={total_connections}")
    
    async def send_personal_message(self, message: dict, user_id: str):
        """发送消息给指定用户的所有连接"""
        async with self._lock:
            if user_id not in self.active_connections:
                logger.debug(f"⚠️ [WS] 用户 {user_id} 没有活跃连接")
                return
            
            connections = list(self.active_connections[user_id])
        
        # 在锁外发送消息，避免阻塞
        message_json = json.dumps(message, ensure_ascii=False)
        dead_connections = []
        
        for connection in connections:
            try:
                await connection.send_text(message_json)
                logger.debug(f"📤 [WS] 发送消息给 user={user_id}")
            except Exception as e:
                logger.warning(f"❌ [WS] 发送消息失败: {e}")
                dead_connections.append(connection)
        
        # 清理死连接
        if dead_connections:
            async with self._lock:
                if user_id in self.active_connections:
                    for conn in dead_connections:
                        self.active_connections[user_id].discard(conn)
                    if not self.active_connections[user_id]:
                        del self.active_connections[user_id]
    
    async def broadcast(self, message: dict):
        """广播消息给所有连接"""
        async with self._lock:
            all_connections = []
            for connections in self.active_connections.values():
                all_connections.extend(connections)
        
        message_json = json.dumps(message, ensure_ascii=False)
        
        for connection in all_connections:
            try:
                await connection.send_text(message_json)
            except Exception as e:
                logger.warning(f"❌ [WS] 广播消息失败: {e}")
    
    def get_stats(self) -> dict:
        """获取连接统计"""
        return {
            "total_users": len(self.active_connections),
            "total_connections": sum(len(conns) for conns in self.active_connections.values()),
            "users": {user_id: len(conns) for user_id, conns in self.active_connections.items()}
        }


# 全局连接管理器实例
manager = ConnectionManager()


@router.websocket("/notifications")
async def websocket_notifications_endpoint(
    websocket: WebSocket,
    token: str = Query(...)
):
    """
    WebSocket 通知端点
    
    客户端连接: ws://localhost:8000/api/ws/notifications?token=<jwt_token>
    
    消息格式:
    {
        "type": "notification",  // 消息类型: notification, heartbeat, connected
        "data": {
            "id": "...",
            "title": "...",
            "content": "...",
            "type": "analysis",
            "link": "/stocks/000001",
            "source": "analysis",
            "created_at": "2025-10-23T12:00:00",
            "status": "unread"
        }
    }
    """
    # 验证 token
    user_id = await _resolve_authenticated_user_id(token)
    if not user_id:
        # 必须先 accept 再 close，否则 Starlette 会回退为 HTTP 403，
        # 自定义关闭码无法到达浏览器（与 analysis.py WebSocket 处理一致）
        try:
            await websocket.accept()
            await websocket.close(code=4401, reason="authentication failed")
        except Exception:
            pass
        return

    # 连接 WebSocket
    await manager.connect(websocket, user_id)
    
    # 发送连接确认
    await websocket.send_json({
        "type": "connected",
        "data": {
            "user_id": user_id,
            "timestamp": format_iso(now_utc()),
            "message": "WebSocket 连接成功"
        }
    })

    try:
        # 心跳任务
        heartbeat_task: asyncio.Task | None = None
        async def send_heartbeat():
            while True:
                try:
                    await asyncio.sleep(30)  # 每 30 秒发送一次心跳
                    await websocket.send_json({
                        "type": "heartbeat",
                        "data": {
                            "timestamp": format_iso(now_utc())
                        }
                    })
                except Exception as e:
                    logger.debug(f"💓 [WS] 心跳发送失败: {e}")
                    break
        
        # 启动心跳任务
        heartbeat_task = asyncio.create_task(send_heartbeat())
        
        # 接收客户端消息（主要用于保持连接）
        while True:
            try:
                data = await websocket.receive_text()
                # 可以处理客户端发送的消息（如 ping/pong）
                logger.debug(f"📥 [WS] 收到客户端消息: user={user_id}, data={data}")
            except WebSocketDisconnect:
                logger.info(f"🔌 [WS] 客户端主动断开: user={user_id}")
                break
            except Exception as e:
                logger.error(f"❌ [WS] 接收消息错误: {e}")
                break
    
    finally:
        # 取消心跳任务
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
        
        # 断开连接
        await manager.disconnect(websocket, user_id)


# 🔥 辅助函数：供其他模块调用，发送通知
async def send_notification_via_websocket(user_id: str, notification: dict):
    """
    通过 WebSocket 发送通知

    Args:
        user_id: 用户 ID
        notification: 通知数据
    """
    message = {
        "type": "notification",
        "data": notification
    }
    await manager.send_personal_message(message, user_id)

