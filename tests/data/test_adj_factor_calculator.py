"""前复权因子归一化单元测试（P0-14 回归）。

背景：``calculate_from_corporate_actions`` 在循环内为 ``fore_adj_factor``
赋的值与 ``adj_factor`` 相同（向后累积），导致前复权价格下游消费时基准
错误。修复后引入 ``_normalize_fore_adj_factor`` 在 return 前做"最新一日=1.0"
归一化，``adj_factor`` 保留原始累积值。

本测试覆盖 4 类典型公司行为 + 混合序列：
1. 纯现金分红
2. 纯送股
3. 纯拆股
4. 混合多事件序列（送股 + 分红 + 拆股）

核心契约：
- ``result[-1]["fore_adj_factor"] == 1.0``（最新一日归一化）
- ``result[-1]["adj_factor"]`` 保留累积值（≠ 1.0）
- ``fore_adj_factor`` 序列单调性：越早的事件，fore 越偏离 1.0（除权越深）
"""

import pytest

from app.data.processor.post_processors.adj_factor_calculator import (
    AdjFactorCalculator,
    _normalize_fore_adj_factor,
)


# ── _normalize_fore_adj_factor 直接单测 ────────────────────────


class TestNormalizeForeAdjFactorUnit:
    """直接验证归一化函数行为（in-place）。"""

    def test_empty_list_noop(self):
        # 空列表不应抛错
        _normalize_fore_adj_factor([])
        assert True

    def test_latest_factor_one_already_noop(self):
        rows = [
            {"symbol": "X", "fore_adj_factor": 1.5, "adj_factor": 1.5},
            {"symbol": "X", "fore_adj_factor": 1.0, "adj_factor": 1.0},
        ]
        _normalize_fore_adj_factor(rows)
        # 最新一日已是 1.0，归一化系数也是 1.0，row[0] 保持不变
        assert rows[-1]["fore_adj_factor"] == pytest.approx(1.0)
        assert rows[0]["fore_adj_factor"] == pytest.approx(1.5)

    def test_normalize_to_one_for_latest(self):
        rows = [
            {"symbol": "X", "fore_adj_factor": 0.5, "adj_factor": 0.5},
            {"symbol": "X", "fore_adj_factor": 0.8, "adj_factor": 0.8},
        ]
        _normalize_fore_adj_factor(rows)
        # norm = 1.0 / 0.8 = 1.25
        assert rows[-1]["fore_adj_factor"] == pytest.approx(1.0)
        assert rows[0]["fore_adj_factor"] == pytest.approx(0.5 * 1.25)

    def test_zero_latest_factor_skipped(self):
        """最新一日 factor ≤ 0 时应静默跳过（不做归一化）。"""
        rows = [
            {"symbol": "X", "fore_adj_factor": 0.5, "adj_factor": 0.5},
            {"symbol": "X", "fore_adj_factor": 0.0, "adj_factor": 0.0},
        ]
        _normalize_fore_adj_factor(rows)
        # 未归一化
        assert rows[-1]["fore_adj_factor"] == 0.0
        assert rows[0]["fore_adj_factor"] == 0.5


# ── 端到端：calculate_from_corporate_actions ────────────────────


