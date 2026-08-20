"""
内置确定性计算工具（builtin tool，非 skill）

LLM 心算/金额计算易错，所有数值计算必须走本工具的确定性代码。
- calc_expression：ast 白名单节点求值（禁 eval），支持 50% 百分比字面量
- 金融函数：涨跌幅/仓位/盈亏比/盈亏/复利/最大回撤/VaR(95%)
- 精度：内部 Decimal，输出按语义 quantize 并附公式回显

注册路径：build_analyst_specs 无条件追加 calc_tool_defs() 进 callable_tools，
执行走 runner 的 ad-hoc extra_defs（无需注册进 ToolRegistry）。
"""

import ast
import logging
import math
import re
from decimal import Decimal, ROUND_HALF_UP, getcontext
from typing import List

from app.llm.tools.wrappers import func_to_tooldef

logger = logging.getLogger(__name__)

# 金额/金融计算默认 28 位有效数字，避免复利等迭代场景精度损失
getcontext().prec = 28

_EXPR_MAX_LEN = 500
_AST_MAX_DEPTH = 100
_MAX_EXP = 32  # 指数上限，防 10**10000 量级爆炸

_ALLOWED_BINOPS = (
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.Pow,
    ast.FloorDiv,
)
_ALLOWED_UNARYOPS = (ast.UAdd, ast.USub)

_ALLOWED_CALLS = {
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "sqrt": math.sqrt,
    "exp": math.exp,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
}


def _to_decimal(value) -> Decimal:
    """int/float/str → Decimal（str 路径规避 float 二进制误差）"""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _q4(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _eval_node(node: ast.AST, depth: int = 0) -> Decimal:
    """递归求值白名单 AST 节点，返回 Decimal"""
    if depth > _AST_MAX_DEPTH:
        raise ValueError(f"表达式嵌套过深（>{_AST_MAX_DEPTH}）")
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, depth + 1)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("仅允许数字常量")
        return _to_decimal(node.value)
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, _ALLOWED_UNARYOPS):
            raise ValueError(f"不允许的一元运算符: {type(node.op).__name__}")
        v = _eval_node(node.operand, depth + 1)
        return v if isinstance(node.op, ast.UAdd) else -v
    if isinstance(node, ast.BinOp):
        if not isinstance(node.op, _ALLOWED_BINOPS):
            raise ValueError(f"不允许的运算符: {type(node.op).__name__}")
        left = _eval_node(node.left, depth + 1)
        right = _eval_node(node.right, depth + 1)
        op = node.op
        if isinstance(op, ast.Add):
            return left + right
        if isinstance(op, ast.Sub):
            return left - right
        if isinstance(op, ast.Mult):
            return left * right
        if isinstance(op, ast.Div):
            if right == 0:
                raise ZeroDivisionError("除数为 0")
            return left / right
        if isinstance(op, ast.FloorDiv):
            if right == 0:
                raise ZeroDivisionError("除数为 0")
            return (left / right).to_integral_value(rounding=ROUND_HALF_UP)
        if isinstance(op, ast.Mod):
            if right == 0:
                raise ZeroDivisionError("除数为 0")
            return left % right
        # Pow
        if abs(right) > _MAX_EXP:
            raise ValueError(f"指数绝对值不得超过 {_MAX_EXP}")
        if right != right.to_integral_value():
            # Decimal 非整数幂走 float 数学库，精度 15 位左右，结果转回 Decimal
            result = float(left) ** float(right)
            if not math.isfinite(result):
                raise OverflowError("结果溢出")
            return _to_decimal(result)
        return left ** int(right)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("仅允许调用白名单函数")
        fname = node.func.id
        if "__" in fname or fname not in _ALLOWED_CALLS:
            raise ValueError(f"不允许的函数: {fname}")
        args = [_eval_node(a, depth + 1) for a in node.args]
        if node.keywords:
            raise ValueError("不支持关键字参数")
        # math 系函数吃 float；min/max/abs/round 吃 Decimal
        if fname in ("sqrt", "exp", "log", "log10", "log2"):
            fargs = [float(a) for a in args]
            if fname == "log" and len(fargs) not in (1, 2):
                raise ValueError("log 需要 1 或 2 个参数")
            result = _ALLOWED_CALLS[fname](*fargs)
            if not math.isfinite(result):
                raise OverflowError("结果溢出")
            return _to_decimal(result)
        if fname == "round" and len(args) == 2:
            # round(x, n) 的 n 必须是 int（Decimal 会 TypeError）
            args = [args[0], int(args[1])]
        return _to_decimal(_ALLOWED_CALLS[fname](*args))
    raise ValueError(f"不允许的表达式元素: {type(node).__name__}")


