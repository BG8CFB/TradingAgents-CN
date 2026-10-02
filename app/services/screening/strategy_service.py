"""选股策略运行服务 — L0 消费层（读 factor_scores，过滤+排序+落库推荐）。

边界：只经 DataInterface/repo 读标准库，不直连数据源；
LLM 相关（L1）在 insight_service，本服务不触 LLM（自动研判由
generate_daily_recommendations 的调用方（worker job）串联，见 Task 8/9）。
"""

import logging
from typing import Any, Dict, List, Optional

from app.data.core.interface import DataInterface
from app.data.factors.strategy_config import get_strategies
from app.data.storage.mongo.repositories.factor_scores_repo import FactorScoresRepo
from app.data.storage.mongo.repositories.screening_recommendations_repo import (
    ScreeningRecommendationsRepo,
)
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

# 策略结果条目里回传给前端的因子子集（控制响应体大小）
_KEY_FACTORS = [
    "ret_5d", "ret_20d", "bias_ma20", "ma20_slope", "macd_golden_days",
    "turnover_amp", "main_inflow_5d_pct", "pe_ttm_percentile", "roe",
    "net_profit_yoy",
]


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
        trade_date = await FactorScoresRepo().get_latest_trade_date("CN")
        if not trade_date:
            return []
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
        loaded = await self._load_latest_factors()
        if not loaded:
            # 空数据也要返回完整响应形状（router 按 result["style"] 取值）
            return {"total": 0, "items": [], "as_of": None,
                    "strategy": strategy_id, "style": strategy["style"]}
        items, trade_date = loaded

        passed = [r for r in items if self._match(r, strategy.get("filters", []))
                  and self._match(r, extra_conditions or [])]

        style = strategy["style"]
        passed.sort(key=lambda r: (r.get(f"score_{style}") is not None,
                                   r.get(f"score_{style}") or 0.0), reverse=True)
        top_n = limit or strategy.get("top_n", 30)
        top = passed[:top_n]

        return {
            "total": len(passed),
            "items": [self._to_item(r, strategy) for r in top],
            "as_of": trade_date,
            "strategy": strategy_id,
            "style": style,
        }

    async def get_daily(self, strategy_id: Optional[str] = None) -> Dict[str, Any]:
        """读最新交易日落库推荐（router /daily 委托此方法，避免 routers 触 storage）。"""
        repo = ScreeningRecommendationsRepo()
        if strategy_id:
            docs = [d for d in [await repo.get_latest_by_strategy("CN", strategy_id)] if d]
        else:
            latest = await repo.get_latest_any("CN")
            docs = await repo.list_strategies_on_date("CN", latest["trade_date"]) if latest else []
        trade_date = docs[0]["trade_date"] if docs else None
        return {
            "trade_date": trade_date,
            "strategies": [
                {"strategy_id": d["strategy_id"], "strategy_name": d.get("strategy_name"),
                 "style": d.get("style"), "total": d.get("total"),
                 "items": d.get("items", []), "insight_status": d.get("insight_status"),
                 "generated_at": d.get("generated_at")}
                for d in docs
            ],
        }

    async def generate_daily_recommendations(self) -> Dict[str, Any]:
        """对全部模板跑 Top-N 并落库当日推荐（幂等覆盖）。"""
        written = 0
        for s in get_strategies():
            try:
                result = await self.run_strategy(s["id"])
                if not result["as_of"]:
                    logger.warning("factor_scores 无数据，跳过 %s", s["id"])
                    continue
                await ScreeningRecommendationsRepo().upsert_daily({
                    "strategy_id": s["id"],
                    "trade_date": result["as_of"],
                    "strategy_name": s["name"],
                    "style": s["style"],
                    "total": result["total"],
                    "items": result["items"],
                    "insight_status": "none",
                    "generated_at": now_tz().isoformat(),
                    "data_source": "computed",
                }, market="CN")
                written += 1
            except Exception as e:
                # 单模板失败不阻塞其余模板（spec §13 降级）
                logger.error("每日推荐生成失败 %s: %s", s["id"], e, exc_info=True)
        logger.info("每日推荐生成完成：%d/%d 个模板", written, len(get_strategies()))
        return {"strategies_written": written}

    # ── 内部 ────────────────────────────────────────────────

    @staticmethod
    def _match(record: Dict, conditions: List[Dict]) -> bool:
        for cond in conditions:
            field, op, target = cond.get("field"), cond.get("op"), cond.get("value")
            fn = _OPS.get(op)
            if fn is None:
                logger.warning("未知操作符 %s，条件忽略: %s", op, cond)
                continue
            if not fn(record.get(field), target):
                return False
        return True

    @staticmethod
    def _to_item(r: Dict, strategy: Dict) -> Dict:
        factors = {k: r.get(k) for k in _KEY_FACTORS if r.get(k) is not None}
        # 双写：英文 signals 兼容既有消费方；signal_items 供前端中文化渲染
        matched = [c for c in strategy.get("filters", [])
                   if r.get(c["field"]) is not None]
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
            "score_short_term": r.get("score_short_term"),
            "score_balanced": r.get("score_balanced"),
            "score_value": r.get("score_value"),
            "factors": factors,
            "signals": signals,
            "signal_items": signal_items,
        }
