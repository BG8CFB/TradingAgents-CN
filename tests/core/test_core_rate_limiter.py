"""
测试 app/core/rate_limiter.py — 速率限制器模块
"""

import asyncio
import time

import pytest

from app.core.rate_limiter import (
    RateLimiter,
    TushareRateLimiter,
    AKShareRateLimiter,
    BaoStockRateLimiter,
    get_tushare_rate_limiter,
    get_akshare_rate_limiter,
    get_baostock_rate_limiter,
    reset_all_limiters,
)


class TestRateLimiterInit:
    """测试 RateLimiter 初始化"""

    def test_init_with_correct_params(self):
        """正确初始化参数"""
        limiter = RateLimiter(max_calls=10, time_window=30, name="TestLimiter")
        assert limiter.max_calls == 10
        assert limiter.time_window == 30
        assert limiter.name == "TestLimiter"

    def test_init_default_name(self):
        """默认名称为 RateLimiter"""
        limiter = RateLimiter(max_calls=5, time_window=10)
        assert limiter.name == "RateLimiter"

    def test_init_calls_deque_empty(self):
        """初始时调用队列为空"""
        limiter = RateLimiter(max_calls=5, time_window=10)
        assert len(limiter.calls) == 0

    def test_init_stats_zero(self):
        """初始统计信息为零"""
        limiter = RateLimiter(max_calls=5, time_window=10)
        assert limiter.total_calls == 0
        assert limiter.total_waits == 0
        assert limiter.total_wait_time == 0.0


class TestRateLimiterAcquire:
    """测试 RateLimiter.acquire() 获取许可"""

    @pytest.mark.asyncio
    async def test_acquire_within_limit(self):
        """限制内的调用不被阻塞"""
        limiter = RateLimiter(max_calls=5, time_window=10)
        await limiter.acquire()
        assert limiter.total_calls == 1
        assert len(limiter.calls) == 1

    @pytest.mark.asyncio
    async def test_acquire_multiple_within_limit(self):
        """多次调用在限制内均成功"""
        limiter = RateLimiter(max_calls=5, time_window=10)
        for _ in range(5):
            await limiter.acquire()
        assert limiter.total_calls == 5
        assert len(limiter.calls) == 5

    @pytest.mark.asyncio
    async def test_acquire_tracks_timestamps(self):
        """acquire 记录的时间戳是递增的"""
        limiter = RateLimiter(max_calls=10, time_window=60)
        for _ in range(3):
            await limiter.acquire()
        timestamps = list(limiter.calls)
        assert timestamps == sorted(timestamps)


class TestRateLimiterStats:
    """测试 RateLimiter 统计功能"""

    @pytest.mark.asyncio
    async def test_get_stats_returns_correct_structure(self):
        """get_stats() 返回正确的结构"""
        limiter = RateLimiter(max_calls=10, time_window=60, name="StatsTest")
        await limiter.acquire()
        stats = limiter.get_stats()

        assert stats["name"] == "StatsTest"
        assert stats["max_calls"] == 10
        assert stats["time_window"] == 60
        assert stats["current_calls"] == 1
        assert stats["total_calls"] == 1
        assert stats["total_waits"] == 0
        assert stats["total_wait_time"] == 0.0
        assert stats["avg_wait_time"] == 0

    @pytest.mark.asyncio
    async def test_get_stats_avg_wait_time_calculation(self):
        """avg_wait_time 正确计算"""
        limiter = RateLimiter(max_calls=10, time_window=60)
        limiter.total_waits = 2
        limiter.total_wait_time = 1.0
        stats = limiter.get_stats()
        assert stats["avg_wait_time"] == 0.5

    @pytest.mark.asyncio
    async def test_reset_stats_clears_all(self):
        """reset_stats() 清除所有统计"""
        limiter = RateLimiter(max_calls=5, time_window=10)
        await limiter.acquire()
        await limiter.acquire()
        assert limiter.total_calls == 2

        limiter.reset_stats()
        assert limiter.total_calls == 0
        assert limiter.total_waits == 0
        assert limiter.total_wait_time == 0.0

    @pytest.mark.asyncio
    async def test_reset_stats_does_not_clear_calls_deque(self):
        """reset_stats() 不清除调用记录队列"""
        limiter = RateLimiter(max_calls=5, time_window=10)
        await limiter.acquire()
        limiter.reset_stats()
        # calls deque 不受 reset_stats 影响
        assert len(limiter.calls) == 1


