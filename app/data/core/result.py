"""刷新结果数据结构。"""

from dataclasses import dataclass, field
from typing import Dict, Optional

from app.data.schema.base.enums import RefreshStatus


@dataclass
class DomainRefreshResult:
    """单域刷新结果。"""
    domain: str
    status: str               # fresh / refreshed / failed
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
        """根据各域结果计算整体状态。"""
        if not self.domains:
            return RefreshStatus.FAILED

        statuses = [d.status for d in self.domains.values()]
        all_fresh = all(s == "fresh" for s in statuses)
        all_success = all(s in ("fresh", "refreshed") for s in statuses)
        any_failed = "failed" in statuses

        if all_fresh:
            self.status = RefreshStatus.FRESH
        elif all_success:
            self.status = RefreshStatus.REFRESHED
        elif any_failed and all_success:
            self.status = RefreshStatus.PARTIAL
        else:
            self.status = RefreshStatus.FAILED
        return self.status
