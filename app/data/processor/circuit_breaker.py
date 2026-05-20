"""
熔断器 (Circuit Breaker)

按「数据源 + 数据域」组合维度的三态状态机。
Redis 优先存储状态，不可用时降级为进程内存。

状态转换：
  Closed  → Open:    窗口期内连续失败 ≥ threshold
  Open    → HalfOpen: 冷却时间到期
  HalfOpen → Closed:  探测请求成功
  HalfOpen → Open:    探测请求失败

阶梯冷却策略：60s → 120s → 300s → 600s
"""

import logging
import time
from enum import Enum
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# 阶梯冷却时间表（秒）
_COOLDOWN_STEPS = [60, 120, 300, 600]

# 错误类型冷却倍数
_ERROR_TYPE_MULTIPLIERS = {
    "rate_limited": 2.0,    # 429 限流
    "auth_failed": 5.0,     # 403 认证
    "server_error": 1.5,    # 5xx
    "network": 1.0,         # 网络超时/断开
}


class _CircuitState:
    """单个熔断器实例的状态（进程内存）"""

    __slots__ = (
        "state", "failure_count", "window_start",
        "last_failure_time", "opened_at", "open_count", "next_retry_at",
    )

    def __init__(self):
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.window_start = time.monotonic()
        self.last_failure_time: Optional[float] = None
        self.opened_at: Optional[float] = None
        self.open_count = 0
        self.next_retry_at: Optional[float] = None


