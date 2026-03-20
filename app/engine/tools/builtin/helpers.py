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
    """获取当前线程的 DataSourceManager 实例（线程安全）"""
    from app.data.manager import DataSourceManager

    if not hasattr(_thread_local, 'manager'):
        _thread_local.manager = DataSourceManager()
        logger.debug(f"创建新的 DataSourceManager 实例 (线程: {threading.current_thread().name})")
    return _thread_local.manager


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
