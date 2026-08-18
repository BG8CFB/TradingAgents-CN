from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class SyncCheckpointSchema:
    """同步检查点 — sync_checkpoints 集合文档。"""
    market: str
    domain: str
    source: str
    last_sync_date: Optional[str] = None
    last_sync_time: Optional[str] = None
    status: Optional[str] = None       # success / failed / running
    record_count: Optional[int] = None
    duration_ms: Optional[int] = None
    # single=按需刷新单股 / batch=批量自选股 / market=全市场调度
    scope: Optional[str] = None
    # manual=用户手动触发 / scheduled=定时调度
    trigger: Optional[str] = None
    symbol: Optional[str] = None       # 仅 scope=single 时填充

    def to_db_doc(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class SyncEventSchema:
    """同步事件 — sync_events 集合文档。"""
    market: str
    event_type: str          # SYNC_START / SYNC_SUCCESS / SYNC_FAILED / SOURCE_FALLBACK / CIRCUIT_OPEN / CIRCUIT_CLOSE
    domain: str
    source: Optional[str] = None
    source_from: Optional[str] = None   # 回退事件: 源
    source_to: Optional[str] = None     # 回退事件: 目标
    reason: Optional[str] = None
    record_count: Optional[int] = None
    duration_ms: Optional[int] = None
    task_id: Optional[str] = None
    created_at: Optional[str] = None

    def to_db_doc(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class SourceHealthSchema:
    """数据源健康 — source_health 集合文档。"""
    market: str
    source: str
    domain: str
    success_rate_1h: Optional[float] = None
    avg_latency_ms_1h: Optional[float] = None
    circuit_state: Optional[str] = None  # closed / open / half_open
    last_success_time: Optional[str] = None
    consecutive_failures: Optional[int] = None
    total_calls_1h: Optional[int] = None
    total_failures_1h: Optional[int] = None
    updated_at: Optional[str] = None

    def to_db_doc(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}
