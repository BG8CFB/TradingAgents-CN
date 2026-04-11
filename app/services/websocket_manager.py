"""
WebSocket 连接管理器
用于实时推送分析进度更新
"""

import asyncio
import json
import logging
from typing import Dict, Set, Any
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

class WebSocketManager:
    """WebSocket 连接管理器"""
    
    def __init__(self):
        # 存储活跃连接：{task_id: {websocket1, websocket2, ...}}
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()
    
    async def connect(self, websocket: WebSocket, task_id: str):
        """建立 WebSocket 连接"""
        await websocket.accept()
        
        async with self._lock:
            if task_id not in self.active_connections:
                self.active_connections[task_id] = set()
            self.active_connections[task_id].add(websocket)
        
        logger.info(f"🔌 WebSocket 连接建立: {task_id}")
    
    async def disconnect(self, websocket: WebSocket, task_id: str):
        """断开 WebSocket 连接"""
        async with self._lock:
            if task_id in self.active_connections:
                self.active_connections[task_id].discard(websocket)
                if not self.active_connections[task_id]:
                    del self.active_connections[task_id]
        
        logger.info(f"🔌 WebSocket 连接断开: {task_id}")
    
    async def send_progress_update(self, task_id: str, message: Dict[str, Any]):
        """发送进度更新到指定任务的所有连接"""
        if task_id not in self.active_connections:
            return
        
        # 复制连接集合以避免在迭代时修改
        connections = self.active_connections[task_id].copy()
        
        for connection in connections:
            try:
                await connection.send_text(json.dumps(message))
            except Exception as e:
                logger.warning(f"⚠️ 发送 WebSocket 消息失败: {e}")
                # 移除失效的连接
                async with self._lock:
                    if task_id in self.active_connections:
                        self.active_connections[task_id].discard(connection)
    
    async def broadcast_to_user(self, user_id: str, message: Dict[str, Any]):
        """向指定用户相关的所有连接广播消息

        注意：当前连接按 task_id 管理，此方法会遍历所有任务连接发送消息。
        如需精确按用户过滤，需扩展连接管理结构添加 user_id 映射。
        """
        if not self.active_connections:
            return

        message_json = json.dumps(message, ensure_ascii=False)

        async with self._lock:
            all_connections = []
            for connections in self.active_connections.values():
                all_connections.extend(connections)

        for connection in all_connections:
            try:
                await connection.send_text(message_json)
            except Exception as e:
                logger.warning(f"⚠️ broadcast_to_user 发送失败: {e}")
    
    async def get_connection_count(self, task_id: str) -> int:
        """获取指定任务的连接数"""
        async with self._lock:
            return len(self.active_connections.get(task_id, set()))
    
    async def get_total_connections(self) -> int:
        """获取总连接数"""
        async with self._lock:
            total = 0
            for connections in self.active_connections.values():
                total += len(connections)
            return total

# 全局实例
_websocket_manager = None

def get_websocket_manager() -> WebSocketManager:
    """获取 WebSocket 管理器实例"""
    global _websocket_manager
    if _websocket_manager is None:
        _websocket_manager = WebSocketManager()
    return _websocket_manager