def _normalize_percent(expr: str) -> str:
    """50% → (50/100)；仅转换紧贴数字的 %（无空格），"7 % 3" 仍为取模"""
    return re.sub(r"(\d+(?:\.\d+)?)%", r"(\1/100)", expr)


def _eval_expression(expression: str) -> Decimal:
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("表达式不能为空")
    if len(expression) > _EXPR_MAX_LEN:
        raise ValueError(f"表达式过长（>{_EXPR_MAX_LEN} 字符）")
    if "__" in expression:
        raise ValueError("表达式包含禁止的标识符")
    expr = _normalize_percent(expression)
    tree = ast.parse(expr, mode="eval")
    return _eval_node(tree)


# ──────────────────────────────────────────────────────────────
# 工具函数（docstring 首段即 LLM 可见的工具描述）
# ──────────────────────────────────────────────────────────────


def calc_expression(expression: str) -> str:
    """精确计算数学表达式（四则/百分比/幂/开方），避免心算出错。支持 + - * / // % **、50% 百分比字面量，以及函数 abs/min/max/round/sqrt/exp/log/log10/log2。示例："(1291.5 - 1250) / 1250 * 100"、"50% * 80000"、"sqrt(144)"。"""
    try:
        result = _eval_expression(expression)
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError) as e:
        return f"错误：{e.__class__.__name__}: {e}"
    return f"{expression} = {_q4(result)}"


def pct_change(old: float, new: float) -> str:
    """计算涨跌幅百分比：(new - old) / old * 100。常用于价格变动、指标环比/同比。"""
    old_d, new_d = _to_decimal(old), _to_decimal(new)
    if old_d == 0:
        return "错误：基期值为 0，涨跌幅无定义"
    result = (new_d - old_d) / old_d * Decimal(100)
    return f"(new - old) / old * 100 = ({new_d} - {old_d}) / {old_d} * 100 = {_q4(result)}%"


def position_size(capital: float, entry: float, stop: float, risk_pct: float) -> str:
    """风险定额仓位计算：给定总资金、入场价、止损价和单笔可承受亏损比例，计算可买股数、占用金额与仓位占比。"""
    capital_d, entry_d, stop_d = _to_decimal(capital), _to_decimal(entry), _to_decimal(stop)
    risk_amount = capital_d * _to_decimal(risk_pct) / Decimal(100)
    per_share_risk = abs(entry_d - stop_d)
    if per_share_risk == 0:
        return "错误：入场价与止损价相同，每股风险为 0"
    shares_raw = risk_amount / per_share_risk
    # A 股按 100 股一手向下取整
    shares = int(shares_raw / 100) * 100
    cost = shares * entry_d
    if cost > capital_d:
        shares = int(capital_d / entry_d / 100) * 100
        cost = shares * entry_d
        note = "；风险额度超出资金上限，已按满仓向下取整"
    else:
        note = ""
    if shares <= 0:
        return "错误：按 100 股一手计算，可用资金或风险额度不足一手"
    position_pct = cost / capital_d * Decimal(100)
    return (
        f"可买 {shares} 股，占用金额 {_q4(cost)} 元，仓位占比 {_q4(position_pct)}%"
        f"（单笔风险额度 {_q4(risk_amount)} 元，每股风险 {_q4(per_share_risk)} 元）{note}"
    )


def risk_reward(entry: float, target: float, stop: float) -> str:
    """计算盈亏比（风险回报比）：|target - entry| / |entry - stop|。"""
    entry_d, target_d, stop_d = _to_decimal(entry), _to_decimal(target), _to_decimal(stop)
    risk = abs(entry_d - stop_d)
    reward = abs(target_d - entry_d)
    if risk == 0:
        return "错误：入场价与止损价相同，风险为 0"
    rr = reward / risk
    return f"盈亏比 = |{target_d} - {entry_d}| / |{entry_d} - {stop_d}| = {_q4(rr)}"


