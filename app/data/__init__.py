"""数据访问层 — 统一数据平台。

对外入口: app.data.core.interface.DataInterface (单例)
读取层:   app.data.core.reader.Reader
"""

from app.data.core.reader import Reader
from app.data.core.interface import DataInterface

__all__ = ["Reader", "DataInterface"]
