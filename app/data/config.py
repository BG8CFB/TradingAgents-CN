"""
统一数据源优先级配置

从 MongoDB datasource_groupings 集合读取各市场的数据源优先级，
提供统一的 get_enabled_sources(market) 接口。
"""
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

_DEFAULT_SOURCES = {
    "CN": ["akshare", "tushare", "baostock"],
    "HK": ["akshare", "yfinance"],
    "US": ["yfinance", "finnhub"],
}

# 数据库中 market_category_id 与内部 market 标识的映射
_MARKET_CATEGORY_MAP = {
    "CN": "a_shares",
    "HK": "hk_stocks",
    "US": "us_stocks",
}

# 数据库中可能出现的中文标识到标准 market 的映射
_MARKET_LABEL_MAP = {
    "a_shares": "CN",
    "hk_stocks": "HK",
    "us_stocks": "US",
    "A股": "CN",
    "港股": "HK",
    "美股": "US",
}


def get_enabled_sources(market: str) -> List[str]:
    """
    获取指定市场的已启用数据源优先级列表

    Args:
        market: 市场标识 "CN" / "HK" / "US"

    Returns:
        按优先级排序的数据源名称列表（优先级高的在前）
    """
    market = market.upper()
    category_id = _MARKET_CATEGORY_MAP.get(market)
    if not category_id:
        logger.warning(f"⚠️ 未知市场: {market}，使用默认顺序")
        return _DEFAULT_SOURCES.get(market, [])

    # 1. 尝试从 datasource_groupings 集合读取
    sources = _read_from_datasource_groupings(category_id)
    if sources:
        return sources

    # 2. 尝试从 system_configs 集合读取
    sources = _read_from_system_configs(market, category_id)
    if sources:
        return sources

    # 3. 回退到默认
    logger.info(f"📊 [{market}] 使用默认数据源顺序: {_DEFAULT_SOURCES.get(market, [])}")
    return _DEFAULT_SOURCES.get(market, [])


def get_source_priority(market: str) -> Dict[str, int]:
    """
    获取数据源优先级映射（名称 → 优先级数字）

    Args:
        market: 市场标识

    Returns:
        Dict: 数据源名称到优先级数字的映射
    """
    market = market.upper()
    category_id = _MARKET_CATEGORY_MAP.get(market)
    if not category_id:
        return {}

    try:
        from app.core.database import get_mongo_db_sync
        db = get_mongo_db_sync()

        # 优先尝试 datasource_groupings
        groupings = list(db.datasource_groupings.find(
            {"market_category_id": category_id, "enabled": True}
        ).sort("priority", -1))

        if groupings:
            return {
                g["data_source_name"].lower(): g.get("priority", 0)
                for g in groupings
                if g.get("data_source_name")
            }

        # 回退到 system_configs
        config_data = db.system_configs.find_one(
            {"is_active": True}, sort=[("version", -1)]
        )
        if config_data and config_data.get("data_source_configs"):
            result = {}
            for ds in config_data["data_source_configs"]:
                if not ds.get("enabled", True):
                    continue
                market_cats = ds.get("market_categories", [])
                if market_cats and category_id not in market_cats:
                    cat_cn = [k for k, v in _MARKET_LABEL_MAP.items() if v == market]
                    if not any(c in market_cats for c in cat_cn):
                        continue
                result[ds.get("type", "").lower()] = ds.get("priority", 0)
            return result

    except Exception as e:
        logger.debug(f"读取数据源优先级失败: {e}")

    return {}


def _read_from_datasource_groupings(category_id: str) -> Optional[List[str]]:
    """从 datasource_groupings 集合读取"""
    try:
        from app.core.database import get_mongo_db_sync
        db = get_mongo_db_sync()

        groupings = list(db.datasource_groupings.find(
            {"market_category_id": category_id, "enabled": True}
        ).sort("priority", -1))

        if groupings:
            sources = [
                g["data_source_name"].lower()
                for g in groupings
                if g.get("data_source_name")
            ]
            if sources:
                logger.info(f"✅ [数据源配置] {category_id} 从 datasource_groupings 读取: {sources}")
                return sources
    except Exception as e:
        logger.debug(f"datasource_groupings 读取失败: {e}")
    return None


def _read_from_system_configs(market: str, category_id: str) -> Optional[List[str]]:
    """从 system_configs.data_source_configs 读取"""
    try:
        from app.core.database import get_mongo_db_sync
        db = get_mongo_db_sync()

        config_data = db.system_configs.find_one(
            {"is_active": True}, sort=[("version", -1)]
        )
        if not config_data or not config_data.get("data_source_configs"):
            return None

        cat_cn = [k for k, v in _MARKET_LABEL_MAP.items() if v == market]
        enabled_sources = []

        for ds in config_data["data_source_configs"]:
            if not ds.get("enabled", True):
                continue

            market_cats = ds.get("market_categories", [])
            if market_cats:
                if category_id not in market_cats and not any(c in market_cats for c in cat_cn):
                    continue

            ds_type = ds.get("type", "").lower()
            if ds_type:
                enabled_sources.append({
                    "type": ds_type,
                    "priority": ds.get("priority", 0),
                })

        enabled_sources.sort(key=lambda x: x["priority"], reverse=True)
        sources = [s["type"] for s in enabled_sources]

        if sources:
            logger.info(f"✅ [数据源配置] {market} 从 system_configs 读取: {sources}")
            return sources
    except Exception as e:
        logger.debug(f"system_configs 读取失败: {e}")
    return None
