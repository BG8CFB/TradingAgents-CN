#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美股数据同步服务（支持多数据源）

功能：
1. 从 yfinance 同步美股基础信息和行情
2. 支持多数据源存储：同一股票可有多个数据源记录
3. 使用 (code, source) 联合查询进行 upsert 操作

设计说明：
- 参考A股多数据源同步服务设计（Tushare/AKShare/BaoStock）
- 主要使用 yfinance 作为数据源
- 批量更新操作提高性能
"""

import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Optional, Any
from pymongo import UpdateOne

# 导入美股数据提供器
import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.data.providers.us.yfinance import YFinanceUtils
from app.utils.time_utils import now_utc
from app.core.database import get_mongo_db
from app.core.config import settings
from app.utils.timezone import now_config_tz, format_iso

logger = logging.getLogger(__name__)


class USSyncService:
    """美股数据同步服务（支持多数据源）"""

    def __init__(self):
        self.db = get_mongo_db()
        self.settings = settings

        # 数据提供器
        self.yfinance_provider = YFinanceUtils()

        # 美股列表缓存（从 Finnhub 动态获取）
        self.us_stock_list = []
        self._stock_list_cache_time = None
        self._stock_list_cache_ttl = 3600 * 24  # 缓存24小时

        # Finnhub 客户端（延迟初始化）
        self._finnhub_client = None

    async def initialize(self):
        """初始化同步服务"""
        logger.info("✅ 美股同步服务初始化完成")

    def _get_finnhub_client(self):
        """获取 Finnhub 客户端（延迟初始化）"""
        if self._finnhub_client is None:
            try:
                import finnhub
                import os

                api_key = os.getenv('FINNHUB_API_KEY')
                if not api_key:
                    logger.warning("⚠️ 未配置 FINNHUB_API_KEY，无法使用 Finnhub 数据源")
                    return None

                self._finnhub_client = finnhub.Client(api_key=api_key)
                logger.info("✅ Finnhub 客户端初始化成功")
            except Exception as e:
                logger.error(f"❌ Finnhub 客户端初始化失败: {e}")
                return None

        return self._finnhub_client

    def _get_us_stock_list_from_finnhub(self) -> List[str]:
        """
        从 Finnhub 获取所有美股列表

        Returns:
            List[str]: 美股代码列表
        """
        try:
            from datetime import datetime, timedelta

            # 检查缓存是否有效
            if (self.us_stock_list and self._stock_list_cache_time and
                now_config_tz() - self._stock_list_cache_time < timedelta(seconds=self._stock_list_cache_ttl)):
                logger.debug(f"📦 使用缓存的美股列表: {len(self.us_stock_list)} 只")
                return self.us_stock_list

            logger.info("🔄 从 Finnhub 获取美股列表...")

            # 获取 Finnhub 客户端
            client = self._get_finnhub_client()
            if not client:
                logger.warning("⚠️ Finnhub 客户端不可用，使用备用列表")
                return self._get_fallback_stock_list()

            # 获取美股列表（US 交易所）
            symbols = client.stock_symbols('US')

            if not symbols:
                logger.warning("⚠️ Finnhub 返回空数据，使用备用列表")
                return self._get_fallback_stock_list()

            # 提取股票代码列表（只保留普通股票，过滤掉 ETF、基金等）
            stock_codes = []
            for symbol_info in symbols:
                symbol = symbol_info.get('symbol', '')
                symbol_type = symbol_info.get('type', '')

                # 只保留普通股票（Common Stock）
                if symbol and symbol_type == 'Common Stock':
                    stock_codes.append(symbol)

            logger.info(f"✅ 成功获取 {len(stock_codes)} 只美股（普通股）")

            # 更新缓存
            self.us_stock_list = stock_codes
            self._stock_list_cache_time = now_config_tz()

            return stock_codes

        except Exception as e:
            logger.error(f"❌ 从 Finnhub 获取美股列表失败: {e}")
            logger.info("📋 使用备用美股列表")
            return self._get_fallback_stock_list()

    def _get_fallback_stock_list(self) -> List[str]:
        """
        获取备用美股列表（主要美股标的）

        Returns:
            List[str]: 美股代码列表
        """
        return [
            # 科技巨头
            "AAPL",   # 苹果
            "MSFT",   # 微软
            "GOOGL",  # 谷歌
            "AMZN",   # 亚马逊
            "META",   # Meta
            "TSLA",   # 特斯拉
            "NVDA",   # 英伟达
            "AMD",    # AMD
            "INTC",   # 英特尔
            "NFLX",   # 奈飞
            # 金融
            "JPM",    # 摩根大通
            "BAC",    # 美国银行
            "WFC",    # 富国银行
            "GS",     # 高盛
            "MS",     # 摩根士丹利
            # 消费
            "KO",     # 可口可乐
            "PEP",    # 百事可乐
            "WMT",    # 沃尔玛
            "HD",     # 家得宝
            "MCD",    # 麦当劳
            # 医疗
            "JNJ",    # 强生
            "PFE",    # 辉瑞
            "UNH",    # 联合健康
            "ABBV",   # 艾伯维
            # 能源
            "XOM",    # 埃克森美孚
            "CVX",    # 雪佛龙
        ]

    async def sync_basic_info_from_source(
        self,
        source: str = "yfinance",
        force_update: bool = False
    ) -> Dict[str, int]:
        """
        从指定数据源同步美股基础信息

        Args:
            source: 数据源名称 (默认 yfinance)
            force_update: 是否强制更新（强制刷新股票列表）

        Returns:
            Dict: 同步统计信息 {updated: int, inserted: int, failed: int}
        """
        if source != "yfinance":
            logger.error(f"❌ 不支持的数据源: {source}")
            return {"updated": 0, "inserted": 0, "failed": 0}

        # 如果强制更新，清除缓存
        if force_update:
            self._stock_list_cache_time = None
            logger.info("🔄 强制刷新美股列表")

        # 获取美股列表（从 Finnhub 或缓存）
        stock_list = self._get_us_stock_list_from_finnhub()

        if not stock_list:
            logger.error("❌ 无法获取美股列表")
            return {"updated": 0, "inserted": 0, "failed": 0}

        logger.info(f"🇺🇸 开始同步美股基础信息 (数据源: {source})")
        logger.info(f"📊 待同步股票数量: {len(stock_list)}")

        operations = []
        failed_count = 0

        for stock_code in stock_list:
            try:
                # 从 yfinance 获取数据
                stock_info = self.yfinance_provider.get_stock_info(stock_code)
                
                if not stock_info or not stock_info.get('shortName'):
                    logger.warning(f"⚠️ 跳过无效数据: {stock_code}")
                    failed_count += 1
                    continue
                
                # 标准化数据格式
                normalized_info = self._normalize_stock_info(stock_info, source)
                normalized_info["code"] = stock_code.upper()
                normalized_info["source"] = source
                normalized_info["updated_at"] = now_config_tz()
                
                # 批量更新操作
                operations.append(
                    UpdateOne(
                        {"code": normalized_info["code"], "source": source},  # 🔥 联合查询条件
                        {"$set": normalized_info},
                        upsert=True
                    )
                )
                
                logger.debug(f"✅ 准备同步: {stock_code} ({stock_info.get('shortName')}) from {source}")
                
            except Exception as e:
                logger.error(f"❌ 同步失败: {stock_code} from {source}: {e}")
                failed_count += 1
        
        # 执行批量操作
        result = {"updated": 0, "inserted": 0, "failed": failed_count}
        
        if operations:
            try:
                bulk_result = await self.db.stock_basic_info_us.bulk_write(operations)
                result["updated"] = bulk_result.modified_count
                result["inserted"] = bulk_result.upserted_count
                
                logger.info(
                    f"✅ 美股基础信息同步完成 ({source}): "
                    f"更新 {result['updated']} 条, "
                    f"插入 {result['inserted']} 条, "
                    f"失败 {result['failed']} 条"
                )
            except Exception as e:
                logger.error(f"❌ 批量写入失败: {e}")
                result["failed"] += len(operations)
        
        return result
    
    def _normalize_stock_info(self, stock_info: Dict, source: str) -> Dict:
        """
        标准化股票信息格式
        
        Args:
            stock_info: 原始股票信息
            source: 数据源
        
        Returns:
            Dict: 标准化后的股票信息
        """
        # 提取通用字段
        normalized = {
            "name": stock_info.get("shortName", ""),
            "name_en": stock_info.get("longName", stock_info.get("shortName", "")),
            "currency": stock_info.get("currency", "USD"),
            "exchange": stock_info.get("exchange", "NASDAQ"),
            "market": stock_info.get("exchange", "NASDAQ"),
            "area": stock_info.get("country", "US"),
        }
        
        # 可选字段
        if "marketCap" in stock_info and stock_info["marketCap"]:
            # 转换为亿美元
            normalized["total_mv"] = stock_info["marketCap"] / 100000000
        
        if "sector" in stock_info:
            normalized["sector"] = stock_info["sector"]
        
        if "industry" in stock_info:
            normalized["industry"] = stock_info["industry"]
        
        return normalized
    
    async def sync_quotes_from_source(
        self,
        source: str = "yfinance"
    ) -> Dict[str, int]:
        """
        从指定数据源同步美股实时行情
        
        Args:
            source: 数据源名称 (默认 yfinance)
        
        Returns:
            Dict: 同步统计信息
        """
        if source != "yfinance":
            logger.error(f"❌ 不支持的数据源: {source}")
            return {"updated": 0, "inserted": 0, "failed": 0}
        
        logger.info(f"🇺🇸 开始同步美股实时行情 (数据源: {source})")
        
        operations = []
        failed_count = 0
        
        for stock_code in self.us_stock_list:
            try:
                # 获取最近1天的数据作为实时行情
                import yfinance as yf
                ticker = yf.Ticker(stock_code)
                data = ticker.history(period="1d")
                
                if data.empty:
                    logger.warning(f"⚠️ 跳过无效行情: {stock_code}")
                    failed_count += 1
                    continue
                
                latest = data.iloc[-1]
                
                # 标准化行情数据
                normalized_quote = {
                    "code": stock_code.upper(),
                    "close": float(latest['Close']),
                    "open": float(latest['Open']),
                    "high": float(latest['High']),
                    "low": float(latest['Low']),
                    "volume": int(latest['Volume']),
                    "currency": "USD",
                    "updated_at": now_utc()
                }
                
                # 计算涨跌幅
                if normalized_quote["open"] > 0:
                    pct_chg = ((normalized_quote["close"] - normalized_quote["open"]) / normalized_quote["open"]) * 100
                    normalized_quote["pct_chg"] = round(pct_chg, 2)
                
                operations.append(
                    UpdateOne(
                        {"code": normalized_quote["code"]},
                        {"$set": normalized_quote},
                        upsert=True
                    )
                )
                
                logger.debug(f"✅ 准备同步行情: {stock_code} (价格: {normalized_quote['close']} USD)")
                
            except Exception as e:
                logger.error(f"❌ 同步行情失败: {stock_code}: {e}")
                failed_count += 1
        
        # 执行批量操作
        result = {"updated": 0, "inserted": 0, "failed": failed_count}
        
        if operations:
            try:
                bulk_result = await self.db.market_quotes_us.bulk_write(operations)
                result["updated"] = bulk_result.modified_count
                result["inserted"] = bulk_result.upserted_count
                
                logger.info(
                    f"✅ 美股行情同步完成: "
                    f"更新 {result['updated']} 条, "
                    f"插入 {result['inserted']} 条, "
                    f"失败 {result['failed']} 条"
                )
            except Exception as e:
                logger.error(f"❌ 批量写入失败: {e}")
                result["failed"] += len(operations)
        
        return result


# ==================== 全局服务实例 ====================

_us_sync_service = None

async def get_us_sync_service() -> USSyncService:
    """获取美股同步服务实例"""
    global _us_sync_service
    if _us_sync_service is None:
        _us_sync_service = USSyncService()
        await _us_sync_service.initialize()
    return _us_sync_service


# ==================== APScheduler 兼容的任务函数 ====================

async def run_us_yfinance_basic_info_sync(force_update: bool = False):
    """APScheduler任务：美股基础信息同步（yfinance）"""
    try:
        service = await get_us_sync_service()
        result = await service.sync_basic_info_from_source("yfinance", force_update)
        logger.info(f"✅ 美股基础信息同步完成 (yfinance): {result}")
        return result
    except Exception as e:
        logger.error(f"❌ 美股基础信息同步失败 (yfinance): {e}")
        raise


async def run_us_yfinance_quotes_sync():
    """APScheduler任务：美股实时行情同步（yfinance）"""
    try:
        service = await get_us_sync_service()
        result = await service.sync_quotes_from_source("yfinance")
        logger.info(f"✅ 美股实时行情同步完成: {result}")
        return result
    except Exception as e:
        logger.error(f"❌ 美股实时行情同步失败: {e}")
        raise


async def run_us_status_check():
    """APScheduler任务：美股数据源状态检查"""
    try:
        service = await get_us_sync_service()
        # 刷新股票列表（如果缓存过期）
        stock_list = service._get_us_stock_list_from_finnhub()

        # 简单的状态检查：返回股票列表数量
        result = {
            "status": "ok",
            "stock_count": len(stock_list),
            "data_source": "yfinance + finnhub",
            "timestamp": format_iso(now_config_tz())
        }
        logger.info(f"✅ 美股状态检查完成: {result}")
        return result
    except Exception as e:
        logger.error(f"❌ 美股状态检查失败: {e}")
        return {"status": "error", "error": str(e)}

