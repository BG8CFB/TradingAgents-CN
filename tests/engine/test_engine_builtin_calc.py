"""内置计算工具测试（真实调用，禁 mock）

覆盖：表达式求值正确性/安全防护、百分比字面量、每个金融函数的已知答案、
Decimal 精度与舍入、func_to_tooldef 的 schema 映射。
"""

from decimal import Decimal

import pytest

from app.engine.tools.builtin.calc import (
    CALC_ENFORCEMENT_PROMPT,
    _BATCH_MAX_TASKS,
    _BATCH_OPS,
    _eval_expression,
    _q4,
    bollinger,
    calc_batch,
    calc_expression,
    calc_pnl,
    calc_tool_defs,
    cagr,
    compound,
    ema,
    max_drawdown,
    moving_average,
    pct_change,
    position_size,
    risk_reward,
    sharpe_ratio,
    var_95,
    volatility,
)
from app.llm.tools.wrappers import func_to_tooldef


# ──────────────────────────────────────────────────────────────
# 表达式求值
# ──────────────────────────────────────────────────────────────


class TestExpression:
    def test_basic_arithmetic(self):
        assert _eval_expression("1 + 2 * 3") == Decimal(7)
        assert _eval_expression("(10 - 4) / 3") == Decimal("2")
        assert _eval_expression("2 ** 10") == Decimal(1024)
        assert _eval_expression("7 // 2") == Decimal(4)
        assert _eval_expression("7 % 3") == Decimal(1)
        assert _eval_expression("-5 + 3") == Decimal(-2)

    def test_percent_literal(self):
        assert _eval_expression("50% * 80000") == Decimal(40000)
        assert _eval_expression("1 + 20%") == Decimal("1.2")

    def test_whitelist_functions(self):
        assert _eval_expression("sqrt(144)") == Decimal(12)
        assert _eval_expression("abs(-10)") == Decimal(10)
        assert _eval_expression("max(3, 7, 5)") == Decimal(7)
        assert _eval_expression("min(3, 7, 5)") == Decimal(3)
        assert _eval_expression("round(3.14159, 2)") == Decimal("3.14")
        # float 数学函数存在浮点误差，用近似比较
        assert float(_eval_expression("log(exp(1))")) == pytest.approx(1.0)

    def test_float_precision_via_decimal_str(self):
        # 心算易错点：0.1 + 0.2
        assert _eval_expression("0.1 + 0.2") == Decimal("0.3")

    def test_reject_attribute_access(self):
        with pytest.raises(ValueError):
            _eval_expression("(1).__class__")

    def test_reject_dunder(self):
        with pytest.raises(ValueError):
            _eval_expression("__import__('os')")

    def test_reject_unknown_function(self):
        with pytest.raises(ValueError):
            _eval_expression("open('/etc/passwd')")

    def test_reject_string_constant(self):
        with pytest.raises(ValueError):
            _eval_expression("'a' + 'b'")

    def test_division_by_zero(self):
        with pytest.raises(ZeroDivisionError):
            _eval_expression("1 / 0")

    def test_exponent_limit(self):
        with pytest.raises(ValueError):
            _eval_expression("10 ** 100")

    def test_expression_too_long(self):
        with pytest.raises(ValueError):
            _eval_expression("1+" * 300 + "1")

    def test_oversized_result_overflow(self):
        with pytest.raises((OverflowError, ValueError)):
            _eval_expression("exp(1000)")

    def test_percent_vs_modulo(self):
        # 紧贴数字为百分比；空格分隔为取模
        assert _eval_expression("50% * 2") == Decimal(1)
        assert _eval_expression("7 % 3") == Decimal(1)

    def test_calc_expression_error_returns_text(self):
        result = calc_expression("1 / 0")
        assert result.startswith("错误")

    def test_calc_expression_success_format(self):
        result = calc_expression("(1291.5 - 1250) / 1250 * 100")
        assert "= 3.3200" in result


# ──────────────────────────────────────────────────────────────
# 金融函数（已知答案）
# ──────────────────────────────────────────────────────────────


