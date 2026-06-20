"""熔断器 — 按 source × domain 粒度隔离故障。

冷却阶梯支持按数据源配置（从 source_limits.yaml 读取）：
- 每个源可独立设置 ``circuit_initial_cooldown`` 与 ``circuit_max_cooldown``
- 阶梯自动从 initial → max 生成（3 档：initial、initial*2、max）
- 未配置的源回退到全局默认 [60, 120, 300, 600]
- 错误类型倍率继续叠加（1x ~ 5x），封顶 3600s
"""

import logging
import threading
import time
from typing import Dict, List, Optional, Tuple

from app.data.schema.base.enums import CircuitState
from app.data.sources.base.error_codes import DataErrorCode

logger = logging.getLogger(__name__)

FAILURE_THRESHOLD = 3
WINDOW_SECONDS = 300
# 全局默认冷却阶梯（向后兼容旧测试与未配置源）
COOLDOWN_STEPS: List[int] = [60, 120, 300, 600]
# half-open 探测请求挂起超过该时长视为卡死，允许新探测通过
_HALF_OPEN_PROBE_TIMEOUT = 60.0
# 单源冷却时间绝对上限
_ABSOLUTE_MAX_COOLDOWN = 3600

_ERROR_COOLDOWN_MULTIPLIERS = {
    DataErrorCode.RATE_LIMITED: 2,
    DataErrorCode.AUTH_FAILED: 5,
    DataErrorCode.TOKEN_INVALID: 5,
    DataErrorCode.NETWORK_TIMEOUT: 1,
    DataErrorCode.CONNECTION_ERROR: 1,
    DataErrorCode.SERVICE_UNAVAILABLE: 1.5,  # 上游 5xx 短暂故障，与 SERVER_ERROR 同档
    DataErrorCode.SERVER_ERROR: 1.5,
    DataErrorCode.DATA_INVALID: 1,
    DataErrorCode.INSUFFICIENT_CREDITS: 5,
}


def _build_cooldown_steps(initial: int, max_cooldown: int) -> List[int]:
    """根据 initial 与 max 生成单调递增的三档冷却阶梯。

    阶梯含义：第 1 次熔断用 initial，第 2 次用 initial*2，
    第 3 次及以后直接用 max_cooldown。
    """
    initial = max(1, int(initial))
    max_cooldown = max(initial, int(max_cooldown))
    mid = min(initial * 2, max_cooldown)
    return [initial, mid, max_cooldown]


def load_source_cooldown_config() -> Dict[str, List[int]]:
    """从 source_limits.yaml 读取每个源的冷却阶梯。

    YAML 字段（由本文档熔断参数表维护）：
        circuit_initial_cooldown: 初始冷却秒数
        circuit_max_cooldown:     最大冷却秒数

    Returns:
        dict[source_name -> [initial, mid, max]]，读取失败或未配置返回空 dict。
    """
    import yaml
    from pathlib import Path

    config_path = Path(__file__).parent.parent / "config" / "source_limits.yaml"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            limits_config = yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"加载熔断冷却配置失败，使用默认阶梯: {e}")
        return {}

    result: Dict[str, List[int]] = {}
    for source, cfg in limits_config.items():
        if not isinstance(cfg, dict):
            continue
        initial = cfg.get("circuit_initial_cooldown")
        max_cd = cfg.get("circuit_max_cooldown")
        if initial is None or max_cd is None:
            continue
        result[source] = _build_cooldown_steps(int(initial), int(max_cd))
    return result


