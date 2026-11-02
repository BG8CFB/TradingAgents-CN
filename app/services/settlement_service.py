# data-access-exempt: 应用层集合（decision_settlements）；行情/日历/基本信息读取经 DataInterface
"""
决策结算记分卡服务：登记 → 定价 → 持有 → 结算 → 聚合。

业务口径（P0）：信号/置信度正源 = structured_summary（无 summarizer 回退 trader decision）；
入场 T+1 开盘、第 horizon_days 个交易日收盘结算、停牌顺延；一字板按板块幅差判 unfillable
（主板 ±10%/ST ±5%、创业板·科创板 ±20%、北交所 ±30%，HK/US 无涨跌停）；
错题由结算规则派生；channel=online 为默认聚合口径（双通道制衡）。详见各方法 docstring。

结算只用已收盘 session 的 bar：市场时区的当日 bar 可能来自盘中同步（手动同步/强刷/
新鲜度巡检补数），一律排除，到期日为当日时顺延到次日结算。
exit_date 兼作 resolution 语义（结果可知日）：后续记忆/回测注入教训时，以
exit_date <= as_of 为防前视门槛。
"""
import logging
import math
import statistics
from bisect import bisect_right
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.core.database import get_mongo_db
from app.core.horizons import horizon_days_of, max_wait_days
from app.data.core.index_universe import resolve_benchmark
from app.data.core.interface import DataInterface
from app.data.core.market import get_market_timezone
from app.models.settlement import (
    ConfidenceBucketOut,
    ScorecardOut,
    SettlementListOut,
    SettlementOut,
    SignalStatOut,
    HorizonStatOut,
    TrendPointOut,
)
from app.utils.timezone import now_tz

logger = logging.getLogger(__name__)

DEFAULT_HORIZON_DAYS = 7
_PRICE_EPS = 0.001

_MARKET_MAP = {"A股": "CN", "港股": "HK", "美股": "US", "CN": "CN", "HK": "HK", "US": "US"}
_SIGNAL_MAP = {
    "buy": "Buy", "买入": "Buy", "看多": "Buy",
    "sell": "Sell", "卖出": "Sell", "看空": "Sell",
    "hold": "Hold", "持有": "Hold", "观望": "Hold", "中性": "Hold",
}
_BOARD_LIMIT_PCT = {"主板": 10.0, "创业板": 20.0, "科创板": 20.0, "北交所": 30.0}
# summary 失败占位文案特征（兜底包不进结算样本）
_PLACEHOLDER_KEYWORDS = ("解析失败", "系统错误", "数据获取失败", "无法生成")
_CALIBRATION_BUCKETS = ("<60", "60-70", "70-80", "80+")


def normalize_signal(raw: Any) -> Optional[str]:
    """把 summary/trader 的信号归一为 Buy/Sell/Hold；无法识别返回 None。"""
    if not isinstance(raw, str):
        return None
    return _SIGNAL_MAP.get(raw.strip().lower())


def to_confidence(raw: Any) -> Optional[float]:
    """置信度归一为 0-100；接受 0-1 分数（trader decision 口径）或 0-100。"""
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if 0 < v <= 1:
        v *= 100
    return max(0.0, min(100.0, v))


def infer_board(symbol: str) -> str:
    """按 symbol 前缀推断板块（与 favorites_service._infer_board 同规则）。"""
    c = str(symbol).zfill(6)
    if c.startswith(("60", "00")):
        return "主板"
    if c.startswith("30"):
        return "创业板"
    if c.startswith("68"):
        return "科创板"
    if c.startswith(("4", "8", "92")):
        return "北交所"
    return "主板"


def board_limit_pct(board: Optional[str], is_st: bool) -> Optional[float]:
    """板块涨跌停幅度（%）。主板 ST 缩至 5%；未知板块/市场返回 None（无涨跌停）。"""
    pct = _BOARD_LIMIT_PCT.get(board or "")
    if pct is None:
        return None
    if is_st and board == "主板":
        return 5.0
    return pct


def is_limit_unfillable(
    open_: Optional[float],
    high: Optional[float],
    low: Optional[float],
    pre_close: Optional[float],
    signal: str,
    limit_pct: float,
) -> bool:
    """一字板判定：全天无波动（high == low）且开盘即处于封板价。"""
    if open_ is None or high is None or low is None or pre_close is None:
        return False
    if abs(high - low) > _PRICE_EPS:
        return False
    if signal == "Buy":
        limit_up = round(pre_close * (1 + limit_pct / 100), 2)
        return open_ >= limit_up - _PRICE_EPS
    if signal == "Sell":
        limit_down = round(pre_close * (1 - limit_pct / 100), 2)
        return open_ <= limit_down + _PRICE_EPS
    return False


def wilson_ci(k: int, n: int, z: float = 1.96) -> Optional[Dict[str, float]]:
    """命中率的 Wilson 置信区间（0-1）。"""
    if n <= 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return {"low": max(0.0, centre - half), "high": min(1.0, centre + half)}