class TestFinancialFunctions:
    def test_pct_change(self):
        result = pct_change(10, 12)
        assert "= 20.0000%" in result

    def test_pct_change_negative(self):
        result = pct_change(100, 80)
        assert "= -20.0000%" in result

    def test_pct_change_zero_base(self):
        assert "错误" in pct_change(0, 10)

    def test_position_size_risk_based(self):
        # 资金 100 万，入场 100，止损 95，单笔风险 1% → 风险额度 1 万，每股风险 5 元
        # 理论 2000 股 → 取整 2000 股，占用 20 万，仓位 20%
        result = position_size(1000000, 100, 95, 1)
        assert "2000 股" in result
        assert "200000" in result
        assert "20.0000%" in result

    def test_position_size_capped_by_capital(self):
        # 风险额度远超资金 → 按满仓取整
        result = position_size(95000, 100, 99, 50)
        assert "900 股" in result
        assert "满仓" in result

    def test_position_size_lot_rounding(self):
        # 理论 150 股 → 取整 100 股
        result = position_size(10000, 100, 95, 0.75)
        assert "100 股" in result

    def test_position_size_same_prices(self):
        assert "错误" in position_size(100000, 100, 100, 1)

    def test_risk_reward(self):
        result = risk_reward(100, 110, 95)
        assert "2.0000" in result

    def test_risk_reward_zero_risk(self):
        assert "错误" in risk_reward(100, 110, 100)

    def test_calc_pnl_basic(self):
        # (12-10)*1000=2000 毛利；手续费 (10+12)*1000*0.0003=6.6；净 1993.4
        result = calc_pnl(10, 12, 1000)
        assert "2000.0000" in result
        assert "6.6000" in result
        assert "1993.4000" in result

    def test_calc_pnl_loss(self):
        result = calc_pnl(12, 10, 1000)
        assert "-2000.0000" in result

    def test_calc_pnl_custom_fee(self):
        result = calc_pnl(10, 10, 1000, 0)
        assert "0.0000 元；净盈亏 = 0.0000" in result

    def test_compound_annual(self):
        # 100 * 1.08^10 = 215.8925
        result = compound(100, 8, 10)
        assert "215.8925" in result

    def test_compound_monthly(self):
        # 100 * (1+0.08/12)^(12) = 108.3000
        result = compound(100, 8, 1, 12)
        assert "108.30" in result

    def test_compound_invalid_rate(self):
        assert "错误" in compound(100, -200, 1)

    def test_max_drawdown(self):
        # 峰值 120 → 谷 90：回撤 25%
        result = max_drawdown("100, 110, 120, 90, 105")
        assert "25.0000%" in result

    def test_max_drawdown_monotonic_up(self):
        result = max_drawdown("1, 2, 3, 4")
        assert "0.0000%" in result

    def test_max_drawdown_bad_input(self):
        assert "错误" in max_drawdown("100")

    def test_var_95(self):
        # 20 个样本，5% 分位 → idx = ceil(1)-1 = 0 → 最差 -3%
        returns = ",".join(["-3", "-2", "-1"] + ["0.5"] * 17)
        result = var_95(returns, 100000)
        assert "-3%" in result
        assert "3000.0000 元" in result

    def test_var_95_bad_input(self):
        assert "错误" in var_95("1", 100)

    def test_moving_average(self):
        # (10+11+12)/3 = 11，取最后 3 个值
        result = moving_average("1, 2, 10, 11, 12", 3)
        assert "SMA(3)" in result and "= 11.0000" in result

    def test_moving_average_insufficient(self):
        assert "错误" in moving_average("1, 2", 5)

    def test_ema_known_answer(self):
        # 种子 SMA(2) = (10+12)/2 = 11；alpha = 2/3；再推一个 14 → 2/3*14 + 1/3*11 = 13
        result = ema("10, 12, 14", 2)
        assert "EMA(2) = 13.0000" in result

    def test_ema_insufficient(self):
        assert "错误" in ema("1", 3)

    def test_volatility_flat_series(self):
        # 价格不变 → 收益率全 0 → 波动率 0
        result = volatility("100, 100, 100, 100")
        assert "年化波动率" in result and "0.0000%" in result

    def test_volatility_annualized_scaling(self):
        # 年化缩放关系：annualized(252) / daily_std = sqrt(252)
        import re as _re

        prices = ",".join(str(100 + (1 if i % 2 == 0 else 0)) for i in range(10))
        result = volatility(prices)
        daily = float(_re.search(r"标准差 = ([\d.]+)%", result).group(1))
        annual = float(_re.search(r"= ([\d.]+)%（\d+ 个收益样本", result).group(1))
        assert annual / daily == pytest.approx(252**0.5, rel=1e-3)

    def test_volatility_invalid_period(self):
        assert "错误" in volatility("100, 101, 102", 0)

    def test_sharpe_ratio_zero_vol(self):
        assert "错误" in sharpe_ratio("100, 100, 100")

    def test_sharpe_ratio_zero_rf(self):
        # 单调上涨日收益恰为常数 → 标准差 0 → 无定义；改用交替序列验证可计算
        prices = ",".join(str(100 + (1 if i % 2 == 0 else 0)) for i in range(10))
        result = sharpe_ratio(prices, 0)
        assert "夏普比率 =" in result

    def test_cagr(self):
        # 100 → 200，2 年 → 2^0.5 - 1 ≈ 41.4214%
        result = cagr(100, 200, 2)
        assert "41.4214%" in result

    def test_cagr_invalid(self):
        assert "错误" in cagr(0, 200, 2)
        assert "错误" in cagr(100, 200, 0)

    def test_bollinger(self):
        # 序列 10,10,10,10 → 中轨 10，标准差 0，上下轨 = 10
        result = bollinger("10, 10, 10, 10", 4, 2)
        assert "中轨 = 10.0000" in result and "上轨 = 10.0000" in result

    def test_bollinger_insufficient(self):
        assert "错误" in bollinger("1, 2", 5)


