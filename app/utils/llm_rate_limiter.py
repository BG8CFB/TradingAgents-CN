"""
LLM 调用速率限制器

🔥 修复 S11: 添加 LLM 调用速率限制，防止成本失控和 API 限流

功能：
1. 基于令牌桶算法的速率限制
2. 支持按提供商配置不同的限制
3. 支持并发控制
4. 提供调用统计和成本估算
"""

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Any
from functools import wraps

logger = logging.getLogger("tradingagents.utils.llm_rate_limiter")


@dataclass
class RateLimitConfig:
    """速率限制配置"""
    # 每分钟最大请求数
    requests_per_minute: int = 60
    # 每分钟最大 token 数（估算）
    tokens_per_minute: int = 100000
    # 最大并发请求数
    max_concurrent: int = 5
    # 请求间最小间隔（秒）
    min_interval: float = 0.1
    # 是否启用
    enabled: bool = True


@dataclass
class CallStats:
    """调用统计"""
    total_calls: int = 0
    total_tokens_estimated: int = 0
    total_cost_estimated: float = 0.0
    failed_calls: int = 0
    rate_limited_calls: int = 0
    last_call_time: float = 0.0
    calls_this_minute: int = 0
    minute_start_time: float = field(default_factory=time.time)


# 默认的提供商速率限制配置
DEFAULT_RATE_LIMITS: Dict[str, RateLimitConfig] = {
    "openai": RateLimitConfig(requests_per_minute=60, tokens_per_minute=90000, max_concurrent=5),
    "deepseek": RateLimitConfig(requests_per_minute=60, tokens_per_minute=100000, max_concurrent=5),
    "dashscope": RateLimitConfig(requests_per_minute=100, tokens_per_minute=150000, max_concurrent=10),
    "google": RateLimitConfig(requests_per_minute=60, tokens_per_minute=100000, max_concurrent=5),
    "anthropic": RateLimitConfig(requests_per_minute=50, tokens_per_minute=80000, max_concurrent=3),
    "default": RateLimitConfig(requests_per_minute=30, tokens_per_minute=50000, max_concurrent=3),
}

# 估算的 token 成本（每 1000 tokens，美元）
TOKEN_COSTS: Dict[str, Dict[str, float]] = {
    "openai": {"input": 0.0015, "output": 0.002},
    "deepseek": {"input": 0.0001, "output": 0.0002},
    "dashscope": {"input": 0.0008, "output": 0.002},
    "google": {"input": 0.00025, "output": 0.0005},
    "anthropic": {"input": 0.003, "output": 0.015},
    "default": {"input": 0.001, "output": 0.002},
}


