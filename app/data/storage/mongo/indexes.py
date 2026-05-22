"""MongoDB 索引定义与初始化。"""

import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


# 业务集合唯一索引定义: (domain, index_spec)
# index_spec = [(field1, 1), (field2, -1), ...]  其中 1=ASC, -1=DESC
_BUSINESS_UNIQUE_INDEXES: Dict[str, List[Tuple[str, int]]] = {
    "basic_info": [("symbol", 1)],
    "trade_calendar": [("exchange", 1), ("cal_date", 1)],
    "daily_quotes": [("symbol", 1), ("trade_date", 1), ("period", 1)],
    "daily_indicators": [("symbol", 1), ("trade_date", 1)],
    "adj_factors": [("symbol", 1), ("trade_date", 1)],
    "corporate_actions": [("symbol", 1), ("ex_date", 1), ("action_type", 1)],
    "financial_data": [("symbol", 1), ("report_period", 1), ("statement_type", 1)],
    "market_quotes": [("symbol", 1)],
    "news": [("content_hash", 1)],
}

# 辅助索引
_BUSINESS_AUX_INDEXES: Dict[str, List[List[Tuple[str, int]]]] = {
    "basic_info": [[("data_source", 1)], [("updated_at", -1)]],
    "trade_calendar": [[("cal_date", 1)]],
    "daily_quotes": [[("trade_date", -1)], [("symbol", 1), ("trade_date", -1)]],
    "daily_indicators": [[("trade_date", -1)]],
    "financial_data": [[("symbol", 1), ("announce_date", -1)], [("report_period", -1)]],
    "news": [[("symbol", 1), ("publish_time", -1)]],
    "market_quotes": [[("updated_at", -1)]],
}

# 元数据集合索引
_METADATA_INDEXES: Dict[str, List[List[Tuple[str, int]]]] = {
    "sync_checkpoints": [
        [("market", 1), ("domain", 1), ("source", 1)],  # unique
        [("last_sync_time", -1)],
    ],
    "sync_events": [
        [("market", 1), ("created_at", -1)],
        [("event_type", 1)],
    ],
    "source_health": [
        [("market", 1), ("source", 1), ("domain", 1)],  # unique
        [("updated_at", -1)],
    ],
    "system_configs": [
        [("config_type", 1), ("market", 1), ("domain", 1)],  # unique
        [("updated_at", -1)],
    ],
}


async def ensure_indexes(db) -> None:
    """为所有市场的业务集合和元数据集合创建索引。"""
    from app.data.storage.mongo.collections import (
        get_collection_name,
        _BUSINESS_COLLECTIONS,
        _METADATA_COLLECTIONS,
    )

    markets = ["CN", "HK", "US"]

    # 业务集合索引
    for market in markets:
        for domain in _BUSINESS_COLLECTIONS:
            coll_name = get_collection_name(domain, market)
            coll = db[coll_name]

            # 唯一索引
            if domain in _BUSINESS_UNIQUE_INDEXES:
                idx_spec = _BUSINESS_UNIQUE_INDEXES[domain]
                try:
                    await coll.create_index(
                        idx_spec, unique=True, name=f"uk_{domain}", background=True
                    )
                except Exception as e:
                    logger.warning(f"创建唯一索引 {coll_name}: {e}")

            # 辅助索引
            if domain in _BUSINESS_AUX_INDEXES:
                for i, idx_spec in enumerate(_BUSINESS_AUX_INDEXES[domain]):
                    try:
                        await coll.create_index(
                            idx_spec, name=f"aux_{domain}_{i}", background=True
                        )
                    except Exception as e:
                        logger.warning(f"创建辅助索引 {coll_name}: {e}")

    # 元数据集合索引
    for domain, indexes in _METADATA_INDEXES.items():
        coll_name = _METADATA_COLLECTIONS[domain]
        coll = db[coll_name]
        for i, idx_spec in enumerate(indexes):
            is_unique = i == 0  # 第一个是唯一索引
            try:
                await coll.create_index(
                    idx_spec,
                    unique=is_unique,
                    name=f"idx_{domain}_{i}",
                    background=True,
                )
            except Exception as e:
                logger.warning(f"创建元数据索引 {coll_name}: {e}")

    logger.info("MongoDB 索引创建完成")
