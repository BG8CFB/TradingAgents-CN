"""strategies.yaml 加载与校验测试。"""

from app.data.factors.strategy_config import (
    load_strategy_config, get_factor_groups, get_strategies,
)


def test_config_loads_and_shape():
    cfg = load_strategy_config()
    # 三套风格权重，权重和为 1
    weights = cfg["score_weights"]
    assert set(weights) == {"short_term", "balanced", "value"}
    for style, w in weights.items():
        assert abs(sum(w.values()) - 1.0) < 1e-6, style
    # 因子分组覆盖 spec 的 6 组
    groups = get_factor_groups()
    assert set(groups) == {"momentum", "trend", "volume", "flow", "valuation", "quality"}
    # 单因子权重上限：组权重/组内因子数 ≤ 40%（spec §8）
    max_factor_weight = max(
        w / len(groups[g]) for w, g in
        ((w, g) for style_w in weights.values() for g, w in style_w.items())
    )
    assert max_factor_weight <= 0.40
    # 6 个策略模板，id 唯一，恰有一个 default
    strategies = get_strategies()
    assert len(strategies) == 6
    ids = [s["id"] for s in strategies]
    assert len(set(ids)) == 6
    assert sum(1 for s in strategies if s.get("default")) == 1
    # 每个模板的 filters 字段都在因子/分组字段范围内
    known = {f for fs in groups.values() for f in fs}
    for s in strategies:
        assert s["style"] in weights
        for cond in s.get("filters", []):
            assert cond["field"] in known, (s["id"], cond["field"])
