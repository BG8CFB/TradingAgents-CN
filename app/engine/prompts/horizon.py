"""投资期限锚点段：mid/long 档运行时注入 system prompt，压过角色定义里的短线硬文案。

设计（期限贯通方案 A）：
- short/None → 空串（零注入，缺省任务 prompt 与历史字节一致）
- 锚点置于 system 尾部（最高显著位），逐条点名 trader/bull/bear 角色定义中
  写死的「未来 3 天买入 / 未来 7 天卖出 / 未来 7 天协同性」等周期条款，
  要求一律按本次分析持有期重新解读
- 风险组 / risk-manager / summary 不注入：它们评估的对象（交易计划）已带期限

行业参照：ai-hedge-fund 的期限不进 prompt（人格语言天然对齐），我们因
seeds 角色定义存在硬文案而需要此锚点线；见 docs/投资期限贯通.md。
"""
from typing import Literal, Optional

from app.core.horizons import HORIZON_DAYS, HORIZON_LABELS, horizon_days_of

HorizonRole = Literal["analyst", "debater", "judge", "trader"]

_HEADER = (
    "【投资期限指令｜优先级高于角色定义中的一切周期表述】\n"
    "本次分析的投资期限为 {n} 个交易日（{label}口径）。"
    "持有期自决策日后的首个交易日起算，至第 {n} 个交易日收盘结束。"
)

_TRADER_OVERRIDE = """
角色定义中的以下周期条款一律按本期限重新解读，不得照抄原文天数：
- 「未来 3 天每天买入价格区间」→ 前 {entry_window} 个交易日的分批建仓参考价；
- 「未来 7 天每天卖出价格区间」→ 第 {n_minus_2} 至第 {n} 个交易日的分批止盈参考价；
- 「持有周期 短线≤7/中线≤30 个交易日」→ 本计划持有期固定为 {n} 个交易日，到期未达预期按现价择机离场；
- 单笔亏损上限与强制止损等风控纪律保持不变；止损位须匹配 {n} 日级别波动（{stop_anchor}），禁止用日内波动止损截断更长持有期。
关键点位与目标价必须与 {n} 个交易日匹配：不得以 3~7 日的短线盘口锚作为主目标位。{long_extra}"""

_STOP_ANCHOR = {7: "参考 5 日均线破位", 20: "参考 20 日均线破位", 60: "参考 60 日均线或季度趋势破位"}
_LONG_EXTRA = (
    "长线止损参考 60 日均线/季度趋势破位；目标价以季度基本面与估值中枢为主锚，技术点位仅作建仓与止盈节奏。"
)
_TIER_FOCUS = {
    20: "以月度级别的趋势、资金与事件节奏为主，淡化日内与隔日噪声，给出 20 个交易日窗口内的关键时间点。",
    60: "以季度级别的基本面、行业景气与估值中枢为主锚，技术信号仅用于建仓与止盈节奏，给出 60 个交易日窗口内的催化剂时间线。",
}

_DEBATER_OVERRIDE = """
「短期协同性分析（未来 7 天）」「7 个交易日内上行/下行至[价格区间]」等周期表述，
一律按 {n} 个交易日窗口重新解读：协同性证据与上行/下行目标区间必须以 {n} 个交易日为评估期；
在{label}窗口内不可兑现的论据应降权（隔日资金异动仅作节奏参考，不作核心论据）。"""

_ANALYST_OVERRIDE = """
你的报告将服务于一个持有期 {n} 个交易日（{label}）的投资决策，
评估窗口与结论必须落在该期限内：{focus}
角色定义中的具体天数锚（如「短线 1-5 日」「短期 1-3 天/中期 1-2 周/长期 1-3 月」）
一律按 {n} 个交易日重新解读。"""


def _entry_window(n: int) -> int:
    """分批建仓参考窗口按期限分档：短线 3 / 中线 5 / 长线 10 个交易日"""
    if n <= 7:
        return 3
    if n <= 20:
        return 5
    return 10


def build_horizon_anchor(horizon: Optional[str], role: HorizonRole) -> str:
    """期限锚点段（以空行分隔、可直接 append 到 system prompt 末尾）。

    horizon=None 或 "short" → 空串（零注入）；未知值 → 空串（调用方已按
    horizon_days_of 兜底，此处防御性返回空）。
    """
    n = horizon_days_of(horizon)
    if not n or n == HORIZON_DAYS["short"]:
        return ""
    label = HORIZON_LABELS.get(str(horizon), "")
    head = _HEADER.format(n=n, label=label)
    if role == "trader":
        body = _TRADER_OVERRIDE.format(
            entry_window=_entry_window(n),
            n_minus_2=max(n - 2, 1),
            n=n,
            stop_anchor=_STOP_ANCHOR.get(n, "20 日均线破位"),
            long_extra=_LONG_EXTRA if n >= 60 else "",
        )
    elif role in ("debater", "judge"):
        body = _DEBATER_OVERRIDE.format(n=n, label=label)
    else:
        body = _ANALYST_OVERRIDE.format(n=n, label=label, focus=_TIER_FOCUS.get(n, ""))
    return f"\n\n{head}{body}"
