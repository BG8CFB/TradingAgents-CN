"""公共类型别名与安全转换工具函数。"""

from datetime import datetime
from typing import Optional

import numpy as np

DateStr = str  # YYYY-MM-DD 格式
DecimalStr = str  # 高精度数字字符串


def _safe_float(value) -> Optional[float]:
    """安全转换为 float，NaN/None/空字符串返回 None。"""
    if value is None or value == "":
        return None
    if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _safe_int(value) -> Optional[int]:
    """安全转换为 int，NaN/None/空字符串返回 None。"""
    if value is None or value == "":
        return None
    if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _safe_str(value) -> Optional[str]:
    """安全转换为 str，NaN/None 返回 None。"""
    if value is None:
        return None
    if isinstance(value, float) and np.isnan(value):
        return None
    s = str(value).strip()
    return s if s else None


def _parse_date(value) -> Optional[str]:
    """将各种日期格式统一为 YYYY-MM-DD。"""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # YYYYMMDD -> YYYY-MM-DD
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    # 已经是 YYYY-MM-DD
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    # 尝试 datetime 解析
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass
    try:
        dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass
    return s if len(s) == 10 else None


def _round_price(value: Optional[float], precision: int = 2) -> Optional[float]:
    """价格精度处理。"""
    if value is None:
        return None
    return round(value, precision)


def _round_ratio(value: Optional[float], precision: int = 4) -> Optional[float]:
    """比率精度处理。"""
    if value is None:
        return None
    return round(value, precision)
