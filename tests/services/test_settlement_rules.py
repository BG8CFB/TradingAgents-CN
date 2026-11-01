"""结算规则纯函数测试：板块推断、涨跌停幅差、一字板判定、信号/置信度归一、Wilson 区间。"""

import pytest

from app.services.settlement_service import (
    board_limit_pct,
    infer_board,
    is_limit_unfillable,
    normalize_signal,
    to_confidence,
    wilson_ci,
)


class TestInferBoard:
    @pytest.mark.parametrize(
        ("symbol", "expected"),
        [
            ("600519", "主板"),
            ("000001", "主板"),
            ("300750", "创业板"),
            ("301050", "创业板"),
            ("688981", "科创板"),
            ("830799", "北交所"),
            ("920001", "北交所"),
            ("430047", "北交所"),
            ("999990", "主板"),
        ],
    )
    def test_infer_board(self, symbol, expected):
        assert infer_board(symbol) == expected


class TestBoardLimitPct:
    def test_main_board_10(self):
        assert board_limit_pct("主板", False) == 10.0

    def test_st_main_board_5(self):
        assert board_limit_pct("主板", True) == 5.0

    def test_chinext_st_keeps_20(self):
        assert board_limit_pct("创业板", True) == 20.0

    def test_star_20(self):
        assert board_limit_pct("科创板", False) == 20.0

    def test_bse_30(self):
        assert board_limit_pct("北交所", False) == 30.0

    def test_unknown_no_limit(self):
        assert board_limit_pct(None, False) is None
        assert board_limit_pct("港股主板", False) is None


class TestLimitUnfillable:
    def test_buy_limit_up_one_word(self):
        # 主板 10%：昨收 10 → 涨停 11.0，一字开盘且全天无波动
        assert is_limit_unfillable(11.0, 11.0, 11.0, 10.0, "Buy", 10.0) is True

    def test_buy_limit_up_with_intraday_range(self):
        # 开盘即涨停但盘中有波动（非一字）→ 可成交
        assert is_limit_unfillable(11.0, 11.5, 10.8, 10.0, "Buy", 10.0) is False

    def test_buy_rounding_to_two_decimals(self):
        # 昨收 9.87 → 涨停 round(10.857)=10.86
        assert is_limit_unfillable(10.86, 10.86, 10.86, 9.87, "Buy", 10.0) is True
        assert is_limit_unfillable(10.85, 10.85, 10.85, 9.87, "Buy", 10.0) is False

    def test_buy_limit_down_not_blocking_buy(self):
        # Buy 信号遇一字跌停：开盘价远离涨停价 → 可成交
        assert is_limit_unfillable(9.0, 9.0, 9.0, 10.0, "Buy", 10.0) is False

    def test_sell_limit_down_one_word(self):
        assert is_limit_unfillable(9.0, 9.0, 9.0, 10.0, "Sell", 10.0) is True

    def test_sell_limit_up_not_blocking_sell(self):
        assert is_limit_unfillable(11.0, 11.0, 11.0, 10.0, "Sell", 10.0) is False

    def test_bse_30_percent(self):
        assert is_limit_unfillable(13.0, 13.0, 13.0, 10.0, "Buy", 30.0) is True
        assert is_limit_unfillable(12.99, 12.99, 12.99, 10.0, "Buy", 30.0) is False

    def test_missing_fields_not_unfillable(self):
        assert is_limit_unfillable(None, 11.0, 11.0, 10.0, "Buy", 10.0) is False
        assert is_limit_unfillable(11.0, 11.0, 11.0, None, "Buy", 10.0) is False

    def test_hold_never_unfillable(self):
        assert is_limit_unfillable(11.0, 11.0, 11.0, 10.0, "Hold", 10.0) is False


class TestNormalizeSignal:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Buy", "Buy"),
            ("buy", "Buy"),
            ("BUY ", "Buy"),
            ("买入", "Buy"),
            ("看多", "Buy"),
            ("Sell", "Sell"),
            ("卖出", "Sell"),
            ("Hold", "Hold"),
            ("持有", "Hold"),
            ("观望", "Hold"),
            ("中性", "Hold"),
        ],
    )
    def test_known_signals(self, raw, expected):
        assert normalize_signal(raw) == expected

    @pytest.mark.parametrize("raw", ["减持", "", None, 123, ""])
    def test_unknown_signals_return_none(self, raw):
        assert normalize_signal(raw) is None


class TestToConfidence:
    def test_fraction_scaled_to_100(self):
        assert to_confidence(0.85) == 85.0

    def test_absolute_0_100_kept(self):
        assert to_confidence(65) == 65.0
        assert to_confidence("72") == 72.0

    def test_zero(self):
        assert to_confidence(0) == 0.0

    def test_clamped(self):
        assert to_confidence(150) == 100.0
        assert to_confidence(-5) == 0.0

    def test_invalid(self):
        assert to_confidence(None) is None
        assert to_confidence("abc") is None


class TestWilsonCi:
    def test_empty_returns_none(self):
        assert wilson_ci(0, 0) is None

    def test_contains_point_estimate(self):
        ci = wilson_ci(8, 10)
        assert ci is not None
        assert ci["low"] <= 0.8 <= ci["high"]
        assert 0.0 <= ci["low"] <= ci["high"] <= 1.0

    def test_zero_hits(self):
        ci = wilson_ci(0, 10)
        assert ci["low"] == 0.0
        assert ci["high"] <= 0.3   # 0/10 的 Wilson 上界约 0.28（rule of three ≈ 0.3）
