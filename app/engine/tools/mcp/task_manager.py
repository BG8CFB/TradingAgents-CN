"""
任务级 MCP 工具管理器

核心功能：
1. 任务隔离：每个任务有独立的 MCP 工具状态
2. 断路器模式：工具连续失败后自动禁用
3. 重试机制：可重试错误自动重试
4. 并发控制：限制同一 MCP 服务器的并发调用

基于最佳实践：
- Circuit Breaker Pattern: https://www.groundcover.com/learn/performance/circuit-breaker-pattern
- Asyncio Semaphores: https://medium.com/@mr.sourav.raj/mastering-asyncio-semaphores-in-python-a-complete-guide-to-concurrency-control-6b4dd940e10e
- LangGraph Error Handling: https://sparkco.ai/blog/advanced-error-handling-strategies-in-langgraph-applications
"""

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Set, Optional, Any, Callable, Tuple
from enum import Enum
import functools

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """断路器状态"""
    CLOSED = "closed"      # 正常运行
    OPEN = "open"          # 断路器打开，拒绝请求
    HALF_OPEN = "half_open"  # 半开状态，允许测试请求


@dataclass
class CircuitBreakerConfig:
    """断路器配置"""
    failure_threshold: int = 3           # 连续失败阈值
    success_threshold: int = 2           # 半开状态成功阈值
    timeout: float = 60.0                # 断路器打开后等待时间（秒）
    window_size: int = 10                # 滑动窗口大小（请求数）


@dataclass
class RetryConfig:
    """重试配置"""
    max_attempts: int = 3                # 最大重试次数
    base_delay: float = 1.0              # 起始延迟（秒）- 1s → 2s → 4s
    max_delay: float = 10.0              # 最大延迟（秒）
    exponential_base: float = 2.0        # 指数退避基数


@dataclass
class ToolState:
    """工具状态"""
    failure_count: int = 0               # 连续失败计数
    last_failure_time: float = 0.0       # 上次失败时间
    last_success_time: float = 0.0       # 上次成功时间
    circuit_state: CircuitState = CircuitState.CLOSED
    total_calls: int = 0                 # 总调用次数
    total_failures: int = 0              # 总失败次数


class CircuitBreaker:
    """
    断路器实现

    状态转换：
    CLOSED -> OPEN: 连续失败达到阈值
    OPEN -> HALF_OPEN: 超时后进入半开状态
    HALF_OPEN -> CLOSED: 连续成功达到阈值
    HALF_OPEN -> OPEN: 再次失败
    """

    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_state_change = time.time()
        self._lock = asyncio.Lock()

    async def _can_attempt(self) -> bool:
        """检查是否允许尝试调用"""
        now = time.time()

        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            # 检查是否超时，可以进入半开状态
            if now - self.last_state_change >= self.config.timeout:
                logger.info(f"断路器超时，进入半开状态")
                self.state = CircuitState.HALF_OPEN
                self.last_state_change = now
                self.success_count = 0
                return True
            return False

        if self.state == CircuitState.HALF_OPEN:
            return True

        return False

    async def acquire(self) -> bool:
        """尝试获取调用许可"""
        async with self._lock:
            return await self._can_attempt()

    async def record_success(self):
        """记录成功调用"""
        async with self._lock:
            now = time.time()

            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.config.success_threshold:
                    logger.info(f"断路器恢复，进入关闭状态")
                    self.state = CircuitState.CLOSED
                    self.failure_count = 0
            elif self.state == CircuitState.CLOSED:
                self.failure_count = 0

            self.last_state_change = now

    async def record_failure(self):
        """记录失败调用"""
        async with self._lock:
            now = time.time()

            self.failure_count += 1

            if self.state == CircuitState.HALF_OPEN:
                # 半开状态失败，重新打开断路器
                logger.warning(f"半开状态失败，重新打开断路器")
                self.state = CircuitState.OPEN
                self.last_state_change = now
                self.success_count = 0
            elif self.failure_count >= self.config.failure_threshold:
                # 达到失败阈值，打开断路器
                logger.warning(f"连续失败 {self.failure_count} 次，打开断路器")
                self.state = CircuitState.OPEN
                self.last_state_change = now

    def get_state(self) -> CircuitState:
        """获取当前状态"""
        return self.state