class TestCalculateFromCorporateActionsNormalize:
    """验证同步版本返回结果中最新一日 fore_adj_factor == 1.0。"""

    def setup_method(self):
        self.calc = AdjFactorCalculator()

    def test_empty_actions(self):
        assert self.calc.calculate_from_corporate_actions([]) == []

    def test_pure_cash_dividend(self):
        """纯现金分红序列：fore_adj_factor 最新一日应为 1.0。"""
        actions = [
            {"symbol": "000001", "ex_date": "2024-06-15",
             "action_type": "cash_dividend", "amount": 0.5, "prev_close": 10.0},
            {"symbol": "000001", "ex_date": "2024-12-15",
             "action_type": "cash_dividend", "amount": 0.4, "prev_close": 12.0},
        ]
        result = self.calc.calculate_from_corporate_actions(actions)

        assert len(result) == 2
        # 最新一日归一化
        assert result[-1]["fore_adj_factor"] == pytest.approx(1.0, abs=1e-6)
        # adj_factor 保留向后累积（< 1.0 表示价值下降）
        assert result[-1]["adj_factor"] < 1.0
        # 分红让 factor 减少（<1）；归一化系数 = 1/latest > 1，
        # 所以最早一日的 fore_adj_factor = 早factor / latest_factor > 1.0
        # 这意味着最早一日的前复权价 > 原始价（把后面分红的稀释效应"补回"）
        assert result[0]["fore_adj_factor"] > result[-1]["fore_adj_factor"]

    def test_pure_bonus_issue(self):
        """纯送股：10 送 10 应让 factor 减半。"""
        actions = [
            {"symbol": "000002", "ex_date": "2023-06-15",
             "action_type": "bonus_issue", "ratio_from": 10, "ratio_to": 10},
            {"symbol": "000002", "ex_date": "2024-06-15",
             "action_type": "bonus_issue", "ratio_from": 10, "ratio_to": 5},
        ]
        result = self.calc.calculate_from_corporate_actions(actions)

        assert len(result) == 2
        assert result[-1]["fore_adj_factor"] == pytest.approx(1.0, abs=1e-6)
        # 第一次：factor *= 10/20 = 0.5
        # 第二次：factor *= 10/15 ≈ 0.6667 → 0.5 * 0.6667 ≈ 0.3333
        # 归一化后：row[0] = 0.5 / 0.3333 = 1.5
        assert result[-1]["adj_factor"] == pytest.approx(1.0 / 3, abs=1e-3)
        assert result[0]["fore_adj_factor"] == pytest.approx(1.5, abs=1e-3)

    def test_pure_stock_split(self):
        """纯拆股：1 拆 10 应让 factor 放大 10 倍。"""
        actions = [
            {"symbol": "AAPL", "ex_date": "2020-08-31",
             "action_type": "stock_split", "ratio_from": 1, "ratio_to": 4},
            {"symbol": "AAPL", "ex_date": "2024-02-01",
             "action_type": "stock_split", "ratio_from": 1, "ratio_to": 5},
        ]
        result = self.calc.calculate_from_corporate_actions(actions)

        assert len(result) == 2
        assert result[-1]["fore_adj_factor"] == pytest.approx(1.0, abs=1e-6)
        # 第一次：factor *= 4 → 4
        # 第二次：factor *= 5 → 20
        assert result[-1]["adj_factor"] == pytest.approx(20.0, abs=1e-3)
        # 归一化后 row[0] = 4 / 20 = 0.2
        assert result[0]["fore_adj_factor"] == pytest.approx(0.2, abs=1e-3)

    def test_mixed_actions_sequence(self):
        """混合事件序列：送股 + 分红 + 拆股。

        数学预期：
            row[0] factor = 10/15 ≈ 0.6667（送股）
            row[1] factor = 0.6667 * 1475/1500 ≈ 0.6556（分红）
            row[2] factor = 0.6556 * 2 ≈ 1.3111（拆股）
            norm = 1.0 / 1.3111 ≈ 0.7627
            row[0] fore ≈ 0.5085；row[1] fore ≈ 0.5000；row[2] fore = 1.0
        注意拆股放大效应会让 row[0] > row[1]，因此序列并非严格单调，
        早期事件 fore 偏离 1.0 的程度取决于事件类型组合。
        """
        actions = [
            {"symbol": "600519", "ex_date": "2022-06-20",
             "action_type": "bonus_issue", "ratio_from": 10, "ratio_to": 5},
            {"symbol": "600519", "ex_date": "2023-06-20",
             "action_type": "cash_dividend", "amount": 25.0, "prev_close": 1500.0},
            {"symbol": "600519", "ex_date": "2024-06-20",
             "action_type": "stock_split", "ratio_from": 1, "ratio_to": 2},
        ]
        result = self.calc.calculate_from_corporate_actions(actions)

        assert len(result) == 3
        # 核心契约：最新一日归一化为 1.0
        assert result[-1]["fore_adj_factor"] == pytest.approx(1.0, abs=1e-6)
        # adj_factor 是原始累积值（最终累积 ≈ 1.3111，≠ 1.0）
        assert result[-1]["adj_factor"] == pytest.approx(1.3111, abs=1e-2)
        # 各事件 fore_adj_factor 符合数学预期
        assert result[0]["fore_adj_factor"] == pytest.approx(0.5085, abs=1e-2)
        assert result[1]["fore_adj_factor"] == pytest.approx(0.5000, abs=1e-2)
        # 关键契约：所有行的 fore_adj_factor 都 > 0（无零除/负值）
        for row in result:
            assert row["fore_adj_factor"] > 0
            assert row["adj_factor"] > 0


# ── 异步版本同样验证 ────────────────────────────────


class TestCalculateAsyncNormalize:
    """异步版本同样应归一化（与同步版本契约一致）。"""

    def setup_method(self):
        self.calc = AdjFactorCalculator()

    @pytest.mark.asyncio
    async def test_async_returns_normalized(self):
        actions = [
            {"symbol": "000001", "ex_date": "2024-06-15",
             "action_type": "bonus_issue", "ratio_from": 10, "ratio_to": 10},
            {"symbol": "000001", "ex_date": "2024-12-15",
             "action_type": "cash_dividend", "amount": 0.5, "prev_close": 10.0},
        ]
        result = await self.calc.calculate_from_corporate_actions_async(actions)

        assert len(result) == 2
        assert result[-1]["fore_adj_factor"] == pytest.approx(1.0, abs=1e-6)
        assert result[-1]["adj_factor"] < 1.0

    @pytest.mark.asyncio
    async def test_async_with_empty_actions(self):
        result = await self.calc.calculate_from_corporate_actions_async([])
        assert result == []


# ── 多 symbol 不交叉污染（隐含契约：每个调用是单 symbol 序列）────────


class TestSingleSymbolSemantics:
    """calculate_from_corporate_actions 设计为单 symbol 调用，
    归一化只作用于传入的 list，不会跨调用污染。"""

    def test_two_independent_calls_dont_share_state(self):
        actions_a = [
            {"symbol": "A", "ex_date": "2024-06-15",
             "action_type": "bonus_issue", "ratio_from": 10, "ratio_to": 10},
        ]
        actions_b = [
            {"symbol": "B", "ex_date": "2024-06-15",
             "action_type": "stock_split", "ratio_from": 1, "ratio_to": 10},
        ]
        result_a = AdjFactorCalculator().calculate_from_corporate_actions(actions_a)
        result_b = AdjFactorCalculator().calculate_from_corporate_actions(actions_b)

        # A: factor *= 0.5 → 归一化（只有一条）= 1.0
        assert result_a[-1]["fore_adj_factor"] == pytest.approx(1.0, abs=1e-6)
        assert result_a[-1]["adj_factor"] == pytest.approx(0.5, abs=1e-3)

        # B: factor *= 10 → 归一化 = 1.0
        assert result_b[-1]["fore_adj_factor"] == pytest.approx(1.0, abs=1e-6)
        assert result_b[-1]["adj_factor"] == pytest.approx(10.0, abs=1e-3)
