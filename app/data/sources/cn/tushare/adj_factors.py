"""
Tushare 复权因子 Adapter

将 Tushare adj_factor API 返回的数据转换为 AdjFactorsSchema。

字段映射：
  ts_code → symbol（纯数字）
  trade_date → trade_date（YYYY-MM-DD）
  adj_factor → adj_factor
"""

from typing import Any, Optional

from app.data.schema.stock_adj_factors import AdjFactorsSchema
from app.data.sources.base.adapter import BaseAdapter


class TushareAdjFactorsAdapter(BaseAdapter):
    """Tushare 复权因子适配器"""

    def adapt_adj_factors(self, row: Any) -> Optional[AdjFactorsSchema]:
        """将 Tushare adj_factor 行数据转换为 AdjFactorsSchema"""
        get = row.get

        ts_code = str(get("ts_code", ""))
        symbol = ts_code.split(".")[0] if "." in ts_code else str(get("symbol", "")).zfill(6)

        trade_date = self._format_date(get("trade_date"))
        if not trade_date:
            return None

        return AdjFactorsSchema(
            symbol=symbol,
            trade_date=trade_date,
            adj_factor=self._safe_float(get("adj_factor")),
            fore_adj_factor=self._safe_float(get("fore_adj_factor")),
            back_adj_factor=self._safe_float(get("back_adj_factor")),
            data_source="tushare",
            updated_at="",
        )

    @staticmethod
    def _format_date(value) -> Optional[str]:
        """格式化日期为 YYYY-MM-DD"""
        if value is None:
            return None
        s = str(value).strip()
        if len(s) == 8 and s.isdigit():
            return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        if len(s) == 10 and "-" in s:
            return s
        return s
