"""L1 快速研判服务 — 独立单次 LLM 调用（不经过 engine/工作流）。

成本边界（spec §4/§10）：
- 手动路径：按钮触发，按 (user_id, 自然日) 配额限制，失败不扣配额但落审计
- 每日自动路径：system_settings 开关 screening_daily_insight_enabled（默认关），
  调度天然每日至多 1 次，写 screening_recommendations 条目级 insight
- 前端只传 symbols；服务端按 symbols+最新 trade_date 从 factor_scores 重取因子，
  不信任前端传入的因子值
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.data.core.interface import DataInterface
from app.data.storage.mongo.repositories.factor_scores_repo import FactorScoresRepo
from app.data.storage.mongo.repositories.screening_insights_repo import (
    ScreeningInsightsRepo,
)
from app.data.storage.mongo.repositories.screening_recommendations_repo import (
    ScreeningRecommendationsRepo,
)
from app.llm.core.types import Message, Role
from app.utils.timezone import now_tz

logger = logging.getLogger(__name__)

DEFAULT_INSIGHT_SYSTEM_PROMPT = """你是一名严谨的量化研究员。用户给你一批通过多因子策略
初筛的候选股票及其关键因子数据。请对每一只股票输出 2-3 句中文研判：
第 1 句概括核心逻辑（因子数据支持的选股理由）；第 2 句指出主要风险；
第 3 句（可选）说明适合什么投资风格/场景。

