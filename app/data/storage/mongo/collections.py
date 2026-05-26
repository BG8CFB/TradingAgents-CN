"""集合命名规则 — 按 domain + market 计算集合名。

业务集合: A股无后缀(如 stock_basic_info)，港股/美股加市场后缀(如 stock_basic_info_hk)
元数据集合: 无市场后缀 (如 sync_checkpoints)
"""

from typing import Dict

# 业务集合: domain → A 股基础名
_BUSINESS_COLLECTIONS: Dict[str, str] = {
    "basic_info": "stock_basic_info",
    "trade_calendar": "trade_calendar",
    "daily_quotes": "stock_daily_quotes",
    "daily_indicators": "stock_daily_indicators",
    "adj_factors": "stock_adj_factors",
    "corporate_actions": "stock_corporate_actions",
    "financial_data": "stock_financial_data",
    "market_quotes": "market_quotes",
    "news": "stock_news",
    "connect_status": "stock_connect_status",
    "southbound_holding": "stock_southbound_holding",
    "pre_post_market": "stock_pre_post_market",
    "intraday_quotes": "stock_intraday_quotes",
    "money_flow": "stock_money_flow",
    "margin_trading": "stock_margin_trading",
    "dragon_tiger": "stock_dragon_tiger",
    "block_trade": "stock_block_trade",
    "tushare_universe": "stock_tushare_universe",
}

# 元数据集合: 无市场后缀
_METADATA_COLLECTIONS: Dict[str, str] = {
    "sync_checkpoints": "sync_checkpoints",
    "sync_events": "sync_events",
    "source_health": "source_health",
    "system_configs": "system_configs",
}

# 市场后缀
_MARKET_SUFFIX = {
    "CN": "_cn",
    "HK": "_hk",
    "US": "_us",
}


def get_collection_name(domain: str, market: str) -> str:
    """根据 domain 和 market 返回 MongoDB 集合名。

    Args:
        domain: 数据域 (basic_info / daily_quotes / sync_checkpoints / ...)
        market: 市场 (CN / HK / US)

    Returns:
        集合名，如 "stock_basic_info_cn" / "sync_checkpoints"
    """
    # 元数据集合无后缀
    if domain in _METADATA_COLLECTIONS:
        return _METADATA_COLLECTIONS[domain]

    # 业务集合: CN 不加后缀，HK/US 加市场后缀
    if domain in _BUSINESS_COLLECTIONS:
        base = _BUSINESS_COLLECTIONS[domain]
        if market == "CN":
            return base
        suffix = _MARKET_SUFFIX.get(market, "")
        return f"{base}{suffix}"

    raise KeyError(f"未知的 domain: {domain}")


def get_all_collections(market: str) -> Dict[str, str]:
    """返回指定市场的所有集合名映射 {domain: collection_name}。"""
    result = {}
    suffix = "" if market == "CN" else _MARKET_SUFFIX.get(market, "")
    for domain, base in _BUSINESS_COLLECTIONS.items():
        result[domain] = f"{base}{suffix}"
    for domain, name in _METADATA_COLLECTIONS.items():
        result[domain] = name
    return result


def is_metadata_collection(domain: str) -> bool:
    """判断是否为元数据集合。"""
    return domain in _METADATA_COLLECTIONS
