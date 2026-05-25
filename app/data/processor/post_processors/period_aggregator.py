"""日线→周线/月线聚合器。"""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class PeriodAggregator:
    """将日线行情聚合为周线或月线。"""

    def aggregate_to_weekly(self, daily_records: List[Dict]) -> List[Dict]:
        """日线 → 周线。"""
        return self._aggregate(daily_records, "weekly", self._week_key)

    def aggregate_to_monthly(self, daily_records: List[Dict]) -> List[Dict]:
        """日线 → 月线。"""
        return self._aggregate(daily_records, "monthly", self._month_key)

    def _aggregate(self, records: List[Dict], period: str, key_func) -> List[Dict]:
        if not records:
            return []

        groups: Dict[str, List[Dict]] = {}
        for rec in records:
            if "trade_date" not in rec or "symbol" not in rec:
                continue
            key = f"{rec['symbol']}_{key_func(rec['trade_date'])}"
            if key not in groups:
                groups[key] = []
            groups[key].append(rec)

        result = []
        for key, group in groups.items():
            if not group:
                continue
            group.sort(key=lambda r: r.get("trade_date", ""))

            aggregated = dict(group[-1])  # 复制最后一天的数据
            aggregated["open"] = group[0].get("open")
            valid_highs = [r.get("high") for r in group if r.get("high") is not None]
            aggregated["high"] = max(valid_highs) if valid_highs else None
            valid_lows = [r.get("low") for r in group if r.get("low") is not None]
            aggregated["low"] = min(valid_lows) if valid_lows else None
            aggregated["volume"] = sum(r.get("volume", 0) or 0 for r in group)
            aggregated["amount"] = sum(r.get("amount", 0) or 0 for r in group)
            aggregated["period"] = period
            aggregated["pre_close"] = group[0].get("pre_close")

            close = aggregated.get("close")
            pre_close = aggregated.get("pre_close")
            if close and pre_close and pre_close != 0:
                aggregated["change"] = round(close - pre_close, 2)
                aggregated["pct_chg"] = round((close - pre_close) / pre_close * 100, 4)

            result.append(aggregated)

        return result

    @staticmethod
    def _week_key(date_str: str) -> str:
        """获取 ISO 周标识。"""
        from datetime import datetime
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.isocalendar()[0]}-W{dt.isocalendar()[1]:02d}"

    @staticmethod
    def _month_key(date_str: str) -> str:
        return date_str[:7]  # YYYY-MM
