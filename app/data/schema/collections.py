"""
集合名映射：根据市场和数据类型返回 MongoDB 集合名。

A 股 11 个集合（5 业务 + 3 新业务 + 3 元数据）。
港股加 _hk 后缀，美股加 _us 后缀。
元数据集合（sync_checkpoints/sync_events/source_health）仅 CN 市场使用，
HK/US 后缀版本为未来扩展预留。
"""

from typing import Dict

# 市场后缀规则：A 股无后缀，港股 _hk，美股 _us
_SUFFIX_MAP = {
    "CN": "",
    "HK": "_hk",
    "US": "_us",
}

# 数据类型到 A 股集合名的映射（11 个集合）
_BASE_COLLECTION_MAP: Dict[str, str] = {
    # 业务集合（原有 5 个）
    "basic_info": "stock_basic_info",
    "daily_quotes": "stock_daily_quotes",
    "market_quotes": "market_quotes",
    "financial": "stock_financial_data",
    "news": "stock_news",
    # 新增业务集合（3 个）
    "trade_calendar": "trade_calendar",
    "daily_indicators": "stock_daily_indicators",
    "adj_factors": "stock_adj_factors",
    # 同步元数据集合（3 个）
    "sync_checkpoints": "sync_checkpoints",
    "sync_events": "sync_events",
    "source_health": "source_health",
}

# 完整映射矩阵（预计算）
COLLECTION_MAP: Dict[str, Dict[str, str]] = {}
for _market, _suffix in _SUFFIX_MAP.items():
    COLLECTION_MAP[_market] = {}
    for _dtype, _base in _BASE_COLLECTION_MAP.items():
        COLLECTION_MAP[_market][_dtype] = f"{_base}{_suffix}"


def get_collection_name(market: str, data_type: str) -> str:
    """
    根据市场和数据类型返回 MongoDB 集合名。

    Args:
        market: "CN" / "HK" / "US"
        data_type: 集合类型键名

    Returns:
        集合名，如 "stock_basic_info" / "stock_basic_info_hk"

    Raises:
        KeyError: market 或 data_type 不合法
    """
    return COLLECTION_MAP[market][data_type]


def get_all_collections_for_market(market: str) -> Dict[str, str]:
    """返回指定市场的全部集合名映射"""
    return COLLECTION_MAP[market].copy()
