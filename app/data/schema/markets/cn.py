"""A 股市场特化字段。"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class CNBasicInfoFields:
    """A 股基本信息特化字段。"""

    area: Optional[str] = None           # 所属地区
    market_board: Optional[str] = None   # 主板 / 创业板 / 科创板 / 北交所
