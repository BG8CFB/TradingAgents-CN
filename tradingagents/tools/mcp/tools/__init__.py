"""
MCP 工具模块

本模块包含所有转换为 MCP 格式的本地工具。
使用 FastMCP 的 @mcp.tool() 装饰器定义，与官方 MCP 工具接口一致。
"""

from .finance import (
    get_stock_news,
    get_stock_market_data,
    get_stock_fundamentals,
    get_stock_sentiment,
    get_china_market_overview,
    get_stock_data, get_stock_data_minutes, get_company_performance,
    get_company_performance_hk, get_company_performance_us, get_macro_econ,
    get_money_flow, get_margin_trade, get_fund_data, get_fund_manager_by_name,
    get_index_data, get_csi_index_constituents, get_convertible_bond,
    get_block_trade, get_dragon_tiger_inst, get_finance_news, get_hot_news_7x24,
    get_current_timestamp
)

from .reports import (
    list_reports,
    get_report_content,
    get_reports_batch,
    set_state,
    get_state,
    REPORT_DISPLAY_NAMES,
)

__all__ = [
    "get_stock_news",
    "get_stock_market_data",
    "get_stock_fundamentals",
    "get_stock_sentiment",
    "get_china_market_overview",
    # Finance tools
    "get_stock_data", "get_stock_data_minutes", "get_company_performance",
    "get_company_performance_hk", "get_company_performance_us", "get_macro_econ",
    "get_money_flow", "get_margin_trade", "get_fund_data", "get_fund_manager_by_name",
    "get_index_data", "get_csi_index_constituents", "get_convertible_bond",
    "get_block_trade", "get_dragon_tiger_inst", "get_finance_news", "get_hot_news_7x24",
    "get_current_timestamp",
    # 报告访问工具
    "list_reports",
    "get_report_content",
    "get_reports_batch",
    "set_state",
    "get_state",
    "REPORT_DISPLAY_NAMES",
]