class LLMRateLimiter:
    """
    LLM 调用速率限制器
    
    使用令牌桶算法实现速率限制，支持：
    - 每分钟请求数限制
    - 并发请求数限制
    - 请求间隔控制
    """
    
    _instance: Optional["LLMRateLimiter"] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        self._configs: Dict[str, RateLimitConfig] = DEFAULT_RATE_LIMITS.copy()
        self._stats: Dict[str, CallStats] = {}
        self._semaphores: Dict[str, asyncio.Semaphore] = {}
        self._sync_semaphores: Dict[str, threading.Semaphore] = {}
        self._call_lock = threading.Lock()
        
        logger.info("[LLM速率限制] 初始化完成")
    
    def get_config(self, provider: str) -> RateLimitConfig:
        """获取提供商的速率限制配置"""
        return self._configs.get(provider.lower(), self._configs["default"])
    
    def set_config(self, provider: str, config: RateLimitConfig):
        """设置提供商的速率限制配置"""
        self._configs[provider.lower()] = config
        logger.info(f"[LLM速率限制] 更新 {provider} 配置: {config}")
    
    def get_stats(self, provider: str) -> CallStats:
        """获取提供商的调用统计"""
        if provider.lower() not in self._stats:
            self._stats[provider.lower()] = CallStats()
        return self._stats[provider.lower()]
    
    def _get_semaphore(self, provider: str) -> threading.Semaphore:
        """获取同步信号量"""
        provider = provider.lower()
        if provider not in self._sync_semaphores:
            config = self.get_config(provider)
            self._sync_semaphores[provider] = threading.Semaphore(config.max_concurrent)
        return self._sync_semaphores[provider]
    
    def _check_rate_limit(self, provider: str) -> bool:
        """
        检查是否超过速率限制
        
        Returns:
            True 如果可以继续，False 如果需要等待
        """
        config = self.get_config(provider)
        if not config.enabled:
            return True
        
        stats = self.get_stats(provider)
        current_time = time.time()
        
        # 检查是否需要重置分钟计数器
        if current_time - stats.minute_start_time >= 60:
            stats.calls_this_minute = 0
            stats.minute_start_time = current_time
        
        # 检查每分钟请求数
        if stats.calls_this_minute >= config.requests_per_minute:
            return False
        
        # 检查最小间隔
        if current_time - stats.last_call_time < config.min_interval:
            return False
        
        return True
    
    def _wait_for_rate_limit(self, provider: str, timeout: float = 60.0) -> bool:
        """
        等待直到可以发起请求
        
        Returns:
            True 如果成功获取配额，False 如果超时
        """
        config = self.get_config(provider)
        if not config.enabled:
            return True
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self._check_rate_limit(provider):
                return True
            time.sleep(0.1)
        
        return False
    
    def _record_call(self, provider: str, tokens_estimated: int = 0, success: bool = True):
        """记录一次调用"""
        with self._call_lock:
            stats = self.get_stats(provider)
            stats.total_calls += 1
            stats.calls_this_minute += 1
            stats.last_call_time = time.time()
            stats.total_tokens_estimated += tokens_estimated
            
            if not success:
                stats.failed_calls += 1
            
            # 估算成本
            costs = TOKEN_COSTS.get(provider.lower(), TOKEN_COSTS["default"])
            # 假设输入输出各占一半
            cost = (tokens_estimated / 1000) * (costs["input"] + costs["output"]) / 2
            stats.total_cost_estimated += cost
    
    def rate_limited_call(self, provider: str, func, *args, **kwargs):
        """
        执行速率限制的同步调用
        
        Args:
            provider: LLM 提供商名称
            func: 要调用的函数
            *args, **kwargs: 函数参数
        
        Returns:
            函数返回值
        """
        config = self.get_config(provider)
        
        if not config.enabled:
            return func(*args, **kwargs)
        
        # 获取并发信号量
        semaphore = self._get_semaphore(provider)
        
        # 等待速率限制
        if not self._wait_for_rate_limit(provider):
            stats = self.get_stats(provider)
            stats.rate_limited_calls += 1
            logger.warning(f"[LLM速率限制] {provider} 速率限制超时")
            raise RuntimeError(f"LLM rate limit exceeded for {provider}")
        
        # 执行调用
        acquired = semaphore.acquire(timeout=30)
        if not acquired:
            raise RuntimeError(f"LLM concurrent limit exceeded for {provider}")
        
        try:
            result = func(*args, **kwargs)
            
            # 估算 token 数（简单估算：每个字符约 0.5 token）
            tokens_estimated = 0
            if hasattr(result, 'content') and result.content:
                tokens_estimated = len(result.content) // 2
            
            self._record_call(provider, tokens_estimated, success=True)
            return result
        except Exception as e:
            self._record_call(provider, 0, success=False)
            raise
        finally:
            semaphore.release()
    
    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取所有提供商的统计信息"""
        result = {}
        for provider, stats in self._stats.items():
            result[provider] = {
                "total_calls": stats.total_calls,
                "total_tokens_estimated": stats.total_tokens_estimated,
                "total_cost_estimated": round(stats.total_cost_estimated, 4),
                "failed_calls": stats.failed_calls,
                "rate_limited_calls": stats.rate_limited_calls,
                "calls_this_minute": stats.calls_this_minute,
            }
        return result
    
    def reset_stats(self, provider: Optional[str] = None):
        """重置统计信息"""
        if provider:
            if provider.lower() in self._stats:
                self._stats[provider.lower()] = CallStats()
        else:
            self._stats.clear()
        logger.info(f"[LLM速率限制] 统计信息已重置: {provider or '全部'}")


# 全局实例
_rate_limiter: Optional[LLMRateLimiter] = None


def get_rate_limiter() -> LLMRateLimiter:
    """获取全局速率限制器实例"""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = LLMRateLimiter()
    return _rate_limiter


def rate_limited(provider: str):
    """
    装饰器：为函数添加速率限制
    
    用法：
        @rate_limited("openai")
        def call_openai(messages):
            return llm.invoke(messages)
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            limiter = get_rate_limiter()
            return limiter.rate_limited_call(provider, func, *args, **kwargs)
        return wrapper
    return decorator
