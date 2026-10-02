"""factor_scores 域 schema — L0 因子批算结果。

主键：(symbol, trade_date)。中立字段，无数据源方言。
因子字段由 app/data/factors/engine.py 批量计算写入；可选域缺失/数据不足时
对应因子置 None，不缺行。历史按日保留（为未来回测留数据基础）。
"""

from dataclasses import dataclass
from typing import Optional

from app.data.schema.base.common_fields import CommonFields

# 引擎写入的全部因子字段（原始值，非分位）——引擎与前端展示共用此清单
FACTOR_FIELDS = [
    # 动量
    "ret_5d", "ret_20d", "ret_60d", "dist_to_60d_high",
    # 趋势
    "bias_ma20", "ma20_slope", "macd_golden_days",
    # 量能
    "turnover_amp", "consecutive_vol_up_days", "volume_ratio",
    # 资金
    "main_inflow_5d", "main_inflow_5d_pct",
    # 估值
    "pe_ttm_percentile", "pb_percentile", "dividend_yield",
    # 质量
    "roe", "gross_margin", "net_profit_yoy", "debt_ratio",
]

# 三风格合成分（0-100，覆盖不足为 None）
SCORE_FIELDS = ["score_short_term", "score_balanced", "score_value"]


@dataclass
class FactorScoresSchema(CommonFields):
    """L0 因子日频快照 — 每股每日一行的 19 因子原始值 + 三风格总分。"""

    trade_date: Optional[str] = None
    name: Optional[str] = None
    industry: Optional[str] = None

    # 动量
    ret_5d: Optional[float] = None            # 5 日收益 %
    ret_20d: Optional[float] = None           # 20 日收益 %
    ret_60d: Optional[float] = None           # 60 日收益 %
    dist_to_60d_high: Optional[float] = None  # 距 60 日最高价 %（正=低于高点）

    # 趋势
    bias_ma20: Optional[float] = None         # close/MA20 乖离 %
    ma20_slope: Optional[float] = None        # MA20 五日斜率 %
    macd_golden_days: Optional[float] = None  # 金叉天数（负值=死叉）

    # 量能
    turnover_amp: Optional[float] = None      # 当日换手/20 日均换手
    consecutive_vol_up_days: Optional[float] = None  # 末位起连续放量天数
    volume_ratio: Optional[float] = None      # 量比（daily_indicators 直取）

    # 资金
    main_inflow_5d: Optional[float] = None    # 主力净流入 5 日累计（元）
    main_inflow_5d_pct: Optional[float] = None  # 占 5 日成交额 %

    # 估值
    pe_ttm_percentile: Optional[float] = None  # PE_TTM 历史分位（0-100）
    pb_percentile: Optional[float] = None      # PB 历史分位（0-100）
    dividend_yield: Optional[float] = None     # 股息率 %

    # 质量
    roe: Optional[float] = None               # ROE %
    gross_margin: Optional[float] = None      # 毛利率 %
    net_profit_yoy: Optional[float] = None    # 净利润同比 %（派生计算）
    debt_ratio: Optional[float] = None        # 资产负债率 %

    # 评分
    score_short_term: Optional[float] = None
    score_balanced: Optional[float] = None
    score_value: Optional[float] = None
