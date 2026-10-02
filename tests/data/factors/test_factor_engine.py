"""因子引擎数值正确性测试：种子数据 → 计算 → 与独立手算对比。"""
import math

import pytest

pytestmark = pytest.mark.requires_db

from app.data.factors.engine import FactorScoreEngine
from tests.data.conftest import _cleanup_factor_seeds, _seed_factor_stocks


async def test_factor_values_match_hand_calc(real_mongo_db, seed_factor_inputs):
    db = real_mongo_db
    dates = seed_factor_inputs["dates"]

    # ST 股（name 含 "ST" 子串应被剔除）：先清残留再种，验证过滤生效
    await _cleanup_factor_seeds(db, ["TESTF003"])
    await _seed_factor_stocks(db, {
        "TESTF003": {
            "name": "ST测试", "industry": "电子",
            "close": [20.0] * 130, "turnover": [1.0] * 130,
            "volume": 800_000, "amount": 20_000_000,
            "pe": 40.0, "pb": 3.0, "dv": 0.0, "vr": 1.0,
            "inflow": 0.0, "np_prev": 10.0, "np_cur": 8.0,
            "roe": 2.0, "gm": 8.0, "dr": 80.0,
        },
    }, dates)

    engine = FactorScoreEngine()
    df = await engine.compute_factors("CN")
    got = df.set_index("symbol")
    assert "TESTF003" not in got.index, "ST 股应被引擎剔除"

    # ── 手算断言（TESTF001，行情窗口=种子后 120 日）──
    c = seed_factor_inputs["cfg"]["TESTF001"]["close"]
    # ret_k：k 日收益 = close[-1]/close[-(k+1)]-1
    assert math.isclose(got.loc["TESTF001", "ret_5d"], (c[-1] / c[-6] - 1) * 100, rel_tol=1e-6)
    assert math.isclose(got.loc["TESTF001", "ret_20d"], (c[-1] / c[-21] - 1) * 100, rel_tol=1e-6)
    assert math.isclose(got.loc["TESTF001", "ret_60d"], (c[-1] / c[-61] - 1) * 100, rel_tol=1e-6)
    # dist_to_60d_high = (60日最高/现价 - 1)×100 = 0（最后一天即最高）
    assert math.isclose(got.loc["TESTF001", "dist_to_60d_high"], 0.0, abs_tol=1e-9)
    # bias_ma20 = (close/ma20-1)×100
    ma20 = sum(c[-20:]) / 20
    assert math.isclose(got.loc["TESTF001", "bias_ma20"], (c[-1] / ma20 - 1) * 100, rel_tol=1e-6)
    # ma20_slope = (ma20[-1]/ma20[-5]-1)×100
    ma20_prev = sum(c[-25:-5]) / 20
    assert math.isclose(got.loc["TESTF001", "ma20_slope"], (ma20 / ma20_prev - 1) * 100, rel_tol=1e-6)
    # turnover_amp 已改成交量口径：尾日 2M / 前 20 日均 1M = 2（与换手率口径等价）
    assert math.isclose(got.loc["TESTF001", "turnover_amp"], 2.0, rel_tol=1e-6)
    # volume 前 129 日持平、尾日放大 → 连续放量仅 1 天
    assert got.loc["TESTF001", "consecutive_vol_up_days"] == 1
    # 财务直取 + yoy
    assert math.isclose(got.loc["TESTF001", "net_profit_yoy"], 30.0, rel_tol=1e-6)
    assert got.loc["TESTF001", "roe"] == 18.0
    # 资金：5 日累计 = 5×1000万
    assert math.isclose(got.loc["TESTF001", "main_inflow_5d"], 50_000_000.0, rel_tol=1e-6)
    # main_inflow_5d_pct = 5×1000万 / (5×5000万) ×100 = 20
    assert math.isclose(got.loc["TESTF001", "main_inflow_5d_pct"], 20.0, rel_tol=1e-6)
    # 估值：pe 全窗口恒定 → 当前值不小于窗口内所有值 → 分位 = 100
    assert got.loc["TESTF001", "pe_ttm_percentile"] == 100.0
    assert got.loc["TESTF001", "dividend_yield"] == 3.0
    assert got.loc["TESTF001", "volume_ratio"] == 1.8
    # 三风格分已生成；两行业各 1 股 → 单股行业内 rank 恒 100，
    # 但 dist_to_60d_high 属 lower_better（反转后单股=0），手算：
    # momentum 组均 = (100×3 + 0)/4 = 75 → short_term = 0.35×75 + 0.25×100
    #                + 0.20×100 + 0.20×100 = 91.25
    for col in ("score_short_term", "score_balanced", "score_value"):
        assert not math.isnan(got.loc["TESTF001", col])
    assert math.isclose(got.loc["TESTF001", "score_short_term"], 91.25, abs_tol=1e-6)

    # macd_golden_days：全程上行 dif>dea 持续 → 正；下行 → 负
    assert got.loc["TESTF001", "macd_golden_days"] > 0
    assert got.loc["TESTF002", "macd_golden_days"] < 0

    await _cleanup_factor_seeds(db, ["TESTF003"])
