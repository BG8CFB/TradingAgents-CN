"""
内置工具公共辅助函数
"""
import json
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

# 线程本地存储，每个线程有独立的 manager 实例
_thread_local = threading.local()


def get_manager():
    """获取 DataReader 实例（线程安全）

    返回一个代理对象，将所有方法调用转发到 app.data.reader 中对应的函数。
    兼容旧 DataSourceManager 的调用方式：get_manager().get_xxx(...)。
    """
    if not hasattr(_thread_local, 'manager'):
        _thread_local.manager = _DataReaderProxy()
        logger.debug(f"创建新的 DataReaderProxy 实例 (线程: {threading.current_thread().name})")
    return _thread_local.manager


class _DataReaderProxy:
    """
    数据读取代理，将旧 DataSourceManager 的方法签名映射到 reader.py 函数。

    旧调用方式：get_manager().get_stock_data(code, "us", start, end)
    实际调用：reader.get_stock_data_cross_market(code, "us", start, end)
    """

    def get_stock_data(self, code, market_type, start_date, end_date, indicators=None):
        from app.data import reader
        if market_type == "cn":
            return reader.get_stock_data("CN", code, start_date, end_date)
        elif market_type == "hk":
            return reader.get_stock_data("HK", code, start_date, end_date)
        elif market_type == "us":
            return reader.get_stock_data("US", code, start_date, end_date)
        return reader.get_stock_data_cross_market(code, market_type, start_date, end_date)

    def get_stock_data_minutes(self, market_type, code, start_datetime, end_datetime, freq):
        from app.data import reader
        return reader.get_stock_data_minutes(market_type, code, start_datetime, end_datetime, freq)

    def get_company_performance(self, **kwargs):
        from app.data import reader
        return reader.get_company_performance(**kwargs)

    def get_macro_econ(self, **kwargs):
        from app.data import reader
        return reader.get_macro_econ(**kwargs)

    def get_money_flow(self, **kwargs):
        from app.data import reader
        return reader.get_money_flow(**kwargs)

    def get_margin_trade(self, **kwargs):
        from app.data import reader
        return reader.get_margin_trade(**kwargs)

    def get_fund_data(self, **kwargs):
        from app.data import reader
        return reader.get_fund_data(**kwargs)

    def get_fund_manager_by_name(self, **kwargs):
        from app.data import reader
        return reader.get_fund_manager_by_name(**kwargs)

    def get_index_data(self, code, start_date, end_date):
        from app.data import reader
        return reader.get_index_data(code, start_date, end_date)

    def get_csi_index_constituents(self, **kwargs):
        from app.data import reader
        return reader.get_csi_index_constituents(**kwargs)

    def get_convertible_bond(self, **kwargs):
        from app.data import reader
        return reader.get_convertible_bond(**kwargs)

    def get_block_trade(self, **kwargs):
        from app.data import reader
        return reader.get_block_trade(**kwargs)

    def get_dragon_tiger_inst(self, **kwargs):
        from app.data import reader
        return reader.get_dragon_tiger_inst(**kwargs)

    def get_finance_news(self, query):
        from app.data import reader
        return reader.get_finance_news(query)

    def get_hot_news_7x24(self, limit=100):
        from app.data import reader
        return reader.get_hot_news_7x24(limit)


def format_result(data: Any, title: str, max_rows: int = 2000) -> str:
    """Format data to Markdown"""
    if data is None:
        return f"# {title}\n\nNo data found."

    if isinstance(data, list) and not data:
        return f"# {title}\n\nNo data found."

    if isinstance(data, str):
        # 如果字符串本身已经是Markdown表格，尝试截断行数
        if "|" in data and data.count('\n') > max_rows + 5:
            lines = data.split('\n')
            # 保留头部和前 max_rows 行
            header = lines[:2]
            content = lines[2:]
            if len(content) > max_rows:
                truncated_content = content[:max_rows]
                return "\n".join(header + truncated_content + [f"\n... (剩余 {len(content) - max_rows} 行已隐藏)"])
        return data

    # Assuming data is a list of dicts or a pandas DataFrame (converted to list of dicts)
    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
        # Truncate list if too long
        original_len = len(data)
        if original_len > max_rows:
            data = data[:max_rows]

        # Create markdown table
        headers = list(data[0].keys())
        header_row = "| " + " | ".join(headers) + " |"
        separator_row = "| " + " | ".join(["---"] * len(headers)) + " |"

        rows = []
        for item in data:
            row = "| " + " | ".join([str(item.get(h, "")) for h in headers]) + " |"
            rows.append(row)

        result = f"# {title}\n\n{header_row}\n{separator_row}\n" + "\n".join(rows)

        if original_len > max_rows:
            result += f"\n\n... (剩余 {original_len - max_rows} 行已隐藏)"

        return result

    return f"# {title}\n\n{str(data)}"
