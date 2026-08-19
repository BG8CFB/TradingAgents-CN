"""
基于MongoDB的股票筛选服务（薄壳 — 查询逻辑已迁入数据层）

四阶段跨集合查询的实际实现在 app/data/query/screening_query.py 的
ScreeningQueryService；本模块保留原对外方法签名，调用方零改动。

对外接口请使用 app.services.enhanced_screening_service.EnhancedScreeningService
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.data.query.screening_query import ScreeningQueryService

logger = logging.getLogger(__name__)


class DatabaseScreeningService:
    """基于数据库的股票筛选服务（薄壳委托 ScreeningQueryService）"""

    def __init__(self):
        self._query = ScreeningQueryService()

    async def can_handle_conditions(self, conditions: List[Dict[str, Any]]) -> bool:
        return await self._query.can_handle_conditions(conditions)

    async def screen_stocks(
        self,
        conditions: List[Dict[str, Any]],
        limit: int = 50,
        offset: int = 0,
        order_by: Optional[List[Dict[str, str]]] = None,
        source: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """四阶段跨集合筛选（委托 ScreeningQueryService）。"""
        return await self._query.screen_stocks(
            conditions=conditions,
            limit=limit,
            offset=offset,
            order_by=order_by,
            source=source,
        )

    async def get_field_statistics(self, field: str) -> Dict[str, Any]:
        """获取字段统计信息（委托 ScreeningQueryService）。"""
        return await self._query.get_field_statistics(field)

    async def get_available_values(self, field: str, limit: int = 100) -> List[str]:
        """获取字段的可选值列表（委托 ScreeningQueryService）。"""
        return await self._query.get_available_values(field, limit)


# 全局服务实例
_database_screening_service: Optional[DatabaseScreeningService] = None


def get_database_screening_service() -> DatabaseScreeningService:
    global _database_screening_service
    if _database_screening_service is None:
        _database_screening_service = DatabaseScreeningService()
    return _database_screening_service
