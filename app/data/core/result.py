"""刷新结果数据结构。"""

from dataclasses import dataclass, field
from typing import Dict, Optional

from app.data.schema.base.enums import RefreshStatus


@dataclass
class DomainRefreshResult:
    """单域刷新结果。"""
    domain: str
    status: str  # fresh / refreshed / failed / timeout / skipped
    record_count: int = 0
    source: Optional[str] = None
    fallback_from: Optional[str] = None
    error: Optional[str] = None
    latency_ms: int = 0


@dataclass
class RefreshResult:
    """多域刷新汇总结果。"""
    status: str = RefreshStatus.FAILED  # 整体状态
    symbol: str = ""
    market: str = ""
    domains: Dict[str, DomainRefreshResult] = field(default_factory=dict)
    source_used: Optional[str] = None
    fallback_from: Optional[str] = None
    total_latency_ms: int = 0
    error: Optional[str] = None

    def compute_status(self) -> str:
        """根据各域结果计算整体状态。

        ``skipped`` 表示该域因锁被另一刷新占用而未执行——不计入失败或部分成功。
        若全部域都被 skipped，整体状态也为 skipped；若有部分 skipped + 其余成功，
        按其余域的结果计算（skipped 不拉低整体判定）。
        """
        if not self.domains:
            return RefreshStatus.FAILED

        statuses = [d.status for d in self.domains.values()]

        # 排除 skipped 域，仅用剩余域做整体判定
        non_skipped = [s for s in statuses if s != RefreshStatus.SKIPPED]
        if not non_skipped:
            self.status = RefreshStatus.SKIPPED
            return self.status

        all_fresh = all(s == "fresh" for s in non_skipped)
        all_success = all(s in ("fresh", "refreshed") for s in non_skipped)
        any_failed = "failed" in non_skipped
        any_timeout = "timeout" in non_skipped

        if all_fresh:
            self.status = RefreshStatus.FRESH
        elif all_success:
            self.status = RefreshStatus.REFRESHED
        elif any_failed or any_timeout:
            if any(s in ("fresh", "refreshed") for s in non_skipped):
                self.status = RefreshStatus.PARTIAL
            else:
                self.status = RefreshStatus.FAILED
        else:
            self.status = RefreshStatus.FAILED
        return self.status