class SettlementService:
    """决策结算记分卡服务（应用层集合 decision_settlements）。"""

    def __init__(self):
        self.collection = "decision_settlements"

    async def _ensure_indexes(self):
        try:
            db = get_mongo_db()
            coll = db[self.collection]
            await coll.create_index([("task_id", 1), ("channel", 1)], unique=True, name="idx_task_channel")
            await coll.create_index([("status", 1), ("decision_date", 1)], name="idx_status_date")
            await coll.create_index([("channel", 1), ("status", 1), ("signal", 1)], name="idx_channel_status_signal")
            await coll.create_index([("symbol", 1), ("decision_date", -1)], name="idx_symbol_date")
        except Exception as e:
            logger.warning(f"decision_settlements 索引创建失败(忽略): {e}")

    # ── 登记 ──

    async def register_from_result(self, task_id: str, user_id: Any, result: Dict[str, Any]) -> Optional[str]:
        """分析完成后登记结算记录；不合格决策（兜底包/无信号/无标的）静默跳过。

        幂等：同 task_id + channel 只登记一次（$setOnInsert）。
        """
        try:
            summary = result.get("structured_summary")
            if not isinstance(summary, dict):
                summary = {}
            signal = normalize_signal(summary.get("final_signal"))
            confidence = to_confidence(summary.get("model_confidence"))
            signal_source = "summary"

            if signal is None:
                decision = result.get("decision")
                if isinstance(decision, dict):
                    signal = normalize_signal(decision.get("action") or decision.get("signal"))
                    if signal is not None:
                        confidence = to_confidence(decision.get("confidence"))
                        signal_source = "decision"

            if signal is None:
                logger.debug(f"结算登记跳过：无有效信号 task={task_id}")
                return None

            # 兜底包过滤：summary 失败占位的签名（Hold + 置信度 0/缺失）或失败文案
            if signal_source == "summary":
                if signal == "Hold" and confidence in (None, 0.0):
                    return None
                fail_text = str(summary.get("analysis_summary") or "")
                if any(kw in fail_text for kw in _PLACEHOLDER_KEYWORDS):
                    return None

            symbol = str(result.get("stock_symbol") or result.get("stock_code") or "").strip()
            if not symbol:
                logger.debug(f"结算登记跳过：无标的 task={task_id}")
                return None

            market = _MARKET_MAP.get(str(result.get("market_type") or "A股").strip())
            if market is None:
                logger.debug(f"结算登记跳过：未知市场 task={task_id}")
                return None

            analysis_date = result.get("analysis_date")
            if not isinstance(analysis_date, str) or len(analysis_date) < 10:
                analysis_date = now_tz().strftime("%Y-%m-%d")

            doc = {
                "task_id": task_id,
                "user_id": str(user_id),
                "symbol": symbol,
                "stock_name": result.get("stock_name"),
                "market": market,
                "decision_date": analysis_date[:10],
                "signal": signal,
                "stated_confidence": confidence,
                "key_prices": summary.get("key_indicators") or {},
                # 期限贯通：result 内存值（None=旧任务/未指定 → 默认 7 交易日）
                "horizon_days": horizon_days_of(result.get("horizon")) or DEFAULT_HORIZON_DAYS,
                "channel": "online",
                "status": "pending",
                "board": infer_board(symbol),
                "signal_source": signal_source,
                # 反思输入自包含（避免结算时反查 analysis_reports；decision 源为空串，
                # 反思 prompt 允许基于数字直接复盘）
                "decision_summary": str(summary.get("analysis_summary") or "")[:600],
                "reflection_status": None,
                "reflected_at": None,
                "reflection_retry_count": 0,
                "entry_date": None,
                "entry_price": None,
                "exit_date": None,
                "exit_price": None,
                "return_pct": None,
                "actual_direction": None,
                "direction_hit": None,
                "benchmark_symbol": None,
                "bench_entry": None,
                "bench_exit": None,
                "benchmark_return_pct": None,
                "alpha_pct": None,
                "direction_hit_vs_benchmark": None,
                "error_type": None,
                "failure_reason": None,
                "created_at": now_tz(),
                "settled_at": None,
            }
            await self._ensure_indexes()
            db = get_mongo_db()
            await db[self.collection].update_one(
                {"task_id": task_id, "channel": "online"},
                {"$setOnInsert": doc},
                upsert=True,
            )
            return task_id
        except Exception:
            logger.warning(f"结算登记失败(忽略) task={task_id}", exc_info=True)
            return None

    # ── 结算 ──

    async def settle_due(self, batch_size: int = 500) -> Dict[str, int]:
        """结算所有到期 pending 记录（每日 job 与回填共用）。"""
        await self._ensure_indexes()
        db = get_mongo_db()
        stats = {"settled": 0, "unfillable": 0, "pending": 0}
        flags_cache: Dict[Tuple[str, str], Tuple[bool, str]] = {}
        bench_cache: Dict[Tuple[str, str, str, str], Dict[str, Dict]] = {}
        cursor = (
            db[self.collection]
            .find({"status": "pending"})
            .sort("decision_date", 1)
            .limit(batch_size)
        )
        async for rec in cursor:
            try:
                outcome = await self._settle_record(rec, flags_cache, bench_cache)
                stats[outcome] = stats.get(outcome, 0) + 1
            except Exception:
                logger.warning(f"结算单条失败(保留 pending) task={rec.get('task_id')}", exc_info=True)
                stats["pending"] += 1
        logger.info(f"决策结算批次完成: {stats}")
        return stats

    async def _trading_days(self, market: str, start: str, end: str) -> List[str]:
        resp = await DataInterface.get_instance().read(
            market, "trade_calendar", None, start_date=start, end_date=end
        )
        rows = (resp or {}).get("data") or []
        return sorted({r["cal_date"] for r in rows if r.get("is_open") and r.get("cal_date")})

    async def _quotes(self, market: str, symbol: str, start: str, end: str) -> Dict[str, Dict]:
        resp = await DataInterface.get_instance().read(
            market, "daily_quotes", symbol, start_date=start, end_date=end
        )
        rows = (resp or {}).get("data") or []
        return {r["trade_date"]: r for r in rows if r.get("trade_date")}

    async def _symbol_flags(
        self, market: str, symbol: str, board_hint: Optional[str], cache: Dict
    ) -> Tuple[bool, str]:
        """(is_st, board)：ST 与板块以结算时 basic_info 为准（名称含 ST；market_board 优先）。"""
        key = (market, symbol)
        if key in cache:
            return cache[key]
        is_st, board = False, board_hint or infer_board(symbol)
        try:
            resp = await DataInterface.get_instance().read(market, "basic_info", symbol)
            info = (resp or {}).get("data") or None
            if isinstance(info, dict):
                name = str(info.get("name") or "")
                is_st = "ST" in name.upper()
                board = info.get("market_board") or board
        except Exception as e:
            logger.debug(f"basic_info 读取失败(用前缀推断) {symbol}: {e}")
        cache[key] = (is_st, board)
        return is_st, board

    async def _mark_unfillable(
        self, rec: Dict, reason: str, entry_day: Optional[str] = None, entry_price: Optional[float] = None
    ) -> str:
        db = get_mongo_db()
        update: Dict[str, Any] = {
            "status": "unfillable",
            "error_type": "unfillable",
            "failure_reason": reason,
            "settled_at": now_tz(),
        }
        if entry_day:
            update["entry_date"] = entry_day
        if entry_price is not None:
            update["entry_price"] = entry_price
        await db[self.collection].update_one({"_id": rec["_id"]}, {"$set": update})
        return "unfillable"

    async def _benchmark_series(
        self, market: str, bench_symbol: str, start: str, end: str, cache: Dict
    ) -> Dict[str, Dict]:
        """指数日线序列 {trade_date: bar}，跨记录缓存（同窗口只读一次）。"""
        key = (market, bench_symbol, start, end)
        if key in cache:
            return cache[key]
        resp = await DataInterface.get_instance().read(
            market, "index_quotes", bench_symbol, start_date=start, end_date=end
        )
        rows = (resp or {}).get("data") or []
        series = {r["trade_date"]: r for r in rows if r.get("trade_date")}
        cache[key] = series
        return series

    def _asof_bar(self, series: Dict[str, Dict], on_date: str) -> Optional[Dict]:
        """>= 系列中 <= on_date 的最近一个 bar（基准 asof 定价）。"""
        days = sorted(series.keys())
        idx = bisect_right(days, on_date)
        if idx == 0:
            return None
        return series[days[idx - 1]]

    async def _compute_benchmark(
        self,
        market: str,
        board: Optional[str],
        signal: str,
        entry_day: str,
        exit_day: str,
        return_pct: float,
        bench_cache: Dict,
    ) -> Dict[str, Any]:
        """基准对比六字段。基准不可得时六字段全 None（benchmark_symbol 也不写，
        保持「null=未算出基准」语义；backfill_benchmarks 以 benchmark_symbol
        缺失为线索补算，算不出时落 symbol 标记已尝试，防重复匹配）——
        主结果（return_pct/settled）不受基准缺失影响。"""
        fields: Dict[str, Any] = {
            "benchmark_symbol": None,
            "bench_entry": None,
            "bench_exit": None,
            "benchmark_return_pct": None,
            "alpha_pct": None,
            "direction_hit_vs_benchmark": None,
        }
        bench_symbol = resolve_benchmark(market, board if market == "CN" else None)
        if not bench_symbol:
            return fields
        # 入场端留 30 天余量：入场日指数缺 bar 时回退前收
        start = (date.fromisoformat(entry_day) - timedelta(days=30)).isoformat()
        try:
            series = await self._benchmark_series(market, bench_symbol, start, exit_day, bench_cache)
            entry_bar = self._asof_bar(series, entry_day)
            exit_bar = self._asof_bar(series, exit_day)
            if entry_bar is None or exit_bar is None:
                return fields
            bench_entry = entry_bar.get("open")
            if bench_entry is None:
                bench_entry = entry_bar.get("close")
            bench_exit = exit_bar.get("close")
            if bench_exit is None:
                bench_exit = exit_bar.get("pre_close")
            if bench_entry is None or bench_exit is None or float(bench_entry) == 0:
                return fields
            bench_entry, bench_exit = float(bench_entry), float(bench_exit)
            fields["benchmark_symbol"] = bench_symbol
            fields["bench_entry"] = bench_entry
            fields["bench_exit"] = bench_exit
            bench_ret = round((bench_exit - bench_entry) / bench_entry * 100, 2)
            fields["benchmark_return_pct"] = bench_ret
            alpha = round(return_pct - bench_ret, 2)
            fields["alpha_pct"] = alpha
            if signal == "Buy":
                fields["direction_hit_vs_benchmark"] = alpha > 0
            elif signal == "Sell":
                fields["direction_hit_vs_benchmark"] = alpha < 0
        except Exception as e:
            logger.debug(f"基准计算失败(降级 null) {bench_symbol}: {e}")
        return fields

    async def _settle_record(self, rec: Dict, flags_cache: Dict, bench_cache: Dict) -> str:
        market, symbol = rec["market"], rec["symbol"]
        decision_date = rec["decision_date"]
        horizon = rec.get("horizon_days") or DEFAULT_HORIZON_DAYS
        today = now_tz().strftime("%Y-%m-%d")
        cap_date = (
            date.fromisoformat(decision_date) + timedelta(days=max_wait_days(horizon))
        ).isoformat()
        # 当日（市场时区）bar 可能是盘中同步的半日行情，只读已收盘 session
        market_today = datetime.now(get_market_timezone(market)).strftime("%Y-%m-%d")
        bar_end = (date.fromisoformat(market_today) - timedelta(days=1)).isoformat()
        window_end = min(today, cap_date, bar_end)

        tdays = await self._trading_days(market, decision_date, window_end)
        after = [d for d in tdays if d > decision_date]
        if not after:
            if today >= cap_date:
                return await self._mark_unfillable(rec, "长期停牌或交易日历缺失")
            return "pending"

        quotes = await self._quotes(market, symbol, after[0], window_end)
        if not quotes:
            if today >= cap_date:
                return await self._mark_unfillable(rec, "长期停牌或行情数据缺失")
            return "pending"

        # 板块上移到入场判定前：一字板与基准映射都需要（flags_cache 去重 IO）
        is_st, board = False, rec.get("board")
        if market == "CN":
            is_st, board = await self._symbol_flags(market, symbol, rec.get("board"), flags_cache)

        # 入场：决策日后第 1 个交易日，停牌顺延到下一个有行情的交易日
        entry_idx = next((i for i, d in enumerate(after) if d in quotes), None)
        if entry_idx is None:
            if today >= cap_date:
                return await self._mark_unfillable(rec, "长期停牌")
            return "pending"
        entry_day = after[entry_idx]
        entry_quote = quotes[entry_day]

        # 一字板判定（仅 CN 且非 Hold；HK/US 无涨跌停）
        if market == "CN" and rec["signal"] != "Hold":
            limit_pct = board_limit_pct(board, is_st)
            if limit_pct is not None and is_limit_unfillable(
                entry_quote.get("open"),
                entry_quote.get("high"),
                entry_quote.get("low"),
                entry_quote.get("pre_close"),
                rec["signal"],
                limit_pct,
            ):
                reason = "一字涨停无法买入" if rec["signal"] == "Buy" else "一字跌停无法卖出"
                return await self._mark_unfillable(
                    rec, reason, entry_day=entry_day, entry_price=entry_quote.get("open")
                )

        # 出场：自决策日起第 horizon 个交易日（含入场日），停牌顺延
        exit_idx = entry_idx + horizon - 1
        if exit_idx >= len(after):
            if today >= cap_date:
                return await self._mark_unfillable(rec, "持有期内长期停牌")
            return "pending"
        exit_day = next((d for d in after[exit_idx:] if d in quotes), None)
        if exit_day is None:
            if today >= cap_date:
                return await self._mark_unfillable(rec, "持有期内长期停牌")
            return "pending"

        entry_price = float(entry_quote["open"])
        exit_price = float(quotes[exit_day]["close"])
        return_pct = round((exit_price - entry_price) / entry_price * 100, 2)
        if return_pct > 0:
            direction = "up"
        elif return_pct < 0:
            direction = "down"
        else:
            direction = "flat"

        signal = rec["signal"]
        direction_hit = None
        if signal == "Buy":
            direction_hit = direction == "up"
        elif signal == "Sell":
            direction_hit = direction == "down"

        bench_fields = await self._compute_benchmark(
            market, board, signal, entry_day, exit_day, return_pct, bench_cache
        )

        db = get_mongo_db()
        await db[self.collection].update_one(
            {"_id": rec["_id"]},
            {
                "$set": {
                    "status": "settled",
                    "entry_date": entry_day,
                    "entry_price": entry_price,
                    "exit_date": exit_day,
                    "exit_price": exit_price,
                    "return_pct": return_pct,
                    "actual_direction": direction,
                    "direction_hit": direction_hit,
                    **bench_fields,
                    "error_type": "direction_wrong" if direction_hit is False else None,
                    "settled_at": now_tz(),
                }
            },
        )
        return "settled"

    async def backfill_benchmarks(self, batch_size: int = 2000) -> int:
        """存量 settled 记录补基准字段（幂等，不重定价股票腿）。

        匹配 benchmark_symbol 缺失/为 null 且已有入场出场日期的记录；
        基准数据不可得时仍写入 benchmark_symbol（防止每轮重复匹配）。
        """
        await self._ensure_indexes()
        db = get_mongo_db()
        bench_cache: Dict = {}
        updated = 0
        cursor = (
            db[self.collection]
            .find(
                {
                    "status": "settled",
                    "benchmark_symbol": None,
                    "entry_date": {"$ne": None},
                    "exit_date": {"$ne": None},
                }
            )
            .sort("settled_at", 1)
            .limit(batch_size)
        )
        async for rec in cursor:
            try:
                bench_fields = await self._compute_benchmark(
                    rec["market"],
                    rec.get("board"),
                    rec.get("signal") or "Hold",
                    rec["entry_date"],
                    rec["exit_date"],
                    rec.get("return_pct") or 0.0,
                    bench_cache,
                )
                if bench_fields.get("alpha_pct") is None:
                    # 算不出基准价：只落 symbol 标记已尝试（价格字段保持 null），
                    # 防止下轮回填重复匹配同一批记录
                    attempted = resolve_benchmark(
                        rec["market"], rec.get("board") if rec["market"] == "CN" else None
                    )
                    bench_fields = {"benchmark_symbol": attempted} if attempted else {}
                if bench_fields:
                    await db[self.collection].update_one({"_id": rec["_id"]}, {"$set": bench_fields})
                updated += 1
            except Exception:
                logger.warning(f"基准回填单条失败(跳过) task={rec.get('task_id')}", exc_info=True)
        logger.info(f"基准回填完成: {updated} 条")
        return updated

    # ── 结算反思（记忆闭环写路径）──

    async def reflect_on_settlements(
        self, limit: int = 100, reflector_factory=None
    ) -> Dict[str, int]:
        """对已结算未反思的记录批量生成教训并写入 trader_memory。

        settle_due 之后的独立 pass（不内联进 _settle_record：结算保持纯数据
        路径可测，反思的 LLM 时延与失败不污染结算统计）。

        - 只反思 Buy/Sell（Hold 无对错可总结）
        - reflection_status: None/failed → 待处理（$ne "done" 兼容存量记录），
          done → 跳过；retry_count >= 3 不再重试（防 failed 死循环刷 LLM 调用）
        - 教训写入带 metadata（decision_date / resolution_date=exit_date / symbol /
          signal / user_id），读侧 fetch_memory_brief(as_of) 按 resolution_date
          防前视（历史日期分析看不到当时未揭晓的教训）
        - 反思失败不回滚结算，只置 failed

        Args:
            limit: 单批上限（每条一次廉价 LLM 调用，夜间 job 分钟级）
            reflector_factory: 返回 Reflector 的零参工厂（测试注入用；
                默认 debate 档客户端）
        """
        from app.engine.agents.utils.memory import FinancialSituationMemory
        from app.engine.default_config import DEFAULT_CONFIG

        db = get_mongo_db()
        stats = {"reflected": 0, "failed": 0}
        query = {
            "status": "settled",
            "signal": {"$in": ["Buy", "Sell"]},
            "reflection_status": {"$ne": "done"},
            "$or": [
                {"reflection_retry_count": {"$lt": 3}},
                {"reflection_retry_count": {"$exists": False}},
            ],
        }
        cursor = (
            db[self.collection]
            .find(query)
            .sort("settled_at", 1)
            .limit(limit)
        )
        docs = await cursor.to_list(length=limit)
        if not docs:
            return stats

        factory = reflector_factory or _default_reflector_factory()
        reflector = factory()
        # trader_memory 槽与运行时注入点对称（stage_2/trader.py 等六处检索消费）；
        # ChromaDBManager 单例防并发冲突，构造廉价
        memory = FinancialSituationMemory("trader_memory", dict(DEFAULT_CONFIG))

        for rec in docs:
            # situation 文本含自然语域摘要：纯数字模板在 embedding 空间检索失灵
            brief = (
                f"[{rec.get('decision_date')}] {rec.get('stock_name') or ''}({rec.get('symbol')})"
                f"【{rec.get('signal')}·置信度{rec.get('stated_confidence')}】 "
                f"{(rec.get('decision_summary') or '')[:400]}"
            )
            outcome = {
                "return_pct": rec.get("return_pct"),
                "benchmark_symbol": rec.get("benchmark_symbol"),
                "benchmark_return_pct": rec.get("benchmark_return_pct"),
                "alpha_pct": rec.get("alpha_pct"),
                "horizon_days": rec.get("horizon_days") or DEFAULT_HORIZON_DAYS,
            }
            try:
                lesson = await reflector.reflect_on_outcome(brief, outcome)
            except Exception:
                logger.warning(f"结果反思异常 task={rec.get('task_id')}", exc_info=True)
                lesson = None

            if not lesson:
                await db[self.collection].update_one(
                    {"_id": rec["_id"]},
                    {"$set": {"reflection_status": "failed"}, "$inc": {"reflection_retry_count": 1}},
                )
                stats["failed"] += 1
                continue

            try:
                memory.add_situations(
                    [(brief, lesson)],
                    metadata_list=[
                        {
                            "decision_date": rec.get("decision_date"),
                            "resolution_date": rec.get("exit_date"),
                            "symbol": rec.get("symbol"),
                            "signal": rec.get("signal"),
                            "user_id": rec.get("user_id"),
                        }
                    ],
                )
            except Exception:
                logger.warning(f"教训写入记忆失败 task={rec.get('task_id')}", exc_info=True)
                await db[self.collection].update_one(
                    {"_id": rec["_id"]},
                    {"$set": {"reflection_status": "failed"}, "$inc": {"reflection_retry_count": 1}},
                )
                stats["failed"] += 1
                continue

            await db[self.collection].update_one(
                {"_id": rec["_id"]},
                {"$set": {"reflection_status": "done", "reflected_at": now_tz()}},
            )
            stats["reflected"] += 1

        logger.info(f"结算反思批次完成: {stats}")
        return stats

    # ── 聚合与查询 ──

    async def get_scorecard(
        self,
        channel: str = "online",
        symbol: Optional[str] = None,
        months: int = 12,
        horizon: Optional[str] = None,
    ) -> ScorecardOut:
        await self._ensure_indexes()
        db = get_mongo_db()
        base: Dict[str, Any] = {}
        if channel != "all":
            base["channel"] = channel
        if symbol:
            base["symbol"] = symbol.strip()
        if horizon:
            # 按档过滤（short/mid/long → 7/20/60；非法档忽略走全量）
            hd = horizon_days_of(horizon)
            if hd:
                base["horizon_days"] = hd
        window_start = (now_tz().date() - timedelta(days=30 * months)).isoformat()
        scoped = {**base, "decision_date": {"$gte": window_start}}

        facet = {
            "counts": [
                {"$group": {"_id": {"status": "$status", "signal": "$signal"}, "n": {"$sum": 1}}}
            ],
            "hit": [
                {"$match": {"status": "settled", "signal": {"$in": ["Buy", "Sell"]}}},
                {
                    "$group": {
                        "_id": None,
                        "n": {"$sum": 1},
                        "hits": {"$sum": {"$cond": ["$direction_hit", 1, 0]}},
                        "rets": {"$push": "$return_pct"},
                        "alphas": {"$push": "$alpha_pct"},
                        "bench_hits": {"$sum": {"$cond": ["$direction_hit_vs_benchmark", 1, 0]}},
                        "alpha_n": {"$sum": {"$cond": [{"$ne": ["$alpha_pct", None]}, 1, 0]}},
                    }
                },
            ],
            "calibration": [
                {
                    "$match": {
                        "status": "settled",
                        "signal": {"$in": ["Buy", "Sell"]},
                        "stated_confidence": {"$ne": None},
                    }
                },
                {
                    "$addFields": {
                        "bucket": {
                            "$switch": {
                                "branches": [
                                    {"case": {"$lt": ["$stated_confidence", 60]}, "then": "<60"},
                                    {"case": {"$lt": ["$stated_confidence", 70]}, "then": "60-70"},
                                    {"case": {"$lt": ["$stated_confidence", 80]}, "then": "70-80"},
                                ],
                                "default": "80+",
                            }
                        }
                    }
                },
                {
                    "$group": {
                        "_id": "$bucket",
                        "n": {"$sum": 1},
                        "hits": {"$sum": {"$cond": ["$direction_hit", 1, 0]}},
                        "avg_conf": {"$avg": "$stated_confidence"},
                    }
                },
            ],
            "trend": [
                {"$match": {"status": "settled", "signal": {"$in": ["Buy", "Sell"]}}},
                {
                    "$group": {
                        "_id": {"$substrCP": ["$decision_date", 0, 7]},
                        "n": {"$sum": 1},
                        "hits": {"$sum": {"$cond": ["$direction_hit", 1, 0]}},
                        "avg_ret": {"$avg": "$return_pct"},
                        "avg_alpha": {"$avg": "$alpha_pct"},
                    }
                },
                {"$sort": {"_id": 1}},
            ],
            "by_signal": [
                {"$match": {"status": "settled"}},
                {
                    "$group": {
                        "_id": "$signal",
                        "n": {"$sum": 1},
                        "hits": {"$sum": {"$cond": ["$direction_hit", 1, 0]}},
                        "avg_ret": {"$avg": "$return_pct"},
                        "avg_alpha": {"$avg": "$alpha_pct"},
                    }
                },
            ],
            # 分期限统计：全状态分组（pending 只计数不阅卷——长线决策大量时间
            # 处于 pending，与已结算命中率分开呈现；对齐 ai-hedge-fund 记分卡口径）
            "by_horizon": [
                {
                    "$group": {
                        "_id": "$horizon_days",
                        "n": {"$sum": 1},
                        "pending": {"$sum": {"$cond": [{"$eq": ["$status", "pending"]}, 1, 0]}},
                        "settled": {"$sum": {"$cond": [{"$eq": ["$status", "settled"]}, 1, 0]}},
                        "hits": {"$sum": {"$cond": ["$direction_hit", 1, 0]}},
                        "avg_ret": {"$avg": "$return_pct"},
                    }
                },
                {"$sort": {"_id": 1}},
            ],
        }
        rows = await db[self.collection].aggregate([{"$match": scoped}, {"$facet": facet}]).to_list(1)
        row = rows[0] if rows else {}

        total_registered = settled_non_hold = pending = unfillable = hold = 0
        for c in row.get("counts") or []:
            key, n = c["_id"], c["n"]
            total_registered += n
            # Hold 口径：全部状态的 Hold 决策（登记但不计命中率），不止已结算
            if key.get("signal") == "Hold":
                hold += n
            if key.get("status") == "pending":
                pending += n
            elif key.get("status") == "unfillable":
                unfillable += n
            elif key.get("status") == "settled" and key.get("signal") != "Hold":
                settled_non_hold += n

        out = ScorecardOut(channel=channel)
        out.total_registered = total_registered
        out.settled_count = settled_non_hold
        out.pending_count = pending
        out.unfillable_count = unfillable
        out.hold_count = hold

        hit_rows = row.get("hit") or []
        if hit_rows:
            h = hit_rows[0]
            n = h["n"]
            out.hit_rate = round(h["hits"] / n, 4) if n else None
            out.hit_ci = wilson_ci(h["hits"], n)
            rets = [r for r in (h.get("rets") or []) if isinstance(r, (int, float))]
            if rets:
                out.avg_return_pct = round(sum(rets) / len(rets), 2)
                out.median_return_pct = round(statistics.median(rets), 2)
            # alpha 统计：仅基准可得样本（与命中率分母不同，样本数单独透出）
            alphas = [a for a in (h.get("alphas") or []) if isinstance(a, (int, float))]
            alpha_n = h.get("alpha_n") or len(alphas)
            if alphas:
                out.avg_alpha_pct = round(sum(alphas) / len(alphas), 2)
                out.median_alpha_pct = round(statistics.median(alphas), 2)
            out.alpha_count = alpha_n
            if alpha_n:
                out.benchmark_hit_rate = round((h.get("bench_hits") or 0) / alpha_n, 4)

        calib_map = {c["_id"]: c for c in row.get("calibration") or []}
        out.calibration = [
            ConfidenceBucketOut(
                bucket=b,
                count=calib_map[b]["n"] if b in calib_map else 0,
                avg_confidence=round(calib_map[b]["avg_conf"], 1) if b in calib_map else None,
                hit_rate=round(calib_map[b]["hits"] / calib_map[b]["n"], 4)
                if b in calib_map and calib_map[b]["n"]
                else None,
            )
            for b in _CALIBRATION_BUCKETS
        ]

        out.trend = [
            TrendPointOut(
                month=t["_id"],
                count=t["n"],
                hit_rate=round(t["hits"] / t["n"], 4) if t["n"] else None,
                ci_low=(wilson_ci(t["hits"], t["n"]) or {}).get("low"),
                ci_high=(wilson_ci(t["hits"], t["n"]) or {}).get("high"),
                avg_return_pct=round(t["avg_ret"], 2) if t.get("avg_ret") is not None else None,
                avg_alpha_pct=round(t["avg_alpha"], 2) if t.get("avg_alpha") is not None else None,
            )
            for t in row.get("trend") or []
        ]

        out.by_signal = [
            SignalStatOut(
                signal=s["_id"],
                count=s["n"],
                hit_rate=round(s["hits"] / s["n"], 4) if s["n"] and s["_id"] != "Hold" else None,
                avg_return_pct=round(s["avg_ret"], 2) if s.get("avg_ret") is not None else None,
                avg_alpha_pct=round(s["avg_alpha"], 2) if s.get("avg_alpha") is not None else None,
            )
            for s in row.get("by_signal") or []
        ]

        out.by_horizon = [
            HorizonStatOut(
                horizon_days=h["_id"] or DEFAULT_HORIZON_DAYS,
                count=h["n"],
                pending=h["pending"],
                hit_rate=round(h["hits"] / h["settled"], 4) if h.get("settled") else None,
                avg_return_pct=round(h["avg_ret"], 2) if h.get("avg_ret") is not None else None,
            )
            for h in row.get("by_horizon") or []
        ]

        out.unfillable_ratio = round(unfillable / total_registered, 4) if total_registered else None
        return out

    async def list_records(
        self,
        *,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
        signal: Optional[str] = None,
        error_type: Optional[str] = None,
        channel: Optional[str] = None,
        horizon_days: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> SettlementListOut:
        db = get_mongo_db()
        q: Dict[str, Any] = {}
        if symbol:
            q["symbol"] = symbol.strip()
        if status:
            q["status"] = status
        if signal:
            q["signal"] = signal
        if error_type:
            q["error_type"] = error_type
        if channel:
            q["channel"] = channel
        if horizon_days:
            q["horizon_days"] = horizon_days
        date_range: Dict[str, str] = {}
        if start_date:
            date_range["$gte"] = start_date
        if end_date:
            date_range["$lte"] = end_date
        if date_range:
            q["decision_date"] = date_range

        total = await db[self.collection].count_documents(q)
        cursor = (
            db[self.collection]
            .find(q)
            .sort("decision_date", -1)
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        docs = await cursor.to_list(length=page_size)
        items = [SettlementOut.model_validate(d).model_dump() for d in docs]
        return SettlementListOut(items=items, total=total, page=page, page_size=page_size)

    async def get_by_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        db = get_mongo_db()
        doc = await db[self.collection].find_one(
            {"task_id": task_id}, sort=[("created_at", -1)]
        )
        if not doc:
            return None
        out = SettlementOut.model_validate(doc).model_dump()
        if out.get("status") == "pending":
            out["days_remaining"] = await self._days_remaining(out)
        return out

    async def _days_remaining(self, doc: Dict[str, Any]) -> Optional[int]:
        """待结算剩余交易日（按计划出场日计，含停牌顺延前的原计划）。"""
        try:
            horizon = doc.get("horizon_days") or DEFAULT_HORIZON_DAYS
            decision_date = doc["decision_date"]
            # 与 _settle_record 的 unfillable cap 同源（max_wait_days），防判定错位
            end = (
                date.fromisoformat(decision_date) + timedelta(days=max_wait_days(horizon))
            ).isoformat()
            tdays = await self._trading_days(doc["market"], decision_date, end)
            after = [d for d in tdays if d > decision_date]
            if len(after) < horizon:
                return None
            planned = after[horizon - 1]
            today = now_tz().strftime("%Y-%m-%d")
            if planned <= today:
                return 0
            return sum(1 for d in after if today < d <= planned)
        except Exception as e:
            # 静默返回 None 会让该决策的剩余天数不可知、可能永不结算且无从排查
            logger.warning(f"计算剩余交易日失败（决策 {decision_date}）: {e}", exc_info=True)
            return None


_settlement_service: Optional[SettlementService] = None


def get_settlement_service() -> SettlementService:
    global _settlement_service
    if _settlement_service is None:
        _settlement_service = SettlementService()
    return _settlement_service


def _default_reflector_factory():
    """默认反思器：debate 档客户端（后处理惯例，与 Summarizer/SignalProcessor 同档）。"""

    def _build():
        from app.engine.agents.postprocess.reflector import Reflector
        from app.llm.providers import get_engine_clients

        clients = get_engine_clients()
        client = clients.get("debate")
        if client is None:
            raise RuntimeError("无可用 debate 档 LLM 客户端，跳过结算反思")
        return Reflector(client)

    return _build


async def run_settlement_job() -> None:
    """每日结算 job 体（APScheduler 调度，收盘数据入库后执行）。"""
    try:
        stats = await get_settlement_service().settle_due()
        if any(stats.values()):
            logger.info(f"每日决策结算完成: {stats}")
    except Exception:
        logger.error("每日决策结算 job 失败", exc_info=True)
    # 结算后反思 pass（独立开关；失败只 WARNING，不影响结算结果）
    from app.core.config import settings

    if getattr(settings, "SETTLEMENT_REFLECTION_ENABLED", True):
        try:
            rstats = await get_settlement_service().reflect_on_settlements()
            if any(rstats.values()):
                logger.info(f"结算反思 pass 完成: {rstats}")
        except Exception:
            logger.warning("结算反思 pass 失败(忽略)", exc_info=True)
