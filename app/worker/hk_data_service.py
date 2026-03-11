#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
港股数据服务（按需获取+缓存模式）

功能：
1. 按需从数据源获取港股信息（yfinance/akshare）
2. 自动缓存到 MongoDB，避免重复请求
3. 支持多数据源：同一股票可有多个数据源记录
4. 使用 (code, source) 联合查询进行 upsert 操作

设计说明：
- 采用按需获取+缓存模式，避免批量同步触发速率限制
- 参考A股数据源管理方式（Tushare/AKShare/BaoStock）
- 缓存时长可配置（默认24小时）
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Any

# 导入港股数据提供器
import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.data.providers.hk.hk_stock import HKStockProvider
from app.data.providers.hk.improved_hk import ImprovedHKStockProvider
from app.core.database import get_mongo_db
from app.core.config import settings
from app.utils.timezone import now_config_tz

logger = logging.getLogger(__name__)


class HKDataService:
    """港股数据服务（按需获取+缓存模式）"""

    def __init__(self):
        self.db = get_mongo_db()
        self.settings = settings

        # 数据提供器映射
        self.providers = {
            "yfinance": HKStockProvider(),
            "akshare": ImprovedHKStockProvider(),
        }
        
        # 缓存配置
        self.cache_hours = getattr(settings, 'HK_DATA_CACHE_HOURS', 24)
        self.default_source = getattr(settings, 'HK_DEFAULT_DATA_SOURCE', 'yfinance')

    async def initialize(self):
        """初始化数据服务"""
        logger.info("✅ 港股数据服务初始化完成")
    
    async def get_stock_info(
        self, 
        stock_code: str, 
        source: Optional[str] = None,
        force_refresh: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        获取港股基础信息（按需获取+缓存）
        
        Args:
            stock_code: 股票代码（如 "00700"）
            source: 数据源（yfinance/akshare），None 则使用默认数据源
            force_refresh: 是否强制刷新（忽略缓存）
        
        Returns:
            股票信息字典，失败返回 None
        """
        try:
            # 使用默认数据源
            if source is None:
                source = self.default_source
            
            # 标准化股票代码
            normalized_code = stock_code.lstrip('0').zfill(5)
            
            # 检查缓存
            if not force_refresh:
                cached_info = await self._get_cached_info(normalized_code, source)
                if cached_info:
                    logger.debug(f"✅ 使用缓存数据: {normalized_code} ({source})")
                    return cached_info
            
            # 从数据源获取
            provider = self.providers.get(source)
            if not provider:
                logger.error(f"❌ 不支持的数据源: {source}")
                return None
            
            logger.info(f"🔄 从 {source} 获取港股信息: {stock_code}")
            stock_info = provider.get_stock_info(stock_code)
            
            if not stock_info or not stock_info.get('name'):
                logger.warning(f"⚠️ 获取失败或数据无效: {stock_code} ({source})")
                return None
            
            # 标准化并保存到缓存
            normalized_info = self._normalize_stock_info(stock_info, source)
            normalized_info["code"] = normalized_code
            normalized_info["source"] = source
            normalized_info["updated_at"] = now_config_tz()
            
            await self._save_to_cache(normalized_info)
            
            logger.info(f"✅ 获取成功: {normalized_code} - {stock_info.get('name')} ({source})")
            return normalized_info
            
        except Exception as e:
            logger.error(f"❌ 获取港股信息失败: {stock_code} ({source}): {e}")
            return None
    
    async def _get_cached_info(self, code: str, source: str) -> Optional[Dict[str, Any]]:
        """从缓存获取股票信息"""
        try:
            cache_expire_time = now_config_tz() - timedelta(hours=self.cache_hours)
            
            cached = await self.db.stock_basic_info_hk.find_one({
                "code": code,
                "source": source,
                "updated_at": {"$gte": cache_expire_time}
            })
            
            return cached
            
        except Exception as e:
            logger.error(f"❌ 读取缓存失败: {code} ({source}): {e}")
            return None
    
    async def _save_to_cache(self, stock_info: Dict[str, Any]) -> bool:
        """保存股票信息到缓存"""
        try:
            await self.db.stock_basic_info_hk.update_one(
                {"code": stock_info["code"], "source": stock_info["source"]},
                {"$set": stock_info},
                upsert=True
            )
            return True
            
        except Exception as e:
            logger.error(f"❌ 保存缓存失败: {stock_info.get('code')} ({stock_info.get('source')}): {e}")
            return False
    
    def _normalize_stock_info(self, stock_info: Dict, source: str) -> Dict:
        """
        标准化股票信息格式
        
        Args:
            stock_info: 原始股票信息
            source: 数据源
        
        Returns:
            标准化后的股票信息
        """
        normalized = {
            "name": stock_info.get("name", ""),
            "currency": stock_info.get("currency", "HKD"),
            "exchange": stock_info.get("exchange", "HKG"),
            "market": stock_info.get("market", "香港交易所"),
            "area": stock_info.get("area", "香港"),
        }
        
        # 可选字段
        optional_fields = [
            "industry", "sector", "list_date", "total_mv", "circ_mv",
            "pe", "pb", "ps", "pcf", "market_cap", "shares_outstanding",
            "float_shares", "employees", "website", "description"
        ]
        
        for field in optional_fields:
            if field in stock_info and stock_info[field]:
                normalized[field] = stock_info[field]
        
        return normalized


# ==================== 全局实例管理 ====================

_hk_data_service = None


async def get_hk_data_service() -> HKDataService:
    """获取港股数据服务实例（单例模式）"""
    global _hk_data_service
    if _hk_data_service is None:
        _hk_data_service = HKDataService()
        await _hk_data_service.initialize()
    return _hk_data_service

