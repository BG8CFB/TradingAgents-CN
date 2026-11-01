"""投资期限（horizon）单一事实源：枚举、天数映射、默认分析师池、等待上限。

期限贯通（优化方向二 · 方案 A）：short/mid/long 贯穿用户参数 → prompt 锚点 →
结算期限 → 记分卡分组。与选股 style（short_term/balanced/value）正交，
仅共享「短线/中线/长线」中文词根，不做映射推导。

行业参照（references/）：
- ai-hedge-fund：人格声明 horizon_days（252/126/60），记分卡按声明期限阅卷，
  未到期 pending 只计数不阅卷
- 上游 TradingAgents memory/settlement.py：holding_days 参数化
"""
from enum import Enum
from typing import Dict, Optional, Tuple


class AnalysisHorizon(str, Enum):
    """投资期限档位（值为 API 契约，勿改动）"""

    SHORT = "short"
    MID = "mid"
    LONG = "long"


HORIZON_DAYS: Dict[str, int] = {
    AnalysisHorizon.SHORT.value: 7,   # 与 DEFAULT_HORIZON_DAYS=7 及 seeds 三处期限文案零漂移
    AnalysisHorizon.MID.value: 20,    # 月度节奏 / MA20 锚
    AnalysisHorizon.LONG.value: 60,   # 财报季（对齐 ai-hedge-fund pead=60）
}

HORIZON_LABELS: Dict[str, str] = {
    AnalysisHorizon.SHORT.value: "短线",
    AnalysisHorizon.MID.value: "中线",
    AnalysisHorizon.LONG.value: "长线",
}

# 各档默认分析师池（slug = agent_specs _id；前端联动建议，后端不改写显式选择）。
# 约束：market-analyst / short-term-capital-analyst 是 trader/bull/bear 的
# required_sources（config/seeds/agents.json template_inputs），任何池不可裁。
HORIZON_DEFAULT_POOL: Dict[str, Tuple[str, ...]] = {
    AnalysisHorizon.SHORT.value: (
        "market-analyst",
        "financial-news-analyst",
        "china-market-analyst",
        "social-media-analyst",
        "short-term-capital-analyst",
    ),
    AnalysisHorizon.MID.value: (
        "market-analyst",
        "financial-news-analyst",
        "china-market-analyst",
        "fundamentals-analyst",
        "short-term-capital-analyst",
    ),
    # long 与 mid 同池：期限差异由 prompt 锚点承载，不靠裁分析师表达
    AnalysisHorizon.LONG.value: (
        "market-analyst",
        "financial-news-analyst",
        "china-market-analyst",
        "fundamentals-analyst",
        "short-term-capital-analyst",
    ),
}


def horizon_days_of(horizon: Optional[str]) -> Optional[int]:
    """档位 → 持有期交易日数；None/未知 → None（调用方回落 DEFAULT_HORIZON_DAYS）"""
    if horizon is None:
        return None
    days = HORIZON_DAYS.get(str(horizon).strip().lower())
    return days


def horizon_label(horizon: Optional[str]) -> str:
    """档位 → 中文标签；None/未知 → 空串"""
    if horizon is None:
        return ""
    return HORIZON_LABELS.get(str(horizon).strip().lower(), "")


def max_wait_days(horizon_days: int) -> int:
    """结算等待上限（自然日）：行情长期缺失时按此判 unfillable，防 pending 永挂。

    max(90, N*2+10)：N=7/20 → 90（与原 _MAX_WAIT_DAYS 完全一致，现行为零漂移）；
    N=60 → 130（60 交易日约 84 自然日，翻倍+10 扛得住春节+国庆双长假连跨）。
    _settle_record 与 _days_remaining 必须同源使用，否则剩余天数与
    unfillable 判定错位。
    """
    if horizon_days <= 0:
        return 90
    return max(90, horizon_days * 2 + 10)
