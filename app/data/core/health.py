"""域健康判定模型 — 数据可观测性三支柱（freshness / volume / 运行健康）。

设计原则（对应业界状态页规范 + 数据可观测性五支柱）：
- 健康判定权收归数据层，路由/前端只做渲染
- "没有数据"（no_data）和"没有信号"（unknown）永远不能显示为健康
- 状态渐变分级：healthy / degraded / unhealthy / stale / no_data / unknown

判定输入：
- 数据存在性（volume）：record_count、coverage
- 新鲜度（freshness）：last_sync_time（sync_checkpoints 优先，域统计 updated_at 兜底）
  vs 新鲜度预算（freshness_rules.yaml + data_health.yaml）
- 源运行健康：circuit_state / success_rate_1h / avg_latency_1h / total_calls
- 监控可用性：健康数据本身是否可信（监控失联 → unknown）

纯逻辑模块（无 I/O），由 DataInterface.get_domain_health 聚合输入后调用，
单测见 tests/data/test_domain_health.py。
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "data_health.yaml"
_FRESHNESS_PATH = Path(__file__).parent.parent / "config" / "freshness_rules.yaml"

# 健康快照超过该小时数且内存无热数据 → 视为无信号（修"stale Mongo 快照永远优先"）
HEALTH_SNAPSHOT_MAX_AGE_HOURS = 2.0


def _load_yaml(path: Path) -> Dict:
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as exc:
        logger.warning(f"加载 {path.name} 失败: {exc}")
        return {}


class DomainHealthCalculator:
    """域健康判定器（无状态，可复用）。"""

    def __init__(self, config: Optional[Dict] = None):
        self._config = config or _load_yaml(_CONFIG_PATH)
        self._freshness_rules = _load_yaml(_FRESHNESS_PATH)

    # ── 配置读取 ─────────────────────────────────────────

    def _defaults(self) -> Dict:
        return self._config.get("defaults", {})

    def _is_coverage_exempt(self, domain: str) -> bool:
        return domain in (self._config.get("coverage_exempt_domains") or [])

    def _stale_budget_hours(self, market: str, domain: str) -> Optional[float]:
        """域的新鲜度预算（小时）。

        time_window 类直接用 freshness_rules 的 threshold；
        trading_day_after_close 类用 data_health 的 stale_after_hours（自然日预算）。
        """
        market_cfg = self._freshness_rules.get(market, {})
        rule = market_cfg.get(domain) or {}
        rule_type = rule.get("rule_type", "time_window")
        if rule_type == "time_window":
            hours = rule.get("threshold_hours")
            if hours:
                return float(hours)
            minutes = rule.get("threshold_minutes")
            if minutes:
                return float(minutes) / 60.0
            return None
        # trading_day_after_close：自然日预算，市场可覆盖
        override = (
            self._config.get("markets", {})
            .get(market, {})
            .get("stale_after_hours", {})
            .get("trading_day_default")
        )
        if override is None:
            override = (self._config.get("stale_after_hours") or {}).get(
                "trading_day_default", 72
            )
        return float(override)

    # ── 主判定 ───────────────────────────────────────────

    def evaluate(
        self,
        market: str,
        domain: str,
        record_count: int,
        last_sync_time: Optional[str],
        checkpoint_success: bool,
        sources: Optional[List[Dict]] = None,
        coverage: Optional[float] = None,
        monitoring_available: bool = True,
        now=None,
    ) -> Dict[str, Any]:
        """按短路优先级判定域健康，返回 DomainHealth 结构。"""
        from datetime import datetime, timezone

        now = now or datetime.now(timezone.utc)
        sources = sources or []

        expected_hours = self._stale_budget_hours(market, domain)
        actual_hours = self._age_hours(last_sync_time, now)

        status, reason = self._decide(
            record_count=record_count,
            checkpoint_success=checkpoint_success,
            sources=sources,
            coverage=None if self._is_coverage_exempt(domain) else coverage,
            monitoring_available=monitoring_available,
            actual_hours=actual_hours,
            expected_hours=expected_hours,
        )

        return {
            "domain": domain,
            "status": status,
            "reason": reason,
            "record_count": record_count,
            "coverage": None if self._is_coverage_exempt(domain) else coverage,
            "last_sync_time": last_sync_time,
            "freshness": {
                "expected_hours": expected_hours,
                "actual_hours": actual_hours,
                "budget_hours": expected_hours,
            },
            "sources": [self._serialize_source(s) for s in sources],
        }

    def _decide(
        self,
        record_count: int,
        checkpoint_success: bool,
        sources: List[Dict],
        coverage: Optional[float],
        monitoring_available: bool,
        actual_hours: Optional[float],
        expected_hours: Optional[float],
    ):
        defaults = self._defaults()
        min_samples = defaults.get("min_samples", 20)
        min_rate = defaults.get("min_success_rate", 0.5)
        warn_rate = defaults.get("warn_success_rate", 0.8)
        max_latency = defaults.get("max_latency_ms", 5000)
        min_coverage = defaults.get("min_coverage", 0.8)

        # 0. 监控失联 → unknown（绝不显示为健康）
        if not monitoring_available:
            return "unknown", "健康监控数据不可用（监控失联）"

        # 运行时源信号是否存在（无调用 = 未测试，不参与源健康判定，
        # 但不阻断数据存在性/新鲜度判定——定时同步过也是健康证据）
        has_source_signal = bool(sources) and any(
            (s.get("total_calls") or 0) > 0 for s in sources
        )

        # 1. 无数据
        if record_count == 0 and not checkpoint_success:
            return "no_data", "库内无记录且无成功同步检查点"

        # 2. 运行健康 → unhealthy / degraded（仅有源信号时判定）
        if has_source_signal:
            open_sources = [s for s in sources if s.get("circuit_state") == "open"]
            closed_sources = [s for s in sources if s.get("circuit_state") == "closed"]
            if open_sources and not closed_sources:
                names = ", ".join(s.get("source", "?") for s in open_sources)
                return "unhealthy", f"全部数据源熔断开启（{names}）"
            for s in sources:
                calls = s.get("total_calls_1h") or s.get("total_calls") or 0
                rate = s.get("success_rate_1h")
                if rate is not None and calls >= min_samples and rate < min_rate:
                    return "unhealthy", (
                        f"源 {s.get('source')} 窗口成功率 {rate:.0%} 低于 {min_rate:.0%}"
                        f"（{calls} 次调用）"
                    )

        # 3. 新鲜度 → stale
        if (
            actual_hours is not None
            and expected_hours is not None
            and actual_hours > expected_hours
        ):
            return "stale", (
                f"最近更新 {actual_hours:.0f} 小时前，超出预算 {expected_hours:.0f} 小时"
            )

        # 4. 劣化 → degraded
        if has_source_signal:
            if open_sources:  # 有 open 但仍有 closed 备用源 → 已降级
                names = ", ".join(s.get("source", "?") for s in open_sources)
                return "degraded", f"部分源熔断（{names}），已降级到备用源"
            if any(s.get("circuit_state") == "half_open" for s in sources):
                return "degraded", "存在半开熔断源（恢复探测中）"
            for s in sources:
                calls = s.get("total_calls_1h") or s.get("total_calls") or 0
                rate = s.get("success_rate_1h")
                if rate is not None and calls >= min_samples and rate < warn_rate:
                    return "degraded", (
                        f"源 {s.get('source')} 窗口成功率 {rate:.0%} 低于 {warn_rate:.0%}"
                    )
            for s in sources:
                latency = s.get("avg_latency_1h")
                if latency is not None and latency > max_latency:
                    return "degraded", f"源 {s.get('source')} 平均延迟 {latency:.0f}ms 超标"
        if coverage is not None and coverage < min_coverage:
            return "degraded", f"覆盖率 {coverage:.0%} 低于 {min_coverage:.0%}"

        # 5. 健康
        if not has_source_signal:
            return "healthy", "数据存在且新鲜（无运行时源调用信号，按数据判定）"
        return "healthy", "数据存在、新鲜、源运行正常"

    # ── 工具 ─────────────────────────────────────────────

    @staticmethod
    def _serialize_source(s: Dict) -> Dict:
        """序列化源健康：无样本不伪造（circuit_state=unknown / rate=null）。"""
        no_signal = (s.get("total_calls") or 0) == 0
        rate = s.get("success_rate_1h")
        latency = s.get("avg_latency_1h")
        return {
            "source": s.get("source", ""),
            "circuit_state": "unknown" if no_signal else s.get("circuit_state", "closed"),
            "success_rate_1h": None if (no_signal or rate is None) else rate,
            "avg_latency_1h": None if (no_signal or latency is None) else latency,
            "total_calls": s.get("total_calls") or 0,
            "consecutive_failures": s.get("consecutive_failures", 0),
        }

    @staticmethod
    def _age_hours(ts: Optional[str], now) -> Optional[float]:
        from datetime import datetime, timezone

        if not ts:
            return None
        try:
            if isinstance(ts, datetime):
                updated = ts
            else:
                s = str(ts)
                s = s.replace("Z", "+00:00") if s.endswith("Z") else s
                updated = datetime.fromisoformat(s)
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
            return (now - updated).total_seconds() / 3600.0
        except (ValueError, TypeError):
            return None

    # ── 市场总览 ─────────────────────────────────────────

    @staticmethod
    def summarize(domain_health: List[Dict]) -> Dict[str, Any]:
        """状态页规范：市场整体状态 = 各域状态聚合（顶部横幅）。"""
        counts: Dict[str, int] = {}
        for d in domain_health:
            counts[d["status"]] = counts.get(d["status"], 0) + 1
        if any(counts.get(k) for k in ("unhealthy", "no_data")):
            overall = "partial_outage"
        elif any(counts.get(k) for k in ("stale", "degraded")):
            overall = "degraded"
        elif counts.get("healthy"):
            overall = "all_healthy" if not counts.get("unknown") else "degraded"
        else:
            overall = "unknown"
        return {
            "overall": overall,
            "healthy_domains": counts.get("healthy", 0),
            "warning_domains": counts.get("degraded", 0) + counts.get("stale", 0),
            "problem_domains": counts.get("unhealthy", 0) + counts.get("no_data", 0),
            "unknown_domains": counts.get("unknown", 0),
            "total_domains": len(domain_health),
        }