class CircuitBreaker:
    """三态熔断器: Closed → Open → HalfOpen。

    可选传入 ``source_cooldown_config`` 按 source 定制冷却阶梯，
    未提供时通过 :func:`load_source_cooldown_config` 自动加载，
    加载失败或源缺失则回退到 :data:`COOLDOWN_STEPS`。
    """

    def __init__(self, source_cooldown_config: Optional[Dict[str, List[int]]] = None):
        self._states: Dict[Tuple[str, str], dict] = {}
        self._lock = threading.Lock()
        # 记录探测开始时间戳；超时未回调则视为卡死，允许新探测
        self._half_open_probing: Dict[Tuple[str, str], float] = {}
        # 按 source 定制的冷却阶梯；None 表示未启用定制，使用全局默认
        if source_cooldown_config is None:
            try:
                source_cooldown_config = load_source_cooldown_config()
            except Exception as e:
                logger.warning(f"熔断冷却配置加载失败，全部源使用默认阶梯: {e}")
                source_cooldown_config = {}
        self._source_steps: Dict[str, List[int]] = source_cooldown_config or {}

    def _get_steps(self, source: str) -> List[int]:
        """返回该 source 应使用的冷却阶梯。"""
        return self._source_steps.get(source) or COOLDOWN_STEPS

    def _get_state(self, source: str, domain: str) -> dict:
        key = (source, domain)
        if key not in self._states:
            steps = self._get_steps(source)
            self._states[key] = {
                "state": CircuitState.CLOSED,
                "failures": [],
                "trip_count": 0,
                "opened_at": 0,
                "cooldown": steps[0],
                "last_success": 0,
            }
        return self._states[key]

    def is_open(self, source: str, domain: str) -> bool:
        """判断熔断器是否打开（请求应被拒绝）。"""
        with self._lock:
            state = self._get_state(source, domain)
            key = (source, domain)

            if state["state"] == CircuitState.CLOSED:
                return False

            if state["state"] == CircuitState.OPEN:
                elapsed = time.time() - state["opened_at"]
                if elapsed >= state["cooldown"]:
                    state["state"] = CircuitState.HALF_OPEN
                    logger.info(f"熔断器半开: {source}/{domain}")
                    # 允许第一个探测请求通过，其余继续拒绝
                    probe_started = self._half_open_probing.get(key)
                    if (
                        probe_started is not None
                        and (time.time() - probe_started) < _HALF_OPEN_PROBE_TIMEOUT
                    ):
                        return True  # 已有探测请求在执行且未超时，拒绝新请求
                    self._half_open_probing[key] = time.time()
                    return False
                return True

            if state["state"] == CircuitState.HALF_OPEN:
                probe_started = self._half_open_probing.get(key)
                if (
                    probe_started is not None
                    and (time.time() - probe_started) < _HALF_OPEN_PROBE_TIMEOUT
                ):
                    return True  # 已有探测请求在执行且未超时，拒绝新请求
                self._half_open_probing[key] = time.time()
                return False  # 允许这个探测请求（无探测或已超时）

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

    def record_failure(
        self, source: str, domain: str, error_code: Optional[DataErrorCode] = None
    ) -> None:
        with self._lock:
            state = self._get_state(source, domain)
            now = time.time()

            state["failures"] = [
                t for t in state["failures"] if now - t < WINDOW_SECONDS
            ]
            state["failures"].append(now)

            if state["state"] == CircuitState.HALF_OPEN:
                self._trip(source, domain, error_code)
                self._half_open_probing.pop((source, domain), None)
                return

            if len(state["failures"]) >= FAILURE_THRESHOLD:
                self._trip(source, domain, error_code)

    def _trip(
        self, source: str, domain: str, error_code: Optional[DataErrorCode] = None
    ) -> None:
        """触发熔断。注意：必须在 self._lock 内调用（由 record_failure 持有锁）。"""
        state = self._get_state(source, domain)
        steps = self._get_steps(source)
        state["state"] = CircuitState.OPEN
        state["opened_at"] = time.time()
        state["trip_count"] += 1

        idx = min(state["trip_count"] - 1, len(steps) - 1)
        base_cooldown = steps[idx]
        multiplier = _ERROR_COOLDOWN_MULTIPLIERS.get(error_code, 1)
        # 上限取该源阶梯最大值与全局绝对上限的较小者（保底不超过 1 小时）
        source_cap = steps[-1]
        cap = min(source_cap, _ABSOLUTE_MAX_COOLDOWN)
        state["cooldown"] = min(int(base_cooldown * multiplier), cap)

        logger.warning(
            f"熔断器打开: {source}/{domain}, 冷却 {state['cooldown']}s (错误: {error_code})"
        )

    def get_trip_count(self, source: str, domain: str) -> int:
        """获取熔断器跳闸次数。"""
        with self._lock:
            return self._get_state(source, domain).get("trip_count", 0)

    def reset(self, source: str, domain: str) -> None:
        """手动重置熔断器到 Closed 状态。"""
        with self._lock:
            state = self._get_state(source, domain)
            steps = self._get_steps(source)
            state["state"] = CircuitState.CLOSED
            state["failures"] = []
            state["trip_count"] = 0
            state["opened_at"] = 0
            state["cooldown"] = steps[0]
            logger.info(f"熔断器已重置: {source}/{domain}")
