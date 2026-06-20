"""日线→周线/月线聚合器。"""

import logging
from datetime import datetime, timedelta
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

        # 按 symbol 分桶，每个 symbol 的组按 period_key 升序排序，
        # 用于正确推导 pre_close（上一期收盘）。
        by_symbol: Dict[str, List[str]] = {}
        for key in groups:
            sym, _, _ = key.partition("_")
            by_symbol.setdefault(sym, []).append(key)
        for sym in by_symbol:
            by_symbol[sym].sort()

        result: List[Dict] = []
        for sym, sorted_keys in by_symbol.items():
            prev_close = None
            for key in sorted_keys:
                group = groups[key]
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

                # pre_close 标准语义：上一期收盘价；首期保留日线自身前收。
                # 这样 change = 本期 close - 上期 close，跨期涨跌幅正确。
                if prev_close is not None:
                    aggregated["pre_close"] = prev_close
                else:
                    aggregated["pre_close"] = group[0].get("pre_close")

                close = aggregated.get("close")
                pre_close = aggregated.get("pre_close")
                if close and pre_close and pre_close != 0:
                    aggregated["change"] = round(close - pre_close, 2)
                    aggregated["pct_chg"] = round((close - pre_close) / pre_close * 100, 4)

                result.append(aggregated)
                prev_close = close

        return result

    @staticmethod
    def _week_key(date_str: str) -> str:
        """获取周标识（本周一日期，避免 ISO 周跨年漂移）。

        ISO 周历会把 2024-12-30 归入 2025-W01，导致跨年周被拆开。
        改用"以周一为起点的日历周"：直接取本周一日期作为 group key，
        确保同一自然周的所有日线落在同一组。
        """
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        monday = dt - timedelta(days=dt.weekday())
        return monday.strftime("%Y-%m-%d")

    @staticmethod
    def _month_key(date_str: str) -> str:
        return date_str[:7]  # YYYY-MM