要求：
- 只基于给出的因子数据做客观解读，不编造数据里没有的信息
- 禁止给出任何买卖指令、目标价或仓位建议
- 输出必须是合法 JSON：{"insights": {"<symbol>": "<研判文本>", ...}}，
  每只入参 symbol 都要有对应键，不要输出 JSON 以外的任何内容"""

SETTING_DAILY_ENABLED = "screening_daily_insight_enabled"
SETTING_MANUAL_LIMIT = "screening_manual_insight_daily_limit"
SETTING_MODEL = "screening_insight_model"
SETTING_PROMPT = "screening_insight_prompt"

DEFAULT_MANUAL_LIMIT = 10
MAX_SYMBOLS_PER_CALL = 30
_INSIGHT_FACTORS = [
    "ret_5d", "ret_20d", "bias_ma20", "macd_golden_days", "turnover_amp",
    "main_inflow_5d_pct", "pe_ttm_percentile", "dividend_yield",
    "roe", "net_profit_yoy", "debt_ratio",
]


class QuotaExceededError(Exception):
    """手动研判超出当日配额。"""


class ScreeningInsightService:

    # ── 设置 ────────────────────────────────────────────────

    async def get_settings(self) -> Dict[str, Any]:
        from app.services.config import config_service
        try:
            stored = await config_service.get_system_settings() or {}
        except Exception as e:
            logger.warning("读取 system_settings 失败，用默认值: %s", e)
            stored = {}
        return {
            "daily_enabled": bool(stored.get(SETTING_DAILY_ENABLED, False)),
            "manual_daily_limit": int(stored.get(SETTING_MANUAL_LIMIT,
                                                 DEFAULT_MANUAL_LIMIT)),
            "model": stored.get(SETTING_MODEL) or None,
            "prompt": stored.get(SETTING_PROMPT) or DEFAULT_INSIGHT_SYSTEM_PROMPT,
        }

    async def quota_remaining(self, user_id: str) -> int:
        settings = await self.get_settings()
        today = now_tz().strftime("%Y-%m-%d")
        used = await ScreeningInsightsRepo().count_today_done(user_id, today)
        return max(0, settings["manual_daily_limit"] - used)

    # ── 手动路径 ────────────────────────────────────────────

    async def generate_manual(self, symbols: List[str], user_id: str,
                              strategy_id: Optional[str] = None,
                              conditions_digest: Optional[str] = None) -> Dict[str, Any]:
        symbols = [s for s in symbols if s][:MAX_SYMBOLS_PER_CALL]
        if not symbols:
            raise ValueError("symbols 不能为空")

        remaining = await self.quota_remaining(user_id)
        if remaining <= 0:
            raise QuotaExceededError("今日手动研判配额已用完")

        settings = await self.get_settings()
        audit = {
            "created_at": now_tz().isoformat(),
            "trigger": "manual", "user_id": user_id,
            "trade_date": None, "strategy_id": strategy_id,
            "conditions_digest": conditions_digest,
            "symbols": symbols, "insights": {},
            "model": settings["model"] or "analyst_default",
            "tokens_used": None, "status": "pending",
        }
        try:
            rows, trade_date = await self._fetch_factor_rows(symbols)
            if not rows:
                raise ValueError("factor_scores 中无这些 symbol 的最新因子数据")
            prompt = self._build_prompt(rows)
            text, usage = await self._call_llm(prompt, settings)
            insights = self._parse_json_insights(text, symbols)
            audit.update({
                "trade_date": trade_date, "insights": insights,
                "tokens_used": usage, "status": "done",
            })
            await ScreeningInsightsRepo().insert_one(audit)
            return {
                "insights": insights, "trade_date": trade_date,
                "quota_remaining": remaining - 1,
            }
        except QuotaExceededError:
            raise
        except Exception as e:
            # 失败审计：不扣配额（count 只数 done），向上抛给 API 层报错
            audit["status"] = "failed"
            audit["error"] = str(e)[:500]
            try:
                await ScreeningInsightsRepo().insert_one(audit)
            except Exception as log_err:
                logger.error("研判失败审计落库异常: %s", log_err, exc_info=True)
            raise

    # ── 每日自动路径（开关控制） ─────────────────────────────

    async def run_daily_auto_if_enabled(self) -> Optional[Dict[str, Any]]:
        """开关开启时对默认策略 Top-20 生成研判并写回当日推荐记录。

        开关关闭返回 None（调用方以此区分「未启用」与「执行结果」）。
        """
        settings = await self.get_settings()
        if not settings["daily_enabled"]:
            return None
        repo = ScreeningRecommendationsRepo()
        from app.data.factors.strategy_config import get_default_strategy
        default_id = get_default_strategy()["id"]
        doc = await repo.get_latest_by_strategy("CN", default_id)
        if not doc or not doc.get("items"):
            return {"status": "skipped", "reason": "no_recommendations"}
        symbols = [it["symbol"] for it in doc["items"][:20]]
        try:
            rows, _ = await self._fetch_factor_rows(symbols)
            prompt = self._build_prompt(rows)
            text, usage = await self._call_llm(prompt, settings)
            insights = self._parse_json_insights(text, symbols)
            for it in doc["items"]:
                if it["symbol"] in insights:
                    it["insight"] = insights[it["symbol"]]
            await repo.upsert_daily({
                **doc, "insight_status": "done",
                "insight_generated_at": now_tz().isoformat(),
            }, market="CN")
            return {"status": "done", "symbols": len(insights),
                    "tokens_used": usage}
        except Exception as e:
            # 失败：列表保留，标记 failed，不重试（spec §13）
            logger.error("每日自动研判失败: %s", e, exc_info=True)
            await repo.upsert_daily({**doc, "insight_status": "failed"},
                                    market="CN")
            return {"status": "failed", "error": str(e)[:200]}

    # ── 内部 ────────────────────────────────────────────────

    async def _fetch_factor_rows(self, symbols: List[str]):
        trade_date = await FactorScoresRepo().get_latest_trade_date("CN")
        if not trade_date:
            return [], None
        result = await DataInterface.get_instance().screen(
            "CN", "factor_scores",
            filters={"trade_date": trade_date, "symbol": {"$in": symbols}},
            limit=0)
        return result.get("items", []), trade_date

    @staticmethod
    def _build_prompt(rows: List[Dict]) -> str:
        lines = ["以下是通过多因子策略初筛的候选股因子摘要（数据截至最新交易日）："]
        for r in rows:
            parts = [f"股票 {r.get('symbol')} {r.get('name') or ''} "
                     f"行业:{r.get('industry') or '未知'} "
                     f"短线分:{r.get('score_short_term')} "
                     f"均衡分:{r.get('score_balanced')} "
                     f"价值分:{r.get('score_value')}"]
            kv = [f"{k}={r.get(k)}" for k in _INSIGHT_FACTORS
                  if r.get(k) is not None]
            parts.append("关键因子: " + ", ".join(kv))
            lines.append("- " + " ".join(parts))
        lines.append("请按系统指令对每只股票输出研判，返回 JSON。")
        return "\n".join(lines)

    async def _call_llm(self, prompt: str, settings: Dict[str, Any]):
        """单次 chat 调用：优先设置指定模型，否则 analyst 默认客户端。"""
        from app.llm.providers import get_engine_clients, resolve_task_override_bundle
        from app.llm.retry import with_retry

        client = None
        model_name = settings.get("model")
        if model_name:
            try:
                bundle = await resolve_task_override_bundle(model_name)
                if bundle is not None:
                    client = bundle.primary
            except Exception as e:
                logger.warning("研判模型 %s 解析失败，回落 analyst 默认: %s",
                               model_name, e)
        if client is None:
            clients = await get_engine_clients()
            bundle = clients.get("analyst")
            if bundle is None:
                raise RuntimeError("未配置任何 LLM 模型（请先在设置页配置）")
            client = bundle.primary

        resp = await with_retry(
            lambda: client.chat(
                [Message(role=Role.USER, content=prompt)],
                system=settings["prompt"],
                tools=None,
                max_tokens=4000,
            ),
            max_retries=2,
        )
        text = resp.text() or ""
        usage = getattr(resp, "usage", None)
        tokens = None
        if usage is not None:
            tokens = (getattr(usage, "input_tokens", 0)
                      + getattr(usage, "output_tokens", 0)) or None
        return text, tokens

    @staticmethod
    def _parse_json_insights(text: str, symbols: List[str]) -> Dict[str, str]:
        """解析 LLM JSON 输出（容忍 ```json 围栏）；缺失 symbol 补提示文本。"""
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        payload = {}
        if m:
            try:
                data = json.loads(m.group(0))
                payload = data.get("insights", data)
            except json.JSONDecodeError:
                logger.warning("研判 JSON 解析失败，回退原文按行拆分")
        if not payload:
            # 降级：整段文本作为所有 symbol 的统一研判
            payload = {s: cleaned for s in symbols}
        return {s: str(payload.get(s, "（模型未返回该股研判）")) for s in symbols}