class RetryMechanism:
    """
    重试机制

    支持指数退避和可重试异常判断
    """

    # 可重试异常类型
    RETRYABLE_EXCEPTIONS = (
        ConnectionError,
        TimeoutError,
        asyncio.TimeoutError,
        OSError,
    )

    def __init__(self, config: RetryConfig):
        self.config = config

    def is_retryable(self, exception: Exception) -> bool:
        """判断异常是否可重试"""
        # 检查是否在可重试异常列表中
        for exc_type in self.RETRYABLE_EXCEPTIONS:
            if isinstance(exception, exc_type):
                return True

        # 检查异常消息中的关键词
        error_msg = str(exception).lower()
        retryable_keywords = [
            "timeout", "timed out",
            "connection", "connect",
            "network", "network unreachable",
            "temporary", "temporarily",
            "rate limit", "too many requests",
            "503", "502", "504",  # HTTP 5xx 错误
        ]

        for keyword in retryable_keywords:
            if keyword in error_msg:
                return True

        return False

    def calculate_delay(self, attempt: int) -> float:
        """计算重试延迟（指数退避）"""
        delay = self.config.base_delay * (self.config.exponential_base ** (attempt - 1))
        return min(delay, self.config.max_delay)

    async def execute_with_retry(
        self,
        func: Callable,
        *args,
        **kwargs
    ) -> Any:
        """执行函数并在失败时重试"""
        last_exception = None

        for attempt in range(1, self.config.max_attempts + 1):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                last_exception = e

                if attempt >= self.config.max_attempts:
                    logger.warning(f"重试 {attempt}/{self.config.max_attempts} 次后仍失败: {e}")
                    break

                if not self.is_retryable(e):
                    logger.warning(f"不可重试的错误: {type(e).__name__}: {e}")
                    raise

                delay = self.calculate_delay(attempt)
                logger.info(f"可重试错误 ({attempt}/{self.config.max_attempts}): {e}, {delay:.1f}秒后重试")
                await asyncio.sleep(delay)

        # 所有重试都失败
        raise last_exception


