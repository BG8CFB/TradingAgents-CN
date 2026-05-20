"""
基本面报告服务

从 providers/china/optimized.py 迁移。
提供 A 股基本面数据获取、评分、报告生成功能。

本模块是过渡层：最终 optimized.py 的逻辑会完全拆入此模块，
届时 providers/ 目录将被删除。
"""

from app.data.providers.china.optimized import (
    OptimizedChinaDataProvider,
    get_optimized_china_data_provider,
    get_china_stock_data_cached,
    get_china_fundamentals_cached,
)

__all__ = [
    "OptimizedChinaDataProvider",
    "get_optimized_china_data_provider",
    "get_china_stock_data_cached",
    "get_china_fundamentals_cached",
]