def calc_pnl(
    entry_price: float, exit_price: float, qty: float, fee_rate: float = 0.0003
) -> str:
    """计算交易盈亏（含双边手续费）：(exit - entry) * qty - (entry + exit) * qty * fee_rate。fee_rate 为单边费率，默认万三。"""
    entry_d, exit_d, qty_d = _to_decimal(entry_price), _to_decimal(exit_price), _to_decimal(qty)
    fee_d = _to_decimal(fee_rate)
    gross = (exit_d - entry_d) * qty_d
    fees = (entry_d + exit_d) * qty_d * fee_d
    net = gross - fees
    return (
        f"毛盈亏 = ({exit_d} - {entry_d}) * {qty_d} = {_q4(gross)} 元；"
        f"手续费 = ({entry_d} + {exit_d}) * {qty_d} * {fee_d} = {_q4(fees)} 元；"
        f"净盈亏 = {_q4(net)} 元"
    )


def compound(principal: float, rate: float, periods: float, per_year: float = 1) -> str:
    """复利终值计算：principal * (1 + rate/per_year)^(periods*per_year)。rate 为年化利率（百分数，如 8 表示 8%）。"""
    p_d, r_d, n_d, m_d = (
        _to_decimal(principal),
        _to_decimal(rate),
        _to_decimal(periods),
        _to_decimal(per_year),
    )
    if m_d <= 0:
        return "错误：per_year 必须为正数"
    periodic = Decimal(1) + r_d / Decimal(100) / m_d
    if periodic <= 0:
        return "错误：周期利率 ≤ -100%，终值无意义"
    total_periods = n_d * m_d
    if abs(total_periods) > _MAX_EXP * 1000:
        return "错误：期数过大"
    growth = float(periodic) ** float(total_periods)
    if not math.isfinite(growth):
        return "错误：结果溢出"
    result = p_d * _to_decimal(growth)
    return (
        f"{p_d} * (1 + {r_d}%/{m_d})^({n_d}*{m_d}) = {_q4(_to_decimal(result))} 元"
    )


def _parse_series(values: str) -> List[Decimal]:
    if not isinstance(values, str) or not values.strip():
        raise ValueError("序列不能为空")
    parts = [p.strip() for p in values.split(",") if p.strip()]
    if len(parts) < 2:
        raise ValueError("序列至少需要 2 个逗号分隔的数值")
    return [_to_decimal(p) for p in parts]


def max_drawdown(prices: str) -> str:
    """计算最大回撤百分比：输入逗号分隔的价格/净值序列（时间正序），返回 max((peak - trough)/peak)*100。"""
    try:
        series = _parse_series(prices)
    except ValueError as e:
        return f"错误：{e}"
    peak = series[0]
    max_dd = Decimal(0)
    for price in series:
        if price > peak:
            peak = price
        if peak > 0:
            dd = (peak - price) / peak
            if dd > max_dd:
                max_dd = dd
        else:
            return "错误：序列包含非正的峰值，回撤无定义"
    return f"最大回撤 = {_q4(max_dd * Decimal(100))}%（共 {len(series)} 个数据点）"


def var_95(returns: str, initial: float) -> str:
    """历史模拟法 VaR(95%)：输入逗号分隔的日收益率序列（百分数，如 -1.5,0.8 表示 -1.5%,0.8%）与初始金额，返回 95% 置信下单日最大亏损金额与比例。"""
    try:
        series = _parse_series(returns)
    except ValueError as e:
        return f"错误：{e}"
    initial_d = _to_decimal(initial)
    sorted_r = sorted(series)
    n = len(sorted_r)
    # 5% 分位：index = ceil(0.05*n) - 1，至少取最差值
    idx = max(0, math.ceil(0.05 * n) - 1)
    var_return = sorted_r[idx]
    var_amount = initial_d * abs(var_return) / Decimal(100)
    direction = "亏损" if var_return < 0 else "收益（历史分布右偏，无亏损风险估计意义）"
    return (
        f"VaR(95%) 日收益率分位 = {var_return}%，"
        f"对应单日最大{direction}金额 = {_q4(var_amount)} 元（初始 {initial_d} 元，样本 {n} 天）"
    )


_TOOL_FUNCS = [
    calc_expression,
    pct_change,
    position_size,
    risk_reward,
    calc_pnl,
    compound,
    max_drawdown,
    var_95,
]


def calc_tool_defs() -> List:
    """全部计算工具的 ToolDef 列表（build_analyst_specs 注入 callable_tools）"""
    return [
        func_to_tooldef(f, is_concurrency_safe=True) for f in _TOOL_FUNCS
    ]