# ──────────────────────────────────────────────────────────────
# ToolDef 生成
# ──────────────────────────────────────────────────────────────


class TestToolDefs:
    def test_calc_tool_defs_count_and_names(self):
        defs = calc_tool_defs()
        names = [t.name for t in defs]
        assert names == [
            "calc_expression",
            "pct_change",
            "position_size",
            "risk_reward",
            "calc_pnl",
            "compound",
            "max_drawdown",
            "var_95",
            "moving_average",
            "ema",
            "volatility",
            "sharpe_ratio",
            "cagr",
            "bollinger",
            "calc_batch",
        ]
        assert all(t.is_concurrency_safe for t in defs)

    def test_enforcement_prompt_covers_all_tools(self):
        # 强制 prompt 必须点到每个计算工具名（缺一个都会让 AI 不知道该工具存在）
        for name in [t.name for t in calc_tool_defs()]:
            assert name in CALC_ENFORCEMENT_PROMPT, f"prompt 缺少工具说明: {name}"
        assert "禁止心算" in CALC_ENFORCEMENT_PROMPT
        assert "必须" in CALC_ENFORCEMENT_PROMPT

    def test_schema_number_mapping(self):
        # func_to_tooldef 注解映射：float → number（风险点验证）
        tooldef = func_to_tooldef(pct_change)
        assert tooldef.params_schema["properties"]["old"]["type"] == "number"
        assert tooldef.params_schema["properties"]["new"]["type"] == "number"
        assert tooldef.params_schema["required"] == ["old", "new"]

    def test_schema_series_as_string(self):
        tooldef = func_to_tooldef(max_drawdown)
        assert tooldef.params_schema["properties"]["prices"]["type"] == "string"

    def test_handler_callable_directly(self):
        defs = {t.name: t for t in calc_tool_defs()}
        result = defs["pct_change"].handler(10, 12)  # type: ignore[arg-type]
        assert "20.0000%" in result


# ──────────────────────────────────────────────────────────────
# 批量计算入口
# ──────────────────────────────────────────────────────────────


