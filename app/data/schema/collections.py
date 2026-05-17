"""
集合名映射：根据市场和数据类型返回 MongoDB 集合名。

复用现有 UnifiedStockService.collection_map 的设计，
提升为全局公共函数，供所有服务层和 Worker 调用。
"""

from typing import Dict

# 市场后缀规则：A 股无后缀，港股 _hk，美股 _us
_SUFFIX_MAP = {
    "CN": "",
    "HK": "_hk",
    "US": "_us",
}

# 数据类型到 A 股集合名的映射
_BASE_COLLECTION_MAP: Dict[str, str] = {
    "basic_info": "stock_basic_info",
    "daily_quotes": "stock_daily_quotes",
    "market_quotes": "market_quotes",
    "financial": "stock_financial_data",
    "news": "stock_news",
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
        data_type: "basic_info" / "daily_quotes" / "market_quotes" / "financial" / "news"

    Returns:
        集合名，如 "stock_basic_info" / "stock_basic_info_hk" / "stock_basic_info_us"

    Raises:
        KeyError: market 或 data_type 不合法
    """
    return COLLECTION_MAP[market][data_type]


def get_all_collections_for_market(market: str) -> Dict[str, str]:
    """返回指定市场的全部集合名映射"""
    return COLLECTION_MAP[market].copy()
