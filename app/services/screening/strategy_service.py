"""选股策略运行服务 — L0 消费层（读 factor_scores，过滤+排序+落库推荐）。

边界：只经 DataInterface 读写标准库，不直连数据源或存储内部；
LLM 相关（L1）在 insight_service，本服务不触 LLM（自动研判由
generate_daily_recommendations 的调用方（worker job）串联，见 Task 8/9）。
"""

import hashlib
import json
import logging
import math
from datetime import datetime, timedelta
from numbers import Real
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from app.data.core.interface import DataInterface
from app.data.factors.strategy_config import get_factor_groups, get_strategies, get_style_weights
from app.utils.timezone import now_tz

logger = logging.getLogger(__name__)

_OPS = {
    ">": lambda v, t: v is not None and v > t,
    ">=": lambda v, t: v is not None and v >= t,
    "<": lambda v, t: v is not None and v < t,
    "<=": lambda v, t: v is not None and v <= t,
    "==": lambda v, t: v is not None and v == t,
    "!=": lambda v, t: v is not None and v != t,
    "between": lambda v, t: v is not None and t[0] <= v <= t[1],
}

def is_finite_number(value: Any) -> bool:
    """Missing, booleans, strings and non-finite values are not factor evidence."""
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)


def factor_batch_fingerprint(items: List[Dict]) -> str:
    """Detect same-date input changes without treating a timestamp-only rerun as new."""
    def clean(value):
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()
                    if key not in {"_id", "updated_at", "created_at", "_calculation_id"}}
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, Real) and not isinstance(value, bool) and not math.isfinite(value):
            return None
        return value

    rows = sorted((clean(item) for item in items), key=lambda row: row.get("symbol") or "")
    encoded = json.dumps(rows, sort_keys=True, ensure_ascii=False, allow_nan=False, default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


def strategy_data_quality(items: List[Dict], strategy: Dict,
                          extra_conditions: Optional[List[Dict]] = None) -> Dict:
    """Coverage includes hard filters AND every configured scoring contributor.

    eligible_count means rows evaluable by the hard filters and rankable by a
    finite score, before testing thresholds. A partially scored row can remain a
    candidate, but missing ranking inputs must never be described as complete.
    """
    groups = get_factor_groups()
    known_factors = {field for fields in groups.values() for field in fields}
    filters = strategy.get("filters", []) + (extra_conditions or [])
    required = {c["field"] for c in filters}
    score_field = f"score_{strategy['style']}"
    contributors = {
        field for group, weight in get_style_weights()[strategy["style"]].items()
        if weight > 0 for field in groups[group]
    }
    fields = sorted(required | contributors | {score_field})

    def available(row, field):
        value = row.get(field)
        if field in known_factors or field == score_field:
            return is_finite_number(value)
        return value is not None and (not isinstance(value, Real) or is_finite_number(value))

    total = len(items)
    coverage = {field: {"available": sum(available(row, field) for row in items),
                        "total": total} for field in fields}
    missing = [field for field, count in coverage.items() if not count["available"]]
    partial = [field for field, count in coverage.items()
               if 0 < count["available"] < total]
    eligible = sum(all(available(row, field) for field in required | {score_field})
                   for row in items)
    status = "insufficient" if not eligible else "partial" if missing or partial else "complete"
    return {"status": status, "total_universe": total, "eligible_count": eligible,
            "field_coverage": coverage, "missing_fields": missing, "partial_fields": partial}


def expected_completed_trade_date(calendar: List[Dict], current: datetime) -> Optional[str]:
    """Use a confirmed CN calendar, never weekday guesses or a stale calendar tail.

    Before the Shanghai 15:00 close today's quotes are not a completed session.
    Every date back to the selected open day must have an explicit calendar row.
    """
    current = current.astimezone(ZoneInfo("Asia/Shanghai"))
    cutoff = current.date() - (timedelta(days=1) if current.hour < 15 else timedelta())
    days = {}
    for row in calendar:
        value = row.get("is_open")
        if value in (0, 1) and not isinstance(value, str):
            days.setdefault(row.get("cal_date"), set()).add(bool(value))
    for delta in range(45):
        day = (cutoff - timedelta(days=delta)).isoformat()
        state = days.get(day)
        if state not in ({False}, {True}):
            return None
        if state == {True}:
            return day
    return None


async def latest_expected_trade_date() -> Optional[str]:
    current = datetime.now(ZoneInfo("Asia/Shanghai"))
    result = await DataInterface.get_instance().screen(
        "CN", "trade_calendar",
        filters={"exchange": "SSE", "cal_date": {
            "$gte": (current.date() - timedelta(days=45)).isoformat(),
            "$lte": current.date().isoformat()}},
        projection={"cal_date": 1, "is_open": 1}, limit=0,
    )
    return expected_completed_trade_date(result["items"], current)


def snapshot_is_stale(as_of: Optional[str], expected: Optional[str],
                      needs_refresh: Optional[bool]) -> Optional[bool]:
    """A future-dated batch is not confirmed fresh either."""
    if needs_refresh:
        return True
    return as_of != expected if as_of and expected else None


class StrategyService:

    async def list_strategies(self) -> List[Dict[str, Any]]:
        strategies = []
        for s in get_strategies():
            strategies.append({
                "id": s["id"], "name": s["name"], "description": s.get("description", ""),
                "style": s["style"], "top_n": s.get("top_n", 30),
                "is_default": bool(s.get("default")), "filters": s.get("filters", []),
            })
        return strategies

    async def _load_latest_factors(self) -> tuple:
        trade_date = await DataInterface.get_instance().screening.latest_factor_trade_date("CN")
        if not trade_date:
            return [], None
        result = await DataInterface.get_instance().screen(
            "CN", "factor_scores", filters={"trade_date": trade_date}, limit=0)
        items = result.get("items", [])
        return items, trade_date

    async def run_strategy(self, strategy_id: str,
                           extra_conditions: Optional[List[Dict]] = None,
                           limit: Optional[int] = None) -> Dict[str, Any]:
        strategy = next((s for s in get_strategies() if s["id"] == strategy_id), None)
        if not strategy:
            raise ValueError(f"未知策略模板: {strategy_id}")
        items, trade_date = await self._load_latest_factors()
        return self._evaluate_strategy(items, trade_date, strategy, extra_conditions, limit)

    def _evaluate_strategy(self, items, trade_date, strategy, extra_conditions=None, limit=None):
        quality = strategy_data_quality(items, strategy, extra_conditions)
        style = strategy["style"]
        numeric_fields = {field for group in get_factor_groups().values() for field in group}

        passed = [r for r in items if self._match(r, strategy.get("filters", []), numeric_fields)
                  and self._match(r, extra_conditions or [], numeric_fields)
                  and is_finite_number(r.get(f"score_{style}"))]

        passed.sort(key=lambda r: (-r[f"score_{style}"], r.get("symbol") or ""))
        top_n = limit or strategy.get("top_n", 30)
        top = passed[:top_n]

        return {
            "total": len(passed),
            "items": [self._to_item(r, strategy) for r in top],
            "as_of": trade_date,
            "strategy": strategy["id"],
            "style": style,
            "data_quality": quality,
        }

    async def get_daily(self, strategy_id: Optional[str] = None) -> Dict[str, Any]:
        """读最新交易日落库推荐（router /daily 委托此方法，避免 routers 触 storage）。"""
        docs = await DataInterface.get_instance().screening.latest_recommendations("CN", strategy_id)
        trade_date = docs[0]["trade_date"] if docs else None
        factor_rows, factor_trade_date = await self._load_latest_factors()
        expected = await latest_expected_trade_date()
        as_of = trade_date or factor_trade_date
        needs_refresh = None
        if docs and factor_trade_date:
            if trade_date < factor_trade_date:
                needs_refresh = True
            elif trade_date == factor_trade_date:
                fingerprint = factor_batch_fingerprint(factor_rows)
                known = [d.get("factor_batch_fingerprint") for d in docs]
                if all(known):
                    needs_refresh = any(value != fingerprint for value in known)
        return {
            "trade_date": trade_date,
            "status": "ready" if docs else "not_generated" if factor_trade_date else "no_factor_data",
            "factor_trade_date": factor_trade_date,
            "expected_trade_date": expected,
            "is_stale": snapshot_is_stale(as_of, expected, needs_refresh),
            "recommendation_needs_refresh": needs_refresh,
            "strategies": [
                {"strategy_id": d["strategy_id"], "strategy_name": d.get("strategy_name"),
                 "style": d.get("style"), "total": d.get("total"),
                 "items": d.get("items", []), "insight_status": d.get("insight_status"),
                 "generated_at": d.get("generated_at"),
                 "data_quality": d.get("data_quality") or {
                     "status": "unknown", "total_universe": None, "eligible_count": None,
                     "field_coverage": {}, "missing_fields": [], "partial_fields": []}}
                for d in docs
            ],
        }

    async def generate_daily_recommendations(self) -> Dict[str, Any]:
        """Read one existing factor batch, then persist all strategies without LLM I/O."""
        items, trade_date = await self._load_latest_factors()
        if not items or not trade_date:
            return {"status": "no_factor_data", "strategies_written": 0, "strategies_failed": 0}
        written = 0
        failed = 0
        fingerprint = factor_batch_fingerprint(items)
        for s in get_strategies():
            try:
                result = self._evaluate_strategy(items, trade_date, s)
                await DataInterface.get_instance().screening.save_generated_recommendation({
                    "strategy_id": s["id"],
                    "trade_date": result["as_of"],
                    "strategy_name": s["name"],
                    "style": s["style"],
                    "total": result["total"],
                    "items": result["items"],
                    "data_quality": result["data_quality"],
                    "factor_batch_fingerprint": fingerprint,
                    "insight_status": "none",
                    "generated_at": now_tz().isoformat(),
                    "data_source": "computed",
                }, market="CN")
                written += 1
            except Exception as e:
                failed += 1
                # 单模板失败不阻塞其余模板（spec §13 降级）
                logger.error("每日推荐生成失败 %s: %s", s["id"], e, exc_info=True)
        logger.info("每日推荐生成完成：%d/%d 个模板", written, len(get_strategies()))
        return {"status": "ready" if not failed else "partial" if written else "failed",
                "trade_date": trade_date, "strategies_written": written, "strategies_failed": failed}

    # ── 内部 ────────────────────────────────────────────────

    @staticmethod
    def _match(record: Dict, conditions: List[Dict], numeric_fields=None) -> bool:
        if numeric_fields is None:
            numeric_fields = {field for group in get_factor_groups().values() for field in group}
        for cond in conditions:
            field, op, target = cond.get("field"), cond.get("op"), cond.get("value")
            fn = _OPS.get(op)
            if fn is None:
                logger.warning("未知操作符 %s，拒绝条件: %s", op, cond)
                return False
            value = record.get(field)
            if (value is None or field in numeric_fields and not is_finite_number(value)
                    or isinstance(value, Real) and not is_finite_number(value)):
                return False
            try:
                if not fn(value, target):
                    return False
            except (TypeError, ValueError):
                return False
        return True

    @staticmethod
    def _to_item(r: Dict, strategy: Dict) -> Dict:
        fields = sorted({k for group in get_factor_groups().values() for k in group})
        factors = {k: r.get(k) for k in fields if is_finite_number(r.get(k))}
        # 双写：英文 signals 兼容既有消费方；signal_items 供前端中文化渲染
        matched = [c for c in strategy.get("filters", [])
                   if is_finite_number(r.get(c["field"]))]
        signals = [
            f"{c['field']} {c['op']} {c['value']}" for c in matched
        ]
        signal_items = [
            {"field": c["field"], "op": c["op"], "value": c["value"]}
            for c in matched
        ]
        style = strategy["style"]
        return {
            "symbol": r.get("symbol"),
            "code": r.get("symbol"),  # 前端既有列用 code（兼容）
            "name": r.get("name"),
            "industry": r.get("industry"),
            "score": r.get(f"score_{style}"),
            "score_short_term": r.get("score_short_term") if is_finite_number(r.get("score_short_term")) else None,
            "score_balanced": r.get("score_balanced") if is_finite_number(r.get("score_balanced")) else None,
            "score_value": r.get("score_value") if is_finite_number(r.get("score_value")) else None,
            "factors": factors,
            "signals": signals,
            "signal_items": signal_items,
        }
