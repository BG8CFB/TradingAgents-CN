"""
决策结算记分卡数据模型（MongoDB + Pydantic）

decision_settlements 集合：一次合格决策的结算生命周期记录。
- 信号与置信度正源 = structured_summary（final_signal / model_confidence）；
  自定义工作流无 summarizer 时回退 trader decision（signal_source 标记来源）。
- channel 区分 online（真实分析，默认聚合口径）/ backtest（回测重放，默认不进记分卡）。
"""
from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, field_serializer

SettlementStatus = Literal["pending", "settled", "unfillable"]
SettlementChannel = Literal["online", "backtest"]
TradeSignal = Literal["Buy", "Sell", "Hold"]


class SettlementOut(BaseModel):
    """单条结算记录（API 输出形状，字段与 decision_settlements 文档对齐）"""

    task_id: str
    symbol: str
    stock_name: Optional[str] = None
    market: str = Field(description="DataInterface 市场码：CN/HK/US")
    decision_date: str = Field(description="决策基准日 YYYY-MM-DD")
    signal: TradeSignal
    stated_confidence: Optional[float] = Field(default=None, description="0-100")
    key_prices: Dict[str, Any] = Field(default_factory=dict)
    horizon_days: int = 7
    channel: SettlementChannel = "online"
    status: SettlementStatus = "pending"
    board: Optional[str] = None
    signal_source: Optional[str] = Field(default=None, description="summary / decision")
    entry_date: Optional[str] = None
    entry_price: Optional[float] = None
    exit_date: Optional[str] = None
    exit_price: Optional[float] = None
    return_pct: Optional[float] = None
    actual_direction: Optional[str] = None
    direction_hit: Optional[bool] = None
    benchmark_symbol: Optional[str] = Field(default=None, description="基准指数规范码（如 000300.SH/HSI/SPX）；null=未算出基准（含基准数据不可得），价格字段同为 null")
    bench_entry: Optional[float] = Field(default=None, description="基准入场端价（入场日或其前最近指数 bar 的开盘）")
    bench_exit: Optional[float] = Field(default=None, description="基准出场端价（出场日或其前最近指数 bar 的收盘）")
    benchmark_return_pct: Optional[float] = None
    alpha_pct: Optional[float] = Field(default=None, description="超额收益 = return_pct - benchmark_return_pct")
    direction_hit_vs_benchmark: Optional[bool] = Field(default=None, description="超额方向命中（Buy: alpha>0 / Sell: alpha<0 / Hold: None）")
    error_type: Optional[str] = None
    failure_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    settled_at: Optional[datetime] = None
    days_remaining: Optional[int] = Field(default=None, description="待结算剩余交易日（派生，仅 by-task）")

    @field_serializer("created_at", "settled_at")
    def serialize_datetime(self, dt: Optional[datetime], _info) -> Optional[str]:
        """序列化 datetime 为 ISO 8601，保留时区信息"""
        if dt:
            return dt.isoformat()
        return None

    model_config = {"extra": "ignore"}


class ConfidenceBucketOut(BaseModel):
    """置信度分桶（校准曲线的一个点）"""

    bucket: str
    count: int = 0
    avg_confidence: Optional[float] = None
    hit_rate: Optional[float] = None


class TrendPointOut(BaseModel):
    """按月的命中率趋势点"""

    month: str = Field(description="YYYY-MM")
    count: int = 0
    hit_rate: Optional[float] = None
    ci_low: Optional[float] = None
    ci_high: Optional[float] = None
    avg_return_pct: Optional[float] = None
    avg_alpha_pct: Optional[float] = None


class SignalStatOut(BaseModel):
    """按信号分组的统计"""

    signal: str
    count: int = 0
    hit_rate: Optional[float] = None
    avg_return_pct: Optional[float] = None
    avg_alpha_pct: Optional[float] = None


class HorizonStatOut(BaseModel):
    """按投资期限分组的统计（期限贯通）。

    pending 只计数不阅卷（长线决策大量时间处于待到期状态，
    对齐 ai-hedge-fund 记分卡口径）；hit_rate 仅以已结算样本为分母。
    """

    horizon_days: int = Field(description="持有期交易日数（7/20/60）")
    count: int = 0
    pending: int = 0
    hit_rate: Optional[float] = None
    avg_return_pct: Optional[float] = None


class ScorecardOut(BaseModel):
    """记分卡聚合结果"""

    channel: str
    total_registered: int = 0
    settled_count: int = Field(default=0, description="已结算且信号非 Hold")
    pending_count: int = 0
    unfillable_count: int = 0
    hold_count: int = 0
    hit_rate: Optional[float] = None
    hit_ci: Optional[Dict[str, float]] = Field(default=None, description="Wilson 95% 置信区间")
    avg_return_pct: Optional[float] = None
    median_return_pct: Optional[float] = None
    avg_alpha_pct: Optional[float] = Field(default=None, description="平均超额收益（仅基准可得的样本）")
    median_alpha_pct: Optional[float] = None
    benchmark_hit_rate: Optional[float] = Field(default=None, description="跑赢基准比例（Buy: alpha>0 / Sell: alpha<0）")
    alpha_count: int = Field(default=0, description="alpha 样本数（与命中率样本分母不同，前端须标明）")
    calibration: List[ConfidenceBucketOut] = Field(default_factory=list)
    trend: List[TrendPointOut] = Field(default_factory=list)
    unfillable_ratio: Optional[float] = None
    by_signal: List[SignalStatOut] = Field(default_factory=list)
    by_horizon: List[HorizonStatOut] = Field(default_factory=list)


class SettlementListOut(BaseModel):
    """结算记录分页列表"""

    items: List[SettlementOut]
    total: int = 0
    page: int = 1
    page_size: int = 20