class TestTushareRateLimiter:
    """测试 TushareRateLimiter"""

    def test_standard_tier(self):
        """standard 等级使用正确的限制"""
        limiter = TushareRateLimiter(tier="standard", safety_margin=1.0)
        assert limiter.max_calls == 400
        assert limiter.time_window == 60

    def test_free_tier(self):
        """free 等级使用正确的限制"""
        limiter = TushareRateLimiter(tier="free", safety_margin=1.0)
        assert limiter.max_calls == 100

    def test_vip_tier(self):
        """vip 等级使用正确的限制"""
        limiter = TushareRateLimiter(tier="vip", safety_margin=1.0)
        assert limiter.max_calls == 800

    def test_safety_margin_applied(self):
        """安全边际正确应用"""
        limiter = TushareRateLimiter(tier="standard", safety_margin=0.8)
        # 400 * 0.8 = 320
        assert limiter.max_calls == 320

    def test_safety_margin_half(self):
        """50% 安全边际"""
        limiter = TushareRateLimiter(tier="free", safety_margin=0.5)
        # 100 * 0.5 = 50
        assert limiter.max_calls == 50

    def test_unknown_tier_falls_back_to_standard(self):
        """未知等级回退到 standard"""
        limiter = TushareRateLimiter(tier="unknown_tier", safety_margin=1.0)
        assert limiter.max_calls == 400  # standard 的值
        assert limiter.tier == "standard"

    def test_name_includes_tier(self):
        """名称包含等级信息"""
        limiter = TushareRateLimiter(tier="premium", safety_margin=1.0)
        assert "premium" in limiter.name

    def test_stores_tier_and_margin(self):
        """存储 tier 和 safety_margin"""
        limiter = TushareRateLimiter(tier="basic", safety_margin=0.9)
        assert limiter.tier == "basic"
        assert limiter.safety_margin == 0.9


class TestAKShareRateLimiter:
    """测试 AKShareRateLimiter"""

    def test_default_params(self):
        """默认参数为 60 次/60 秒"""
        limiter = AKShareRateLimiter()
        assert limiter.max_calls == 60
        assert limiter.time_window == 60

    def test_name(self):
        """名称为 AKShareRateLimiter"""
        limiter = AKShareRateLimiter()
        assert limiter.name == "AKShareRateLimiter"

    def test_custom_params(self):
        """自定义参数"""
        limiter = AKShareRateLimiter(max_calls=30, time_window=30)
        assert limiter.max_calls == 30
        assert limiter.time_window == 30


class TestBaoStockRateLimiter:
    """测试 BaoStockRateLimiter"""

    def test_default_params(self):
        """默认参数为 100 次/60 秒"""
        limiter = BaoStockRateLimiter()
        assert limiter.max_calls == 100
        assert limiter.time_window == 60

    def test_name(self):
        """名称为 BaoStockRateLimiter"""
        limiter = BaoStockRateLimiter()
        assert limiter.name == "BaoStockRateLimiter"

    def test_custom_params(self):
        """自定义参数"""
        limiter = BaoStockRateLimiter(max_calls=50, time_window=30)
        assert limiter.max_calls == 50
        assert limiter.time_window == 30


class TestGlobalLimiterSingletons:
    """测试全局限制器单例"""

    def setup_method(self):
        """每个测试前重置全局实例"""
        reset_all_limiters()

    def teardown_method(self):
        """每个测试后清理"""
        reset_all_limiters()

    def test_get_tushare_rate_limiter_returns_singleton(self):
        """get_tushare_rate_limiter 返回单例"""
        limiter1 = get_tushare_rate_limiter()
        limiter2 = get_tushare_rate_limiter()
        assert limiter1 is limiter2

    def test_get_tushare_rate_limiter_type(self):
        """get_tushare_rate_limiter 返回 TushareRateLimiter 实例"""
        limiter = get_tushare_rate_limiter()
        assert isinstance(limiter, TushareRateLimiter)

    def test_get_akshare_rate_limiter_returns_singleton(self):
        """get_akshare_rate_limiter 返回单例"""
        limiter1 = get_akshare_rate_limiter()
        limiter2 = get_akshare_rate_limiter()
        assert limiter1 is limiter2

    def test_get_baostock_rate_limiter_returns_singleton(self):
        """get_baostock_rate_limiter 返回单例"""
        limiter1 = get_baostock_rate_limiter()
        limiter2 = get_baostock_rate_limiter()
        assert limiter1 is limiter2

    def test_reset_all_limiters_clears_instances(self):
        """reset_all_limiters 清除所有全局实例"""
        # 先创建实例
        get_tushare_rate_limiter()
        get_akshare_rate_limiter()
        get_baostock_rate_limiter()
        # 重置
        reset_all_limiters()
        # 验证新获取的不是之前的实例
        import app.core.rate_limiter as mod
        assert mod._tushare_limiter is None
        assert mod._akshare_limiter is None
        assert mod._baostock_limiter is None

    def test_reset_all_limiters_creates_new_after_reset(self):
        """重置后再获取会创建新实例"""
        limiter_old = get_tushare_rate_limiter()
        reset_all_limiters()
        limiter_new = get_tushare_rate_limiter()
        assert limiter_old is not limiter_new