class CircuitBreaker:
    """
    熔断器管理器

    粒度: (source, domain) 组合。
    Redis 优先存储状态，不可用时降级为进程内存。
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        window_seconds: float = 300.0,     # 5 分钟窗口
        max_cooldown: float = 600.0,       # 最大冷却 10 分钟
        stable_threshold: float = 1800.0,  # 30 分钟稳定后重置计数
        redis_client=None,
    ):
        self._failure_threshold = failure_threshold
        self._window_seconds = window_seconds
        self._max_cooldown = max_cooldown
        self._stable_threshold = stable_threshold
        self._circuits: Dict[Tuple[str, str], _CircuitState] = {}
        self._redis = redis_client
        self._redis_prefix = "cb:"

    def _get_circuit(self, source: str, domain: str) -> _CircuitState:
        key = (source, domain)
        if key not in self._circuits:
            self._circuits[key] = _CircuitState()
        return self._circuits[key]

    def _cooldown_for_open_count(self, open_count: int, error_type: str = "network") -> float:
        """计算阶梯冷却时间"""
        idx = min(open_count - 1, len(_COOLDOWN_STEPS) - 1)
        cooldown = float(_COOLDOWN_STEPS[idx])
        multiplier = _ERROR_TYPE_MULTIPLIERS.get(error_type, 1.0)
        return min(cooldown * multiplier, self._max_cooldown)

    def get_state(self, source: str, domain: str) -> CircuitState:
        """获取当前熔断状态（自动检查冷却是否到期）"""
        circuit = self._get_circuit(source, domain)

        if circuit.state == CircuitState.OPEN:
            now = time.monotonic()
            if circuit.next_retry_at and now >= circuit.next_retry_at:
                circuit.state = CircuitState.HALF_OPEN
                logger.info(
                    "熔断器 %s/%s 进入 HalfOpen 状态，允许探测请求",
                    source, domain,
                )

        return circuit.state

    def is_open(self, source: str, domain: str) -> bool:
        """熔断器是否处于 Open 状态（调用方应跳过该源）"""
        return self.get_state(source, domain) == CircuitState.OPEN

    def record_success(self, source: str, domain: str) -> None:
        """记录成功调用"""
        circuit = self._get_circuit(source, domain)

        if circuit.state == CircuitState.HALF_OPEN:
            # 探测成功 → 恢复
            circuit.state = CircuitState.CLOSED
            circuit.failure_count = 0
            circuit.open_count = 0
            circuit.window_start = time.monotonic()
            self._sync_to_redis(source, domain, circuit, "recovered")
            logger.info("熔断器 %s/%s 恢复为 Closed", source, domain)
        else:
            # 正常成功 → 重置失败计数
            circuit.failure_count = 0
            # 检查是否稳定恢复（30 分钟无失败 → 重置 open_count）
            if circuit.open_count > 0:
                now = time.monotonic()
                if (circuit.last_failure_time and
                        now - circuit.last_failure_time > self._stable_threshold):
                    circuit.open_count = 0

    def record_failure(self, source: str, domain: str, error_type: str = "network") -> None:
        """记录失败调用"""
        circuit = self._get_circuit(source, domain)
        now = time.monotonic()

        circuit.last_failure_time = now

        if circuit.state == CircuitState.HALF_OPEN:
            # 探测失败 → 重新熔断
            self._open_circuit(circuit, source, domain, error_type)
            return

        if circuit.state == CircuitState.OPEN:
            return

        # 检查窗口期：超出窗口则重置计数
        if now - circuit.window_start > self._window_seconds:
            circuit.failure_count = 0
            circuit.window_start = now

        circuit.failure_count += 1

        if circuit.failure_count >= self._failure_threshold:
            self._open_circuit(circuit, source, domain, error_type)

    def _open_circuit(
        self, circuit: _CircuitState, source: str, domain: str, error_type: str,
    ) -> None:
        """将熔断器切换到 Open 状态"""
        circuit.state = CircuitState.OPEN
        circuit.opened_at = time.monotonic()
        circuit.open_count += 1

        cooldown = self._cooldown_for_open_count(circuit.open_count, error_type)
        circuit.next_retry_at = circuit.opened_at + cooldown

        # 同步到 Redis
        self._sync_to_redis(source, domain, circuit, "open", error_type)

        logger.warning(
            "熔断器 %s/%s 打开 (第 %d 次, 冷却 %.0fs, 错误类型: %s)",
            source, domain, circuit.open_count, cooldown, error_type,
        )

    def reset(self, source: str, domain: str) -> None:
        """手动重置熔断器"""
        circuit = self._get_circuit(source, domain)
        circuit.state = CircuitState.CLOSED
        circuit.failure_count = 0
        circuit.open_count = 0
        circuit.opened_at = None
        circuit.next_retry_at = None
        logger.info("熔断器 %s/%s 已手动重置", source, domain)

    def get_all_states(self) -> Dict[Tuple[str, str], Dict]:
        """获取所有熔断器状态（用于健康监控）"""
        result = {}
        for (source, domain), circuit in self._circuits.items():
            result[(source, domain)] = {
                "source": source,
                "domain": domain,
                "state": self.get_state(source, domain).value,
                "failure_count": circuit.failure_count,
                "open_count": circuit.open_count,
                "opened_at": circuit.opened_at,
                "next_retry_at": circuit.next_retry_at,
            }
        return result

    def _sync_to_redis(
        self, source: str, domain: str, circuit: _CircuitState,
        event: str, error_type: str = "",
    ) -> None:
        """将熔断器状态同步到 Redis（非关键路径，失败不影响功能）"""
        if self._redis is None:
            return

        try:
            import json
            key = f"{self._redis_prefix}{source}:{domain}"
            data = {
                "state": circuit.state.value,
                "failure_count": circuit.failure_count,
                "open_count": circuit.open_count,
                "opened_at": circuit.opened_at,
                "next_retry_at": circuit.next_retry_at,
                "event": event,
            }
            if error_type:
                data["error_type"] = error_type

            self._redis.setex(key, int(self._max_cooldown) + 60, json.dumps(data))
        except Exception as e:
            logger.debug("Redis 熔断器状态同步失败（降级为内存）: %s", e)

    def _load_from_redis(self, source: str, domain: str) -> Optional[_CircuitState]:
        """从 Redis 加载熔断器状态（启动时恢复）"""
        if self._redis is None:
            return None

        try:
            import json
            key = f"{self._redis_prefix}{source}:{domain}"
            raw = self._redis.get(key)
            if raw is None:
                return None

            data = json.loads(raw)
            circuit = _CircuitState()
            circuit.state = CircuitState(data.get("state", "closed"))
            circuit.failure_count = data.get("failure_count", 0)
            circuit.open_count = data.get("open_count", 0)
            circuit.opened_at = data.get("opened_at")
            circuit.next_retry_at = data.get("next_retry_at")
            return circuit
        except Exception:
            return None
