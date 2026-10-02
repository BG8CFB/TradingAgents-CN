"""因子行业内分位排名与风格评分合成（纯 pandas，无 IO）。

评分口径（spec §8）：
1. 每因子在行业内 percentile rank（消除行业偏差）
2. lower_better 因子反转（rank → 100-rank），统一为越大越好
3. 风格评分 = Σ(组权重 × 组内可用因子平均分)，按可用因子归一
4. 因子覆盖 < 30% 的股票该风格不评分（score=None）
"""

from typing import Dict, List

import numpy as np
import pandas as pd

# 值越小越好的因子（行业内 rank 后反转）
LOWER_BETTER_FACTORS = {
    "pe_ttm_percentile", "pb_percentile", "debt_ratio", "dist_to_60d_high",
}

MIN_COVERAGE_RATIO = 0.30


def rank_factors_by_industry(df: pd.DataFrame,
                             factor_fields: List[str]) -> pd.DataFrame:
    """每因子行业内 pct rank ×100；lower_better 反转。产出 <f>_rank 列。"""
    out = df.copy()
    grouped = out.groupby("industry", group_keys=False)
    for f in factor_fields:
        if f not in out.columns:
            out[f] = np.nan
        rank = grouped[f].rank(pct=True) * 100.0
        if f in LOWER_BETTER_FACTORS:
            rank = 100.0 - rank
        out[f"{f}_rank"] = rank
    return out


def compute_style_scores(df: pd.DataFrame,
                         factor_groups: Dict[str, List[str]],
                         style_weights: Dict[str, Dict[str, float]]) -> pd.DataFrame:
    """对 rank 后的 DataFrame 追加 score_<style> 列（0-100，覆盖不足为 NaN）。"""
    out = df.copy()
    all_factors = [f for fs in factor_groups.values() for f in fs]
    rank_cols = {f: f"{f}_rank" for f in all_factors}

    for style, groups_w in style_weights.items():
        style_factors = [f for g, w in groups_w.items() if w > 0
                         for f in factor_groups[g]]
        # 覆盖率：该风格涉及因子中非 NaN 的比例
        avail = out[[rank_cols[f] for f in style_factors]].notna()
        coverage = avail.mean(axis=1)
        score = pd.Series(np.nan, index=out.index, dtype=float)
        eligible = coverage >= MIN_COVERAGE_RATIO
        if eligible.any():
            # 每因子加权分：组权重在组内均分；行级按可用因子归一
            weighted_sum = pd.Series(0.0, index=out.index)
            weight_sum = pd.Series(0.0, index=out.index)
            for group, gw in groups_w.items():
                if gw <= 0:
                    continue
                members = factor_groups[group]
                fw = gw / len(members)  # 组内均分
                for f in members:
                    rc = out[rank_cols[f]]
                    valid = rc.notna()
                    weighted_sum = weighted_sum + rc.fillna(0.0) * fw * valid
                    weight_sum = weight_sum + fw * valid
            norm = weighted_sum / weight_sum.replace(0.0, np.nan)
            score = norm.where(eligible)
        out[f"score_{style}"] = score
    return out
