"""BaoStock CN Provider — 调用 api/ 子模块获取原始数据。"""

import logging
from datetime import datetime
from typing import Optional, Tuple

import pandas as pd

from app.data.sources.base.provider import BaseProvider

logger = logging.getLogger(__name__)


def _derive_year_quarter(start_date: str, end_date: str) -> Tuple[Optional[int], Optional[int]]:
    """从 start_date/end_date 推导最近的报告期 year/quarter。

    BaoStock 财务接口一次只查单个 year+quarter。这里以 end_date（或 start_date）
    为基准推导其所属季度，让调用方至少拉到目标期间的数据。未提供日期时返回
    (None, None)，BaoStock 会返回最新一期。
    """
    ref = end_date or start_date
    if not ref:
        return None, None
    try:
        dt = datetime.strptime(str(ref).replace("-", "")[:8], "%Y%m%d")
    except ValueError:
        return None, None
    month = dt.month
    if month <= 3:
        return dt.year - 1, 4
    elif month <= 6:
        return dt.year, 1
    elif month <= 9:
        return dt.year, 2
    else:
        return dt.year, 3


class BaoStockCNProvider(BaseProvider):
    """BaoStock A 股数据源 Provider。"""

    def __init__(self):
        super().__init__(name="baostock", market="CN")

    async def connect(self) -> bool:
        try:
            from .api.connection import is_available
            if not is_available():
                return False
            self.connected = True
            return True
        except Exception as e:
            logger.error(f"BaoStock 连接失败: {e}")
            return False

    def is_available(self) -> bool:
        try:
            from .api.connection import is_available
            return is_available()
        except Exception as e:
            logger.debug(f"BaoStock可用性检查失败: {e}")
            return False

    async def get_stock_list(self, **kwargs) -> pd.DataFrame:
        from .api.stock_basic import fetch_stock_list
        return await fetch_stock_list()

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        from .api.daily_quotes import fetch_daily_quotes
        return await fetch_daily_quotes(symbol, start_date, end_date)

    async def get_financial_data(
        self, symbol: str, start_date: str, end_date: str,
        statement_type: str = "", **kwargs
    ) -> pd.DataFrame:
        from .api.financial import fetch_financial_data
        # BaoStock 财务接口按 year+quarter 查询，从 start_date/end_date 推导
        # 最近一个季度的 year/quarter 传入（BaoStock 一次只查单个季度）。
        # 若未提供日期则拉取最新一期（year/quarter 为 None 时 BaoStock 返回最新）。
        year, quarter = _derive_year_quarter(start_date, end_date)
        return await fetch_financial_data(symbol, year=year, quarter=quarter)

    async def get_adj_factors(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        from .api.daily_quotes import fetch_adj_factors
        return await fetch_adj_factors(symbol, start_date, end_date)
