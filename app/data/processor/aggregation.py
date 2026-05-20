"""
周线/月线聚合 (Aggregation)

从 daily 数据聚合生成 weekly / monthly 行情数据。
在日线同步完成后作为后处理步骤触发。

边界条件处理：
  - 跨年周：使用 ISO 8601 周编号，整周聚合不受年界影响
  - 单交易日周：OHLCV 自然退化为单日值
  - 不完整当前周：trade_date 取当前周内最新交易日
"""

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def aggregate_period(
    daily_records: List[Dict[str, Any]],
    period: str,
    trade_dates: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    将日线记录聚合为周线或月线。

    Args:
        daily_records: 日线数据列表，每条需包含 symbol, trade_date, open, high, low, close, volume, amount
        period: "weekly" 或 "monthly"
        trade_dates: 交易日列表（用于确定交易日归属），可选

    Returns:
        聚合后的记录列表
    """
    if period not in ("weekly", "monthly"):
        raise ValueError(f"period 必须为 weekly 或 monthly，收到: {period}")

    if not daily_records:
        return []

    # 按 period key 分组
    groups: Dict[Tuple[str, str], List[Dict]] = {}
    for rec in daily_records:
        symbol = rec.get("symbol", "")
        trade_date_str = rec.get("trade_date", "")
        if not symbol or not trade_date_str:
            continue

        period_key = _get_period_key(trade_date_str, period)
        group_key = (symbol, period_key)

        if group_key not in groups:
            groups[group_key] = []
        groups[group_key].append(rec)

    # 每组聚合
    results = []
    for (symbol, period_key), records in groups.items():
        if not records:
            continue

        # 按日期排序
        records.sort(key=lambda r: r.get("trade_date", ""))

        aggregated = _aggregate_group(records, period)
        aggregated["symbol"] = symbol
        aggregated["period"] = period
        results.append(aggregated)

    return results


def _get_period_key(trade_date_str: str, period: str) -> str:
    """获取周/月的分组键"""
    if period == "weekly":
        # 使用 ISO 8601 周编号
        d = _parse_date(trade_date_str)
        iso_year, iso_week, _ = d.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    else:
        # 月线：YYYY-MM
        return trade_date_str[:7]


def _aggregate_group(records: List[Dict], period: str) -> Dict[str, Any]:
    """聚合一组日线数据为周线或月线"""
    first = records[0]
    last = records[-1]

    # OHLCV 聚合
    opens = [_safe_float(r.get("open")) for r in records]
    closes = [_safe_float(r.get("close")) for r in records]
    highs = [_safe_float(r.get("high")) for r in records]
    lows = [_safe_float(r.get("low")) for r in records]
    volumes = [_safe_float(r.get("volume")) for r in records]
    amounts = [_safe_float(r.get("amount")) for r in records]

    open_price = opens[0]
    close_price = closes[-1]
    high_price = max(h for h in highs if h is not None) if any(h is not None for h in highs) else None
    low_price = min(l for l in lows if l is not None) if any(l is not None for l in lows) else None
    total_volume = sum(v for v in volumes if v is not None)
    total_amount = sum(a for a in amounts if a is not None)

    # pre_close：上一周期最后一个交易日的收盘价
    pre_close = _safe_float(first.get("pre_close"))

    # trade_date：取该周期最后一个交易日的日期
    trade_date = last.get("trade_date", "")

    # 涨跌额/涨跌幅
    change = None
    pct_chg = None
    if close_price is not None and pre_close is not None and pre_close > 0:
        change = round(close_price - pre_close, 2)
        pct_chg = round(change / pre_close * 100, 2)

    result = {
        "trade_date": trade_date,
        "open": _round2(open_price),
        "high": _round2(high_price),
        "low": _round2(low_price),
        "close": _round2(close_price),
        "pre_close": _round2(pre_close),
        "change": _round2(change),
        "pct_chg": _round2(pct_chg),
        "volume": total_volume,
        "amount": total_amount,
    }

    # 继承数据源和更新时间
    result["data_source"] = last.get("data_source", "")
    result["updated_at"] = last.get("updated_at", "")

    return result


def _parse_date(date_str: str) -> date:
    """解析日期字符串"""
    cleaned = date_str.replace("-", "")
    return date(int(cleaned[:4]), int(cleaned[4:6]), int(cleaned[6:8]))


def _safe_float(value: Any) -> Optional[float]:
    """安全转换为浮点数"""
    if value is None or value == "" or value == "NaN":
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _round2(value: Optional[float]) -> Optional[float]:
    """保留 2 位小数"""
    if value is None:
        return None
    return round(value, 2)
