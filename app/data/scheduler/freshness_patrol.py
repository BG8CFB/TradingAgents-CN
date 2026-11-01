"""数据新鲜度巡检与自动补数 — 行业标准的 catchup 兜底层。

设计对齐（均为公开的调度系统通行做法，属行业惯例而非合规硬要求）：
- Airflow 的 catchup：调度窗口因停机错过后，启动后自动补跑；
  APScheduler 无此能力（misfire_grace_time 过期即丢弃），本模块补上。
- dbt 的 freshness 检测：按域定义「数据应该多新」，巡检发现落后即告警/触发。
- 幂等增量重放：补数复用 BaseSyncJob 的增量语义（检查点 → fetch → upsert），
  重复执行无副作用，不需要精确的「漏了哪一天」推算。

触发路径（三道防线）：
1. 启动后延迟巡检：lifespan 注册 startup 任务，避开启动高峰；
2. 周期巡检：每 30 分钟对三市场做一次新鲜度评估（cron 之外的兜底网）；
3. 判定标准：域检查点日期落后于「收盘后应有的最新交易日」→ 落后即补。

与 cron 的分工：cron 管常规节奏（收盘后 N 分钟拉当日）；本模块只处理
「cron 错过/失败/停机」造成的落后，正常情况下零动作（检查点已是最新）。
"""

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Dict, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

# 巡检覆盖的域：调度 yaml 中有 cron 的同步域（market_quotes 按 demand 同步、
# news 高频自愈、factor_scores 是库内计算跟随行情，均不纳入巡检）
_PATROL_MARKET_DOMAINS: Dict[str, list] = {
    "CN": [
        "daily_quotes",
        "daily_indicators",
        "adj_factors",
        "money_flow",
        "financial_data",
        "basic_info",
        "trade_calendar",
        "margin_trading",
        "dragon_tiger",
        "block_trade",
    ],
    "HK": [
        "daily_quotes",
        "daily_indicators",
        "adj_factors",
        "financial_data",
        "basic_info",
        "trade_calendar",
        "southbound_holding",
        "corporate_actions",
    ],
    "US": [
        "daily_quotes",
        "daily_indicators",
        "adj_factors",
        "financial_data",
        "basic_info",
        "trade_calendar",
        "corporate_actions",
    ],
}

# 各域收盘后数据可用的等待窗（市场本地时间）：
# 收盘后源端整理需要时间，巡检判定「应有数据」的时点 = 收盘 + 该窗口。
# 缺省 90 分钟，行情类源通常 30~60 分钟内可用，留裕量避免巡检与 cron 抢跑。
_DOMAIN_READY_AFTER_CLOSE: Dict[str, int] = {
    "CN": {"default": 90, "daily_indicators": 120, "adj_factors": 150,
           "money_flow": 90, "financial_data": 360},
    "HK": {"default": 90},
    "US": {"default": 90, "daily_indicators": 120, "adj_factors": 120},
}

# 市场收盘时间（本地）与自然日容忍度：
# daily 类域按交易日判定；basic_info/calendar/财务等自然日域按天判定。
_MARKET_CLOSE_LOCAL = {"CN": 15, "HK": 16, "US": 16}
# 自然日域的容忍天数：落后超过该天数才补（每天全量同步一次足矣）
_CALENDAR_DAY_TOLERANCE = {"default": 1, "trade_calendar": 7, "financial_data": 2}

_patrol_lock = asyncio.Lock()
_last_patrol_result: Dict = {}


def _ready_after_close(market: str, domain: str) -> int:
    cfg = _DOMAIN_READY_AFTER_CLOSE.get(market, {})
    return cfg.get(domain, cfg.get("default", 90))


def _calendar_tolerance(domain: str) -> int:
    return _CALENDAR_DAY_TOLERANCE.get(domain, _CALENDAR_DAY_TOLERANCE["default"])


def _is_calendar_domain(domain: str) -> bool:
    """自然日域（无交易日语义）：basic_info / trade_calendar / financial_data。"""
    return domain in ("basic_info", "trade_calendar", "financial_data",
                      "corporate_actions", "connect_status")


