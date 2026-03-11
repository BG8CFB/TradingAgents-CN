"""
MCP 工具模块

本模块包含所有转换为 MCP 格式的本地工具。
使用 LangChain 的 @tool 装饰器定义，与 LangChain 工具接口一致。
"""

from .finance import (
    get_stock_news,
    get_stock_fundamentals,
    get_stock_sentiment,
    get_china_market_overview,
    get_stock_data,
    get_stock_data_minutes,
    get_company_performance_unified,  # 🔥 统一工具（替代旧的三个工具）
    get_macro_econ,
    get_money_flow,
    get_margin_trade,
    get_fund_data,
    get_fund_manager_by_name,
    get_index_data,
    get_csi_index_constituents,
    get_convertible_bond,
    get_block_trade,
    get_dragon_tiger_inst,
    get_finance_news,
    get_hot_news_7x24,
    get_current_timestamp
)

__all__ = [
    # 核心金融工具 (5个)
    "get_stock_news",
    "get_stock_fundamentals",
    "get_stock_sentiment",
    "get_china_market_overview",
    "get_stock_data",

    # 分钟级数据
    "get_stock_data_minutes",

    # 公司业绩数据（统一工具，支持A股/港股/美股）
    "get_company_performance_unified",

    # 宏观与资金流向
    "get_macro_econ",
    "get_money_flow",
    "get_margin_trade",

    # 基金数据
    "get_fund_data",
    "get_fund_manager_by_name",

    # 指数与其他
    "get_index_data",
    "get_csi_index_constituents",
    "get_convertible_bond",
    "get_block_trade",
    "get_dragon_tiger_inst",
    "get_finance_news",
    "get_hot_news_7x24",
    "get_current_timestamp",
]
