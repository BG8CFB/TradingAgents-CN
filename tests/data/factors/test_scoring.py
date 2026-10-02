"""行业内分位排名 + 风格评分合成测试（构造已知数据验证）。"""
import math

import pandas as pd

from app.data.factors.scoring import rank_factors_by_industry, compute_style_scores

GROUPS = {
    "momentum": ["ret_5d", "ret_20d"],
    "valuation": ["pe_ttm_percentile"],
}
FACTORS = [f for fs in GROUPS.values() for f in fs]
WEIGHTS = {
    "short_term": {"momentum": 1.0},
    "value": {"valuation": 1.0},
}


def _df():
    # 两行业各 2 股：银行内 ret_5d 高者得高分；pe 分位低者得高分（lower_better）
    return pd.DataFrame([
        {"symbol": "TEST001", "industry": "银行", "ret_5d": 5.0, "ret_20d": 10.0,
         "pe_ttm_percentile": 80.0},
        {"symbol": "TEST002", "industry": "银行", "ret_5d": 1.0, "ret_20d": 4.0,
         "pe_ttm_percentile": 20.0},
        {"symbol": "TEST003", "industry": "医药", "ret_5d": -2.0, "ret_20d": -5.0,
         "pe_ttm_percentile": 50.0},
        {"symbol": "TEST004", "industry": "医药", "ret_5d": 2.0, "ret_20d": 1.0,
         "pe_ttm_percentile": 50.0},
    ])


def test_industry_rank_direction():
    ranked = rank_factors_by_industry(_df(), FACTORS)
    by_sym = ranked.set_index("symbol")
    # 同行业内 ret_5d 高者 rank 高
    assert by_sym.loc["TEST001", "ret_5d_rank"] > by_sym.loc["TEST002", "ret_5d_rank"]
    # pe 分位 lower_better：TEST002(20) 应高于 TEST001(80)
    assert by_sym.loc["TEST002", "pe_ttm_percentile_rank"] > by_sym.loc["TEST001", "pe_ttm_percentile_rank"]
    # 行业内 rank 范围 (0, 100]
    assert 0 < by_sym["ret_5d_rank"].min() <= 100


def test_style_scores_weighted():
    df = rank_factors_by_industry(_df(), FACTORS)
    scored = compute_style_scores(df, GROUPS, WEIGHTS)
    by_sym = scored.set_index("symbol")
    # short_term = momentum 组内 ret_5d/ret_20d 均分加权，TEST001 在银行内两项都最高 → 100
    assert math.isclose(by_sym.loc["TEST001", "score_short_term"], 100.0, abs_tol=1e-6)
    # value = pe 分位单因子（lower_better）：2 股行业内 rank(pct)∈{50,100}，
    # 反转后最优股 = 100-50 = 50（两股行业反转上限即 50）
    assert math.isclose(by_sym.loc["TEST002", "score_value"], 50.0, abs_tol=1e-6)
    assert math.isclose(by_sym.loc["TEST001", "score_value"], 0.0, abs_tol=1e-6)


def test_missing_factor_renormalize():
    df = _df()
    df.loc[df["symbol"] == "TEST001", "ret_20d"] = None  # TEST001 缺 ret_20d
    scored = compute_style_scores(rank_factors_by_industry(df, FACTORS), GROUPS, WEIGHTS)
    by_sym = scored.set_index("symbol")
    # 可用因子归一：TEST001 的 short_term 只剩 ret_5d（行业内最高→100），归一后仍 100
    assert math.isclose(by_sym.loc["TEST001", "score_short_term"], 100.0, abs_tol=1e-6)
    # TEST002 的 ret_5d 是银行内最低（rank 非零）→ 缺失归一后分数为有限正值
    assert by_sym.loc["TEST002", "score_short_term"] > 0


def test_coverage_below_threshold_no_score():
    df = _df()
    # TEST003 两个动量因子都缺 → short_term 覆盖 0% < 30% → 不评分
    df.loc[df["symbol"] == "TEST003", ["ret_5d", "ret_20d"]] = None
    scored = compute_style_scores(rank_factors_by_industry(df, FACTORS), GROUPS, WEIGHTS)
    assert pd.isna(scored.set_index("symbol").loc["TEST003", "score_short_term"])
