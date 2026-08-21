"""模型级并发限流器测试（真线程/真协程，无 mock）

覆盖：
- acquire_sync FIFO 排队与 release 顺序
- alimit 在途峰值 ≤ limit（事件计数器断言）
- 跨事件循环共享同一 limiter（模拟多任务各自 asyncio.run）
- key/limit 无效时直通
"""

import asyncio
import threading
import time

import pytest

from app.llm.limiter import ModelLimiter, alimit, get_inflight, get_limiter


class TestModelLimiterSync:
    def test_acquire_up_to_limit_then_blocks(self):
        lim = ModelLimiter(2)
        assert lim.acquire_sync(timeout=0) is True
        assert lim.acquire_sync(timeout=0) is True
        # 第 3 个：无等待者路径超时返回 False（timeout=0 立即返回）
        assert lim.acquire_sync(timeout=0) is False

    def test_release_wakes_waiter_fifo(self):
        lim = ModelLimiter(1)
        assert lim.acquire_sync(timeout=0) is True
        order: list = []

        def _waiter(tag: str):
            # timeout 给足余量，确保走到被唤醒路径
            assert lim.acquire_sync(timeout=5.0) is True
            order.append(tag)

        t1 = threading.Thread(target=_waiter, args=("first",))
        t2 = threading.Thread(target=_waiter, args=("second",))
        t1.start()
        time.sleep(0.05)  # 保证入队顺序
        t2.start()
        time.sleep(0.05)
        lim.release()  # 唤醒 first
        t1.join(timeout=2)
        lim.release()  # 唤醒 second
        t2.join(timeout=2)
        assert order == ["first", "second"]

    def test_update_limit_grow_immediate(self):
        lim = ModelLimiter(1)
        assert lim.acquire_sync(timeout=0) is True
        lim.update_limit(3)
        assert lim.acquire_sync(timeout=0) is True
        assert lim.acquire_sync(timeout=0) is True
        assert lim.acquire_sync(timeout=0) is False


class TestAlimit:
    def test_none_key_passthrough(self):
        async def _run():
            async with alimit(None, 5):
                return 42

        assert asyncio.run(_run()) == 42

    def test_inflight_peak_capped(self):
        """10 协程并发过 limit=3 的限流器，在途峰值 ≤ 3"""
        peak = [0]
        current = [0]
        lock = threading.Lock()

        async def _worker():
            async with alimit("test|peak", 3):
                with lock:
                    current[0] += 1
                    peak[0] = max(peak[0], current[0])
                await asyncio.sleep(0.05)
                with lock:
                    current[0] -= 1

        async def _main():
            await asyncio.gather(*[_worker() for _ in range(10)])

        asyncio.run(_main())
        assert peak[0] <= 3
        assert peak[0] >= 2  # 确认并非退化成串行（留 1 个调度余量）
        assert get_inflight("test|peak") == 0  # 全部释放

    def test_shared_across_event_loops(self):
        """两个独立事件循环（模拟两个分析任务线程）共享同一 limiter 计数"""
        key = "test|crossloop"

        def _task(tag: str, barrier: threading.Barrier):
            async def _run():
                async with alimit(key, 2):
                    barrier.wait(timeout=5)  # 双方在途时同步
                    await asyncio.sleep(0.05)
                    return tag

            return asyncio.run(_run())

        barrier = threading.Barrier(2, timeout=5)
        t1 = threading.Thread(target=_task, args=("a", barrier))
        t2 = threading.Thread(target=_task, args=("b", barrier))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)
        # 同一 limiter 实例被两个 loop 复用，结束后在途归零
        assert get_inflight(key) == 0

    def test_registry_singleton_and_limit_update(self):
        m1 = get_limiter("test|singleton", 4)
        m2 = get_limiter("test|singleton", 4)
        assert m1 is m2
        # limit 变化经 update_limit 生效
        get_limiter("test|singleton", 6)
        assert m1.limit == 6


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