class TaskLevelMCPManager:
    """
    任务级 MCP 工具管理器

    功能：
    1. 任务隔离：每个 task_id 有独立的工具状态
    2. 断路器：工具连续失败后禁用
    3. 重试：可重试错误自动重试
    4. 并发控制：限制服务器级并发
    """

    def __init__(self, task_id: str):
        self.task_id = task_id
        self._tool_states: Dict[str, ToolState] = {}
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._server_semaphores: Dict[str, asyncio.Semaphore] = {}
        self._failed_tools: Set[str] = set()
        self._retry_mechanism = RetryMechanism(RetryConfig())
        self._circuit_config = CircuitBreakerConfig()
        self._lock = asyncio.Lock()

        # 默认服务器并发限制
        self._default_server_concurrency = 5

        logger.info(f"创建任务级 MCP 管理器: {task_id}")

    def _get_tool_key(self, tool_name: str, server_name: Optional[str] = None) -> str:
        """生成工具的唯一键"""
        if server_name:
            return f"{server_name}:{tool_name}"
        return tool_name

    def _get_server_name(self, tool_key: str) -> Optional[str]:
        """从工具键提取服务器名"""
        if ":" in tool_key:
            return tool_key.split(":", 1)[0]
        return None

    def _get_tool_state(self, tool_key: str) -> ToolState:
        """获取或创建工具状态"""
        if tool_key not in self._tool_states:
            self._tool_states[tool_key] = ToolState()
        return self._tool_states[tool_key]

    def _get_circuit_breaker(self, tool_key: str) -> CircuitBreaker:
        """获取或创建断路器"""
        if tool_key not in self._circuit_breakers:
            self._circuit_breakers[tool_key] = CircuitBreaker(self._circuit_config)
        return self._circuit_breakers[tool_key]

    def _get_server_semaphore(self, server_name: str) -> asyncio.Semaphore:
        """获取或创建服务器信号量"""
        if server_name not in self._server_semaphores:
            self._server_semaphores[server_name] = asyncio.Semaphore(self._default_server_concurrency)
        return self._server_semaphores[server_name]

    async def is_tool_available(self, tool_name: str, server_name: Optional[str] = None) -> bool:
        """检查工具是否可用"""
        tool_key = self._get_tool_key(tool_name, server_name)

        # 检查是否在失败集合中
        if tool_key in self._failed_tools:
            return False

        # 检查断路器状态
        circuit_breaker = self._get_circuit_breaker(tool_key)
        return await circuit_breaker.acquire()

    async def execute_tool(
        self,
        tool_name: str,
        func: Callable,
        *args,
        server_name: Optional[str] = None,
        **kwargs
    ) -> Any:
        """
        执行 MCP 工具调用

        包含：
        1. 断路器检查
        2. 服务器级并发控制
        3. 自动重试
        4. 失败记录
        """
        tool_key = self._get_tool_key(tool_name, server_name)

        # 检查工具是否可用
        if not await self.is_tool_available(tool_name, server_name):
            logger.warning(f"工具 {tool_name} 在当前任务中已禁用")
            return {
                "status": "disabled",
                "message": f"工具 {tool_name} 在当前任务中已禁用（连续失败或断路器打开）",
                "tool_name": tool_name
            }

        circuit_breaker = self._get_circuit_breaker(tool_key)
        tool_state = self._get_tool_state(tool_key)

        # 获取服务器级并发锁
        semaphore = None
        if server_name:
            semaphore = self._get_server_semaphore(server_name)

        try:
            # 应用并发限制
            if semaphore:
                await semaphore.acquire()

            tool_state.total_calls += 1

            # 执行工具（带重试）
            result = await self._retry_mechanism.execute_with_retry(func, *args, **kwargs)

            # 记录成功
            await circuit_breaker.record_success()
            tool_state.last_success_time = time.time()
            tool_state.failure_count = 0

            return result

        except Exception as e:
            # 记录失败
            await circuit_breaker.record_failure()
            tool_state.failure_count += 1
            tool_state.last_failure_time = time.time()
            tool_state.total_failures += 1

            # 检查是否需要禁用工具
            if tool_state.failure_count >= self._circuit_config.failure_threshold:
                async with self._lock:
                    self._failed_tools.add(tool_key)
                logger.error(f"工具 {tool_name} 连续失败 {tool_state.failure_count} 次，已在当前任务中禁用")

            # 返回友好的错误信息
            return {
                "status": "error",
                "message": f"工具调用失败: {str(e)}",
                "tool_name": tool_name,
                "error_type": type(e).__name__
            }

        finally:
            # 释放并发锁
            if semaphore:
                semaphore.release()

    def get_tool_statistics(self, tool_name: str, server_name: Optional[str] = None) -> Dict[str, Any]:
        """获取工具统计信息"""
        tool_key = self._get_tool_key(tool_name, server_name)
        tool_state = self._get_tool_state(tool_key)
        circuit_breaker = self._get_circuit_breaker(tool_key)

        return {
            "tool_name": tool_name,
            "server_name": server_name,
            "total_calls": tool_state.total_calls,
            "total_failures": tool_state.total_failures,
            "failure_count": tool_state.failure_count,
            "circuit_state": circuit_breaker.get_state().value,
            "is_disabled": tool_key in self._failed_tools,
            "last_success_time": tool_state.last_success_time,
            "last_failure_time": tool_state.last_failure_time,
        }

    def get_all_statistics(self) -> Dict[str, Dict[str, Any]]:
        """获取所有工具统计"""
        return {
            tool_key: self.get_tool_statistics(
                tool_key.split(":", 1)[1] if ":" in tool_key else tool_key,
                self._get_server_name(tool_key)
            )
            for tool_key in self._tool_states.keys()
        }

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为可序列化的字典

        只提取配置数据，排除运行时状态（锁、信号量等）
        """
        return {
            "task_id": self.task_id,
            "default_server_concurrency": self._default_server_concurrency,
            "circuit_breaker_config": {
                "failure_threshold": self._circuit_config.failure_threshold,
                "success_threshold": self._circuit_config.success_threshold,
                "timeout": self._circuit_config.timeout,
                "window_size": self._circuit_config.window_size
            },
            "retry_config": {
                "max_attempts": self._retry_mechanism.config.max_attempts,
                "base_delay": self._retry_mechanism.config.base_delay,
                "max_delay": self._retry_mechanism.config.max_delay,
                "exponential_base": self._retry_mechanism.config.exponential_base
            },
            "tool_states": {
                key: {
                    "failure_count": state.failure_count,
                    "last_failure_time": state.last_failure_time,
                    "last_success_time": state.last_success_time,
                    "total_calls": state.total_calls,
                    "total_failures": state.total_failures
                }
                for key, state in self._tool_states.items()
            },
            "failed_tools": list(self._failed_tools)
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TaskLevelMCPManager':
        """
        从字典创建实例

        恢复配置数据，重新初始化运行时对象
        """
        task_id = data.get("task_id", "unknown")
        manager = cls(task_id)

        # 恢复配置
        if "circuit_breaker_config" in data:
            config = data["circuit_breaker_config"]
            manager._circuit_config = CircuitBreakerConfig(
                failure_threshold=config.get("failure_threshold", 3),
                success_threshold=config.get("success_threshold", 2),
                timeout=config.get("timeout", 60.0),
                window_size=config.get("window_size", 10)
            )

        if "retry_config" in data:
            config = data["retry_config"]
            manager._retry_mechanism = RetryMechanism(RetryConfig(
                max_attempts=config.get("max_attempts", 3),
                base_delay=config.get("base_delay", 1.0),
                max_delay=config.get("max_delay", 10.0),
                exponential_base=config.get("exponential_base", 2.0)
            ))

        if "default_server_concurrency" in data:
            manager._default_server_concurrency = data["default_server_concurrency"]

        # 恢复工具状态（但不包含运行时锁）
        if "tool_states" in data:
            for key, state_data in data["tool_states"].items():
                manager._tool_states[key] = ToolState(
                    failure_count=state_data.get("failure_count", 0),
                    last_failure_time=state_data.get("last_failure_time", 0.0),
                    last_success_time=state_data.get("last_success_time", 0.0),
                    total_calls=state_data.get("total_calls", 0),
                    total_failures=state_data.get("total_failures", 0)
                )

        # 恢复失败工具集合
        if "failed_tools" in data:
            manager._failed_tools = set(data["failed_tools"])

        return manager


# 全局任务管理器注册表
_task_managers: Dict[str, TaskLevelMCPManager] = {}
_managers_lock = asyncio.Lock()


def get_task_mcp_manager(task_id: str) -> TaskLevelMCPManager:
    """获取或创建任务级 MCP 管理器"""
    if task_id not in _task_managers:
        _task_managers[task_id] = TaskLevelMCPManager(task_id)
    return _task_managers[task_id]


async def remove_task_mcp_manager(task_id: str):
    """移除任务级 MCP 管理器"""
    async with _managers_lock:
        if task_id in _task_managers:
            del _task_managers[task_id]
            logger.info(f"移除任务级 MCP 管理器: {task_id}")


async def cleanup_all_managers():
    """清理所有管理器"""
    async with _managers_lock:
        _task_managers.clear()
        logger.info("清理所有任务级 MCP 管理器")
