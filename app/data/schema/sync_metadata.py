"""
同步元数据 Schema: 检查点 / 事件 / 数据源健康

三个集合的 Schema 定义：
  - sync_checkpoints: 各域增量同步进度
  - sync_events: 同步任务审计记录
  - source_health: 数据源健康状态
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .base import BaseSchema, _utc_now_iso


@dataclass
class SyncCheckpointSchema(BaseSchema):
    """
    sync_checkpoints 集合 Schema

    主键: (domain, source)
    记录各域增量同步的最新进度
    """

    domain: str = ""                # 数据域: daily_quotes / basic_info / ...
    source: str = ""                # 数据源编码: tushare / akshare / baostock
    last_sync_date: Optional[str] = None   # 上次成功同步的数据截止日期
    last_sync_time: Optional[str] = None   # 上次成功同步的执行时间
    status: str = "idle"            # idle / running / success / failed
    record_count: int = 0           # 上次同步的记录数
    error_message: Optional[str] = None

    @classmethod
    def from_raw(cls, raw: Dict[str, Any], source: str) -> "SyncCheckpointSchema":
        return cls(
            domain=raw.get("domain", ""),
            source=raw.get("source", ""),
            last_sync_date=raw.get("last_sync_date"),
            last_sync_time=raw.get("last_sync_time"),
            status=raw.get("status", "idle"),
            record_count=raw.get("record_count", 0),
            error_message=raw.get("error_message"),
            data_source=source,
            updated_at=raw.get("updated_at", _utc_now_iso()),
        )


@dataclass
class SyncEventSchema(BaseSchema):
    """
    sync_events 集合 Schema

    事件类型:
      SYNC_START / SYNC_SUCCESS / SYNC_FAILED
      SOURCE_FALLBACK / CIRCUIT_OPEN / CIRCUIT_CLOSE
    """

    event_type: str = ""            # SYNC_START / SYNC_SUCCESS / SYNC_FAILED / SOURCE_FALLBACK / ...
    domain: str = ""                # 数据域
    source: str = ""                # 数据源
    symbol: Optional[str] = None    # 股票代码（按需刷新时有值）
    task_id: Optional[str] = None   # 任务 ID

    # 回退事件详情
    fallback_from: Optional[str] = None  # 从哪个源降级
    fallback_to: Optional[str] = None    # 降级到哪个源
    fallback_reason: Optional[str] = None

    # 同步结果
    record_count: int = 0
    duration_ms: int = 0
    error_message: Optional[str] = None

    @classmethod
    def from_raw(cls, raw: Dict[str, Any], source: str) -> "SyncEventSchema":
        return cls(
            event_type=raw.get("event_type", ""),
            domain=raw.get("domain", ""),
            source=raw.get("source", ""),
            symbol=raw.get("symbol"),
            task_id=raw.get("task_id"),
            fallback_from=raw.get("fallback_from"),
            fallback_to=raw.get("fallback_to"),
            fallback_reason=raw.get("fallback_reason"),
            record_count=raw.get("record_count", 0),
            duration_ms=raw.get("duration_ms", 0),
            error_message=raw.get("error_message"),
            data_source=source,
            updated_at=raw.get("updated_at", _utc_now_iso()),
        )


@dataclass
class SourceHealthSchema(BaseSchema):
    """
    source_health 集合 Schema

    主键: (source, domain)
    记录数据源+域的健康统计
    """

    source: str = ""                # 数据源编码
    domain: str = ""                # 数据域
    circuit_state: str = "closed"   # closed / open / half_open

    # 最近 1 小时统计
    success_rate_1h: float = 0.0    # 成功率 (0.0 - 1.0)
    avg_latency_1h: float = 0.0     # 平均延迟（毫秒）
    total_calls_1h: int = 0         # 总调用次数

    # 状态信息
    last_success_time: Optional[str] = None
    last_failure_time: Optional[str] = None
    consecutive_failures: int = 0
    last_error_message: Optional[str] = None

    # 熔断器冷却
    circuit_opened_at: Optional[str] = None
    next_retry_at: Optional[str] = None
    open_count: int = 0             # 累计熔断次数（用于阶梯冷却）

    @classmethod
    def from_raw(cls, raw: Dict[str, Any], source: str) -> "SourceHealthSchema":
        return cls(
            source=raw.get("source", ""),
            domain=raw.get("domain", ""),
            circuit_state=raw.get("circuit_state", "closed"),
            success_rate_1h=raw.get("success_rate_1h", 0.0),
            avg_latency_1h=raw.get("avg_latency_1h", 0.0),
            total_calls_1h=raw.get("total_calls_1h", 0),
            last_success_time=raw.get("last_success_time"),
            last_failure_time=raw.get("last_failure_time"),
            consecutive_failures=raw.get("consecutive_failures", 0),
            last_error_message=raw.get("last_error_message"),
            circuit_opened_at=raw.get("circuit_opened_at"),
            next_retry_at=raw.get("next_retry_at"),
            open_count=raw.get("open_count", 0),
            data_source=source,
            updated_at=raw.get("updated_at", _utc_now_iso()),
        )
