"""
工具通用格式化函数
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


def format_result(data: Any, title: str, max_rows: int = 2000, max_cols: int = 15) -> str:
    """Format data to Markdown
    
    Args:
        data: 要格式化的数据
        title: 标题
        max_rows: 最大行数
        max_cols: 最大列数（超过时会截断）
    """
    if data is None:
        return f"# {title}\n\nNo data found."

    if isinstance(data, list) and not data:
        return f"# {title}\n\nNo data found."

    if isinstance(data, str):
        # 如果字符串本身已经是Markdown表格，尝试截断行数
        if "|" in data and data.count("\n") > max_rows + 5:
            lines = data.split("\n")
            # 保留头部和前 max_rows 行
            header = lines[:2]
            content = lines[2:]
            if len(content) > max_rows:
                truncated_content = content[:max_rows]
                return "\n".join(
                    header
                    + truncated_content
                    + [f"\n... (剩余 {len(content) - max_rows} 行已隐藏)"]
                )
        return data

    # 处理 pandas DataFrame
    try:
        import pandas as pd
        if isinstance(data, pd.DataFrame):
            # 截断列数
            original_cols = len(data.columns)
            if original_cols > max_cols:
                # 保留重要的列（前几列、后几列和关键指标列）
                important_cols = list(data.columns[:5])
                
                # 添加关键指标列（如果存在）
                key_indicators = ['macd_dif', 'macd_dea', 'macd', 'boll_mid', 'boll_upper', 'boll_lower',
                                 'rsi6', 'rsi12', 'rsi24', 'rsi14', 'ma5', 'ma10', 'ma20', 'ma60',
                                 'kdj_k', 'kdj_d', 'kdj_j']
                for col in key_indicators:
                    if col in data.columns and col not in important_cols:
                        important_cols.append(col)
                
                # 如果还有空间，添加后几列
                remaining_cols = [c for c in data.columns if c not in important_cols]
                if len(important_cols) < max_cols and remaining_cols:
                    important_cols.extend(remaining_cols[:max_cols - len(important_cols)])
                
                data = data[important_cols[:max_cols]]
                col_truncated = True
            else:
                col_truncated = False
            
            # 截断行数
            original_rows = len(data)
            if original_rows > max_rows:
                data = data.head(max_rows)
                row_truncated = True
            else:
                row_truncated = False
            
            # 转换为 markdown
            result = data.to_markdown(index=False)
            
            # 添加截断提示
            truncation_notes = []
            if col_truncated:
                truncation_notes.append(f"列数: 显示 {len(data.columns)}/{original_cols} 列")
            if row_truncated:
                truncation_notes.append(f"行数: 显示 {max_rows}/{original_rows} 行")
            
            if truncation_notes:
                result += f"\n\n... ({', '.join(truncation_notes)})"
            
            return f"# {title}\n\n{result}"
    except ImportError:
        pass

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