async def _expected_trading_date(market: str, domain: str) -> Optional[date]:
    """计算「此刻源端应已具备数据」的最新交易日。

    从今天往回找第一个满足「交易日且已过收盘+就绪窗」的日期。
    今天是交易日但还没到就绪时点 → 昨个交易日；否则 → 今天。
    找不到日历（None）时返回 None，调用方按自然日逻辑兜底。
    """
    from app.data.core.market import get_market_timezone
    from app.data.core.domain import DataDomain

    if domain not in {d.value for d in DataDomain}:
        return None

    tz = get_market_timezone(market)
    now_local = datetime.now(tz)
    ready_minutes = _ready_after_close(market, domain)
    close_hour = _MARKET_CLOSE_LOCAL.get(market, 16)

    # 就绪时点（本地）：收盘 + 就绪窗；超过它当日数据才「应有」
    ready_dt = now_local.replace(
        hour=close_hour, minute=0, second=0, microsecond=0
    ) + timedelta(minutes=ready_minutes)

    from app.data.storage.mongo.repositories.trade_calendar_repo import TradeCalendarRepo
    from app.data.schema.base.markets import MARKET_META, MarketType

    meta = MARKET_META.get(MarketType(market))
    exchange = meta.exchanges[0] if meta and meta.exchanges else ""
    repo = TradeCalendarRepo()

    candidate = now_local.date()
    # 最多回看 40 天，覆盖最长节假日连休 + 巡检长期停摆
    for _ in range(40):
        is_open = await repo.is_trading_day(candidate.isoformat(), exchange, market)
        if is_open:
            if candidate == now_local.date() and now_local < ready_dt:
                # 今日数据尚未就绪，继续回看上一交易日
                candidate = candidate - timedelta(days=1)
                continue
            return candidate
        candidate = candidate - timedelta(days=1)
    return None


async def _checkpoint_date(market: str, domain: str) -> Optional[date]:
    """读取域的 scheduled 检查点日期；无检查点视为从未同步（落后）。"""
    from app.data.scheduler.checkpoint import CheckpointManager

    cp_date = await CheckpointManager().get_checkpoint(market, domain, "scheduled")
    if not cp_date:
        return None
    try:
        return date.fromisoformat(str(cp_date)[:10])
    except ValueError:
        return None


async def evaluate_domain(market: str, domain: str) -> Dict:
    """评估单域新鲜度，返回 {behind: bool, expected, checkpoint, reason}。

    判定规则：
    - 交易日域：检查点日期 < 应有交易日 → 落后（停机/失败漏跑）；
      检查点 ≥ 应有 → 正常（周末/节假日自然持平时不算落后）。
    - 自然日域：检查点距今天超过容忍天数 → 落后。
    - 无检查点：落后（从未同步，交给首次全量补齐）。
    """
    checkpoint = await _checkpoint_date(market, domain)

    if _is_calendar_domain(domain):
        tz_days = (date.today() - checkpoint).days if checkpoint else None
        tolerance = _calendar_tolerance(domain)
        behind = tz_days is None or tz_days > tolerance
        return {
            "behind": behind,
            "expected": None,
            "checkpoint": checkpoint.isoformat() if checkpoint else None,
            "reason": (f"calendar_days_behind={tz_days}" if tz_days is not None
                       else "no_checkpoint"),
        }

    expected = await _expected_trading_date(market, domain)
    if expected is None:
        # 无交易日历：无法判定，交给 cron 正常节奏
        return {"behind": False, "expected": None,
                "checkpoint": checkpoint.isoformat() if checkpoint else None,
                "reason": "no_calendar"}

    if checkpoint is None:
        return {"behind": True, "expected": expected.isoformat(),
                "checkpoint": None, "reason": "no_checkpoint"}

    behind = checkpoint < expected
    return {
        "behind": behind,
        "expected": expected.isoformat(),
        "checkpoint": checkpoint.isoformat(),
        "reason": ("checkpoint_behind_expected" if behind else "up_to_date"),
    }


