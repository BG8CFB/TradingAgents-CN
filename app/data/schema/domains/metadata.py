from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class SyncCheckpointSchema:
    """同步检查点 — sync_checkpoints 集合文档。

    data_source 为标准键；兼容期存量文档可能仍只有 legacy `source` 键，
    读取经 MetadataRepo 投影补齐双键（见其 `_project_source_compat`）。
    """
    market: str
    domain: str
    data_source: str
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
    """同步事件 — sync_events 集合文档。

    data_source 为标准键；兼容期读侧经 MetadataRepo 投影补齐 legacy
    `source` 别名。`source_from` / `source_to` 是「回退前后源」语义对，
    保留原名不改（改一半反而破坏成对语义）。
    """
    market: str
    event_type: str          # SYNC_START / SYNC_SUCCESS / SYNC_FAILED / SOURCE_FALLBACK / CIRCUIT_OPEN / CIRCUIT_CLOSE
    domain: str
    data_source: Optional[str] = None
    source_from: Optional[str] = None   # 回退事件: 源（语义对，保留原名）
    source_to: Optional[str] = None     # 回退事件: 目标（语义对，保留原名）
    reason: Optional[str] = None
    record_count: Optional[int] = None
    duration_ms: Optional[int] = None
    task_id: Optional[str] = None
    created_at: Optional[str] = None

    def to_db_doc(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class SourceHealthSchema:
    """数据源健康 — source_health 集合文档。

    data_source 为标准键；兼容期读侧双键投影同 sync_checkpoints。
    """
    market: str
    data_source: str
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
