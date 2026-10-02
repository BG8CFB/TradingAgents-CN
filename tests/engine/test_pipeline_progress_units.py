"""pipeline 进度映射的纯函数测试

总单元公式已迁 CompiledPlan.total_units（tests/engine/workflow/test_compiler_plan.py，
2026-09 编排重写）；本文件保留 percent 线性映射断言：
percent 由 interpolate_percent 线性映射到服务层指定的区间。
"""

from app.engine.orchestrator.pipeline import interpolate_percent


class TestInterpolatePercent:
    def test_start(self):
        assert interpolate_percent(0, 8, 15, 92) == 15

    def test_completion_hits_hi(self):
        assert interpolate_percent(8, 8, 15, 92) == 92

    def test_midpoint(self):
        assert interpolate_percent(4, 8, 15, 92) == 15 + round(0.5 * 77)

    def test_default_range(self):
        assert interpolate_percent(3, 10, 0, 100) == 30

    def test_zero_total_defensive(self):
        assert interpolate_percent(1, 0, 15, 92) == 15
        assert interpolate_percent(1, -1, 15, 92) == 15

    def test_overcount_clamps_to_hi(self):
        assert interpolate_percent(12, 8, 15, 92) == 92

    def test_monotonic(self):
        prev = -1
        for completed in range(0, 9):
            pct = interpolate_percent(completed, 8, 15, 92)
            assert pct >= prev
            prev = pct