class TestCalcBatch:
    def test_mixed_ops_with_ids(self):
        out = calc_batch(
            [
                {"id": "涨幅", "op": "pct_change", "args": {"old": 1250, "new": 1291.5}},
                {"id": "ma", "op": "moving_average", "args": {"prices": "1290,1301,1315", "window": 3}},
                {"op": "calc_expression", "args": {"expression": "50 - 15 - 10"}},
            ]
        )
        lines = out.split("\n")
        assert len(lines) == 3
        assert lines[0].startswith("[涨幅]") and "3.3200%" in lines[0]
        assert lines[1].startswith("[ma]") and "1302.0000" in lines[1]
        # 无 id 任务回退序号
        assert lines[2].startswith("[3]") and "= 25.0000" in lines[2]

    def test_single_failure_not_blocking(self):
        out = calc_batch(
            [
                {"id": "ok", "op": "calc_expression", "args": {"expression": "1+1"}},
                {"id": "div0", "op": "calc_expression", "args": {"expression": "1/0"}},
                {"id": "bad_args", "op": "pct_change", "args": {"wrong": 1}},
            ]
        )
        lines = out.split("\n")
        assert len(lines) == 3
        assert "[ok]" in lines[0] and "= 2.0000" in lines[0]
        # 业务错误（除零）由单函数内部转文本回传
        assert "[div0]" in lines[1] and "错误" in lines[1]
        # 参数名错误（TypeError）由 calc_batch 兜底捕获
        assert "[bad_args]" in lines[2] and "TypeError" in lines[2]

    def test_unknown_op(self):
        out = calc_batch(
            [
                {"op": "nope", "args": {}},
                {"op": "cagr", "args": {"start_value": 100, "end_value": 200, "years": 2}},
            ]
        )
        lines = out.split("\n")
        assert "未知操作" in lines[0] and "cagr" in lines[0]
        assert "41.4214%" in lines[1]

    def test_invalid_tasks_payload(self):
        assert "错误" in calc_batch([])
        assert "错误" in calc_batch("not-a-list")
        assert "错误" in calc_batch({"op": "cagr"})
        # 超上限整批拒绝
        tasks = [{"op": "calc_expression", "args": {"expression": "1+1"}}] * (_BATCH_MAX_TASKS + 1)
        assert "不得超过" in calc_batch(tasks)
        # 恰好等于上限可执行
        ok = calc_batch(tasks[:_BATCH_MAX_TASKS])
        assert ok.count("= 2.0000") == _BATCH_MAX_TASKS

    def test_malformed_task_entries(self):
        out = calc_batch(["bare-string", {"args": {"expression": "1+1"}}, {"op": "cagr", "args": ["not-dict"]}])
        lines = out.split("\n")
        assert "任务必须是对象" in lines[0]
        assert "未知操作" in lines[1]
        assert "args 必须为对象" in lines[2]

    def test_empty_id_falls_back_to_index(self):
        out = calc_batch([{"id": "", "op": "calc_expression", "args": {"expression": "2*3"}}])
        assert out.startswith("[1]")

    def test_batch_tooldef_schema(self):
        # calc_batch 手写 schema：嵌套 items 必须完整（func_to_tooldef 只会给裸 array）
        batch = {t.name: t for t in calc_tool_defs()}["calc_batch"]
        items = batch.params_schema["properties"]["tasks"]["items"]
        assert set(items["properties"]) == {"id", "op", "args"}
        assert items["required"] == ["op"]
        # enum 覆盖全部单函数工具
        assert set(items["properties"]["op"]["enum"]) == {
            f.__name__
            for f in (
                calc_expression,
                pct_change,
                position_size,
                risk_reward,
                calc_pnl,
                compound,
                max_drawdown,
                var_95,
                moving_average,
                ema,
                volatility,
                sharpe_ratio,
                cagr,
                bollinger,
            )
        }
        assert batch.params_schema["required"] == ["tasks"]
        assert batch.is_concurrency_safe is True
        assert batch.handler is calc_batch

    def test_prompt_requires_batch_for_multiple(self):
        # 批量规则必须显式写进强制 prompt（否则模型仍会逐条调用）
        assert "calc_batch" in CALC_ENFORCEMENT_PROMPT
        assert "2 个及以上" in CALC_ENFORCEMENT_PROMPT

    def test_batch_docstring_covers_all_ops(self):
        # _BATCH_OPS 自动跟随 _TOOL_FUNCS，但 docstring 的 op 清单是手写的：
        # 新增计算函数若漏更新描述，AI 就不知道该 op 可用
        doc = calc_batch.__doc__ or ""
        for op_name in _BATCH_OPS:
            assert op_name in doc, f"calc_batch 描述缺少 op: {op_name}"

    def test_batch_docstring_covers_param_hints(self):
        # 每个 op 的参数签名必须写进描述（AI 不必回翻 14 个单函数 schema）
        doc = calc_batch.__doc__ or ""
        for hint in ("expression", "prices", "window", "returns", "initial", "capital"):
            assert hint in doc, f"calc_batch 描述缺少参数提示: {hint}"


class TestQuantize:
    def test_q4_rounding(self):
        assert _q4(Decimal("3.14159")) == Decimal("3.1416")
        assert _q4(Decimal("2.5")) == Decimal("2.5000")
