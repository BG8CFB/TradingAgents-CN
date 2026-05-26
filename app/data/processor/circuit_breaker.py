"""熔断器 — 按 source × domain 粒度隔离故障。"""

import logging
import threading
import time
from typing import Dict, Optional, Tuple

from app.data.schema.base.enums import CircuitState
from app.data.sources.base.error_codes import DataErrorCode

logger = logging.getLogger(__name__)

FAILURE_THRESHOLD = 3
WINDOW_SECONDS = 300
COOLDOWN_STEPS = [60, 120, 300, 600]

_ERROR_COOLDOWN_MULTIPLIERS = {
    DataErrorCode.RATE_LIMITED: 2,
    DataErrorCode.AUTH_FAILED: 5,
    DataErrorCode.TOKEN_INVALID: 5,
    DataErrorCode.NETWORK_TIMEOUT: 1,
    DataErrorCode.CONNECTION_ERROR: 1,
    DataErrorCode.SERVER_ERROR: 1.5,
    DataErrorCode.DATA_INVALID: 1,
    DataErrorCode.INSUFFICIENT_CREDITS: 5,
}


class CircuitBreaker:
    """三态熔断器: Closed → Open → HalfOpen。"""

    def __init__(self):
        self._states: Dict[Tuple[str, str], dict] = {}
        self._lock = threading.Lock()
        self._half_open_probing: Dict[Tuple[str, str], bool] = {}

    def _get_state(self, source: str, domain: str) -> dict:
        key = (source, domain)
        if key not in self._states:
            self._states[key] = {
                "state": CircuitState.CLOSED,
                "failures": [],
                "trip_count": 0,
                "opened_at": 0,
                "cooldown": COOLDOWN_STEPS[0],
                "last_success": 0,
            }
        return self._states[key]

    def is_open(self, source: str, domain: str) -> bool:
        """判断熔断器是否打开（请求应被拒绝）。"""
        with self._lock:
            state = self._get_state(source, domain)

            if state["state"] == CircuitState.CLOSED:
                return False

            if state["state"] == CircuitState.OPEN:
                elapsed = time.time() - state["opened_at"]
                if elapsed >= state["cooldown"]:
                    state["state"] = CircuitState.HALF_OPEN
                    logger.info(f"熔断器半开: {source}/{domain}")
                    # 允许第一个探测请求通过，其余继续拒绝
                    key = (source, domain)
                    if self._half_open_probing.get(key, False):
                        return True  # 已有探测请求在执行，拒绝新请求
                    self._half_open_probing[key] = True
                    return False
                return True

            if state["state"] == CircuitState.HALF_OPEN:
                key = (source, domain)
                if self._half_open_probing.get(key, False):
                    return True  # 已有探测请求在执行，拒绝新请求
                self._half_open_probing[key] = True
                return False  # 允许这个探测请求

    def get_state(self, source: str, domain: str) -> CircuitState:
        with self._lock:
            return self._get_state(source, domain)["state"]

    def record_success(self, source: str, domain: str) -> None:
        with self._lock:
            state = self._get_state(source, domain)
            state["state"] = CircuitState.CLOSED
            state["failures"] = []
            state["last_success"] = time.time()
            state["trip_count"] = max(0, state["trip_count"] - 1)
            self._half_open_probing.pop((source, domain), None)

    def record_failure(self, source: str, domain: str, error_code: Optional[DataErrorCode] = None) -> None:
        with self._lock:
            state = self._get_state(source, domain)
            now = time.time()

            state["failures"] = [t for t in state["failures"] if now - t < WINDOW_SECONDS]
            state["failures"].append(now)

            if state["state"] == CircuitState.HALF_OPEN:
                self._trip(source, domain, error_code)
                self._half_open_probing.pop((source, domain), None)
                return

            if len(state["failures"]) >= FAILURE_THRESHOLD:
                self._trip(source, domain, error_code)

    def _trip(self, source: str, domain: str, error_code: Optional[DataErrorCode] = None) -> None:
        """触发熔断。注意：必须在 self._lock 内调用（由 record_failure 持有锁）。"""
        state = self._get_state(source, domain)
        state["state"] = CircuitState.OPEN
        state["opened_at"] = time.time()
        state["trip_count"] += 1

        idx = min(state["trip_count"] - 1, len(COOLDOWN_STEPS) - 1)
        base_cooldown = COOLDOWN_STEPS[idx]
        multiplier = _ERROR_COOLDOWN_MULTIPLIERS.get(error_code, 1)
        state["cooldown"] = min(int(base_cooldown * multiplier), 3600)

        logger.warning(f"熔断器打开: {source}/{domain}, 冷却 {state['cooldown']}s (错误: {error_code})")

    def get_trip_count(self, source: str, domain: str) -> int:
        """获取熔断器跳闸次数。"""
        with self._lock:
            return self._get_state(source, domain).get("trip_count", 0)

    def reset(self, source: str, domain: str) -> None:
        """手动重置熔断器到 Closed 状态。"""
        with self._lock:
            state = self._get_state(source, domain)
            state["state"] = CircuitState.CLOSED
            state["failures"] = []
            state["trip_count"] = 0
            state["opened_at"] = 0
            state["cooldown"] = COOLDOWN_STEPS[0]
            logger.info(f"熔断器已重置: {source}/{domain}")
