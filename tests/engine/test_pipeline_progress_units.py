"""pipeline 计数式进度的纯函数测试

进度 = 已完成原子单元 / 总单元，等权计数、完成驱动；
percent 由 interpolate_percent 线性映射到服务层指定的区间。
"""

from app.engine.orchestrator.pipeline import compute_total_units, interpolate_percent


class TestComputeTotalUnits:
    def test_analysts_only(self):
        # 无 P2/P3：分析师 + Trader + Summary
        assert compute_total_units(4, phase2_enabled=False, phase2_rounds=1,
                                   phase3_enabled=False, phase3_rounds=1) == 6

    def test_phase2_only_rounds_1(self):
        # 4 分析师 + (2*(1+1)+1) + 1 Trader + 1 Summary
        assert compute_total_units(4, phase2_enabled=True, phase2_rounds=1,
                                   phase3_enabled=False, phase3_rounds=0) == 11

    def test_phase3_only_rounds_1(self):
        # 2 分析师 + 1 Trader + (3*(1+1)+1) + 1 Summary
        assert compute_total_units(2, phase2_enabled=False, phase2_rounds=0,
                                   phase3_enabled=True, phase3_rounds=1) == 11

    def test_phase2_and_phase3(self):
        # 3 分析师 + 5 + 1 + 7 + 1
        assert compute_total_units(3, phase2_enabled=True, phase2_rounds=1,
                                   phase3_enabled=True, phase3_rounds=1) == 17

    def test_rounds_0_still_runs_once(self):
        # rounds=0 表示 1 轮发言（rounds+1）：1 + 3 + 1 + 1 = 6
        assert compute_total_units(1, phase2_enabled=True, phase2_rounds=0,
                                   phase3_enabled=False, phase3_rounds=0) == 6

    def test_zero_analysts_defensive(self):
        # 0 分析师防御：仍有 Trader + Summary
        assert compute_total_units(0, phase2_enabled=False, phase2_rounds=1,
                                   phase3_enabled=False, phase3_rounds=1) == 2

    def test_negative_rounds_clamped(self):
        # 负轮次按 0 处理（1 轮发言）：与 rounds=0 相同
        assert compute_total_units(1, phase2_enabled=True, phase2_rounds=-3,
                                   phase3_enabled=False, phase3_rounds=0) == 6


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