async def run_patrol(trigger: str = "interval") -> Dict:
    """执行一次全市场新鲜度巡检；发现落后域则通过调度引擎补数。

    幂等：补数复用 BaseSyncJob 增量语义，重复触发无副作用。
    并发保护：engine.run_job_now 自带 already_running 幂等；巡检自身
    加锁防止重叠（APScheduler misfire 重放场景）。
    """
    if _patrol_lock.locked():
        logger.info("新鲜度巡检已在执行，跳过本次触发 (%s)", trigger)
        return {"status": "skipped", "reason": "patrol_running"}

    async with _patrol_lock:
        report: Dict = {"trigger": trigger, "checked": 0, "behind": [],
                        "compensated": [], "results": {}}
        engine = None
        try:
            # SchedulerEngine 是数据模块自有组件，直接取单例（不经 app.worker 转发）
            from app.data.scheduler.engine import SchedulerEngine

            engine = SchedulerEngine.get_instance()
        except Exception as e:
            logger.warning("巡检无法获取调度引擎: %s", e)

        # 先完成全部评估再补偿：评估只读检查点，快；
        # 补偿串行执行——多域并发会争抽数据源配额（如 Tushare
        # 500 次/分钟），打爆限流反而拖慢整体回补（对齐 Airflow
        # catchup 逐 run 串行回放的通行做法）
        pending: list = []
        for market, domains in _PATROL_MARKET_DOMAINS.items():
            for domain in domains:
                try:
                    verdict = await evaluate_domain(market, domain)
                except Exception as e:
                    logger.warning("巡检评估失败 %s/%s: %s", market, domain, e)
                    continue
                report["checked"] += 1
                report["results"][f"{market}:{domain}"] = verdict

                if not verdict.get("behind"):
                    continue
                report["behind"].append(f"{market}:{domain}")
                logger.info(
                    "巡检发现落后域 %s/%s: %s (checkpoint=%s expected=%s)",
                    market, domain, verdict.get("reason"),
                    verdict.get("checkpoint"), verdict.get("expected"),
                )
                if engine is not None:
                    pending.append((market, domain))

        for market, domain in pending:
            try:
                # trigger_job 阻塞等待该域补完（增量幂等，可与 cron 共存：
                # engine 侧 already_running 幂等防止同域并发）
                await engine.trigger_job(market, domain)
                report["compensated"].append(
                    {"task_id": f"{market}:{domain}", "domain": f"{market}:{domain}",
                     "status": "triggered"}
                )
            except Exception as e:
                logger.warning("巡检补数触发失败 %s/%s: %s", market, domain, e)
                report["compensated"].append(
                    {"task_id": f"{market}:{domain}", "domain": f"{market}:{domain}",
                     "status": "failed"}
                )

        report["summary"] = (
            f"checked={report['checked']} behind={len(report['behind'])} "
            f"compensated={len(report['compensated'])}"
        )
        if report["behind"]:
            logger.info("新鲜度巡检完成: %s", report["summary"])
        global _last_patrol_result
        _last_patrol_result = report
        return report


def get_last_patrol_result() -> Dict:
    """最近一次巡检结果（供状态端点/诊断读取）。"""
    return _last_patrol_result


async def patrol_loop():
    """周期巡检协程：每 PATROL_INTERVAL_MINUTES 分钟执行一次。

    通过 task_registry 注册（critical=False，shutdown 时 cancel）。
    """
    if not getattr(settings, "DATA_FRESHNESS_PATROL_ENABLED", True):
        logger.info("数据新鲜度巡检已通过配置禁用，循环退出")
        return
    interval = max(5, int(getattr(settings, "DATA_FRESHNESS_PATROL_MINUTES", 30)))
    logger.info("数据新鲜度巡检循环已启动（每 %d 分钟）", interval)
    while True:
        try:
            await run_patrol(trigger="interval")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("新鲜度巡检异常: %s", e, exc_info=True)
        await asyncio.sleep(interval * 60)


async def startup_patrol(delay_seconds: int = 120):
    """启动巡检：延迟执行一次，避开启动高峰（DB 连接/种子/爬虫冷启动）。

    场景：停机多日后重启（cron misfire 已丢弃），本次巡检发现落后并补齐，
    这正是用户「启动时检测到昨日数据未更新就自动补」的诉求。
    """
    try:
        await asyncio.sleep(delay_seconds)
        await run_patrol(trigger="startup")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error("启动巡检异常: %s", e, exc_info=True)
