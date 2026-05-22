"""MongoDB 客户端封装 — 桥接 app/core/database.py。"""

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

_motor_db: Optional[AsyncIOMotorDatabase] = None


def get_motor_db() -> AsyncIOMotorDatabase:
    """获取异步 MongoDB 数据库实例。"""
    global _motor_db
    if _motor_db is None:
        from app.core.database import get_mongo_db
        _motor_db = get_mongo_db()
    return _motor_db


def reset_client():
    """重置客户端引用（测试用）。"""
    global _motor_db
    _motor_db = None
