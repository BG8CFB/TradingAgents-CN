"""
Tushare 每日指标 Adapter

将 Tushare daily_basic API 返回的数据转换为 DailyIndicatorsSchema。

字段映射：
  ts_code → symbol（纯数字）
  trade_date → trade_date（YYYY-MM-DD）
  pe → pe_ttm（Tushare 的 pe 就是 TTM）
  pb → pb
  ps → ps_ttm
  turnover_rate → turnover_rate
  turnover_rate_f → turnover_rate_f
  total_mv → total_mv（万元 → 元 × 10000）
  circ_mv → circ_mv（万元 → 元 × 10000）
  volume_ratio → volume_ratio
"""

from typing import Any, Optional

from app.data.schema.stock_daily_indicators import DailyIndicatorsSchema
from app.data.sources.base.adapter import BaseAdapter


class TushareDailyIndicatorsAdapter(BaseAdapter):
    """Tushare 每日指标适配器"""

    def adapt_daily_indicators(self, row: Any) -> Optional[DailyIndicatorsSchema]:
        """将 Tushare daily_basic 行数据转换为 DailyIndicatorsSchema"""
        get = row.get

        ts_code = str(get("ts_code", ""))
        symbol = ts_code.split(".")[0] if "." in ts_code else str(get("symbol", "")).zfill(6)

        trade_date = self._format_date(get("trade_date"))
        if not trade_date:
            return None

        # 市值转换：万元 → 元
        total_mv = self._safe_float(get("total_mv"))
        if total_mv is not None:
            total_mv = total_mv * 10000

        circ_mv = self._safe_float(get("circ_mv"))
        if circ_mv is not None:
            circ_mv = circ_mv * 10000

        return DailyIndicatorsSchema(
            symbol=symbol,
            trade_date=trade_date,
            pe_ttm=self._safe_float(get("pe")),
            pb=self._safe_float(get("pb")),
            ps_ttm=self._safe_float(get("ps")),
            turnover_rate=self._safe_float(get("turnover_rate")),
            turnover_rate_f=self._safe_float(get("turnover_rate_f")),
            total_mv=total_mv,
            circ_mv=circ_mv,
            volume_ratio=self._safe_float(get("volume_ratio")),
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
