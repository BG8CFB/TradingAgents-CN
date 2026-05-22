"""数据源元信息 — 限流参数、凭据要求等。"""

from dataclasses import dataclass
from typing import Dict, Optional

from app.data.config import load_yaml


@dataclass
class SourceMetadata:
    """数据源元信息。"""
    rate_per_minute: int = 60
    rate_per_day: Optional[int] = None
    polite_interval_ms: int = 1000
    circuit_initial_cooldown: int = 60
    circuit_max_cooldown: int = 600
    requires_token: bool = False
    token_env_var: Optional[str] = None
    session_limit: Optional[int] = None  # BaoStock 特有


def _load_source_metadata() -> Dict[str, SourceMetadata]:
    data = load_yaml("source_limits.yaml")
    result = {}
    for source, params in data.items():
        result[source] = SourceMetadata(
            rate_per_minute=params.get("rate_per_minute", 60),
            rate_per_day=params.get("rate_per_day"),
            polite_interval_ms=params.get("polite_interval_ms", 1000),
            circuit_initial_cooldown=params.get("circuit_initial_cooldown", 60),
            circuit_max_cooldown=params.get("circuit_max_cooldown", 600),
            requires_token=params.get("requires_token", False),
            token_env_var=params.get("token_env_var"),
            session_limit=params.get("session_limit"),
        )
    return result


SOURCE_METADATA: Dict[str, SourceMetadata] = _load_source_metadata()
