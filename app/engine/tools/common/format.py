"""
工具通用格式化函数
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def format_result(data: Any, title: str, max_rows: int = 2000) -> str:
    """Format data to Markdown"""
    if data is None:
        return f"# {title}\n\nNo data found."

    if isinstance(data, list) and not data:
        return f"# {title}\n\nNo data found."

    if isinstance(data, str):
        # 字符串原样返回，不做行数/字符截断：截断会让 LLM 看不到完整数据，
        # 基于残缺数据得出结论（max_rows 参数保留仅为兼容调用签名，不再生效）
        return data

    # Assuming data is a list of dicts or a pandas DataFrame (converted to list of dicts)
    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
        # 列表全量输出，不按行数截断：隐藏的行对 LLM 不可见，会丢失数据
        original_len = len(data)

        # Create markdown table
        headers = list(data[0].keys())
        header_row = "| " + " | ".join(headers) + " |"
        separator_row = "| " + " | ".join(["---"] * len(headers)) + " |"

        rows = []
        for item in data:
            row = "| " + " | ".join([str(item.get(h, "")) for h in headers]) + " |"
            rows.append(row)

        result = f"# {title}\n\n{header_row}\n{separator_row}\n" + "\n".join(rows)

        return result

    return f"# {title}\n\n{str(data)}"
