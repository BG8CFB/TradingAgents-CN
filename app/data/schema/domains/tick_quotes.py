"""逐笔成交（tick）标准域 Schema —— PRD D-6 / FR-06，技术方案第六节。

设计要点（与既有域同规，D-5 格式一致性）：
- 主键语义与 ``index_definitions`` 唯一索引一致，**不含 data_source**
  （单版本覆盖：备用源 upsert 覆盖同自然键记录）；
- ``time_ms`` 为**当日毫秒时刻**（datadir 144B tick 经时间基校准后的值，
  不是 epoch 绝对时间）。选它而非 ``datetime`` 作唯一键之一：毫秒精度可区分
  同一秒内的多笔成交，字符串时间做不到；``datetime`` 仅作可读冗余列；
- 5 档行情存 **Mongo 数组**（数组 [买一..买五] / [卖一..卖五]），不展开为
  扁平 20 列：与 reader 输出同形、文档体积小约 80%（技术方案 O-3 评审结论）；
- ``volume`` / ``amount`` 是**当日累计值**（真实 datadir 实测：末条累计量与日线
  bar 逐值相等），不是单笔增量；单位经 2026-10-20 实盘定版为「手 → 股 ×100」；
- 集合竞价阶段的记录 ``last_price`` 可能为 **0.0**（尚未产生成交价），以
  ``market_phase_status``（12 = 竞价段）区分，不要当作异常值剔除。
"""

from dataclasses import dataclass
from typing import List, Optional

from app.data.schema.base.common_fields import CommonFields


@dataclass
class TickQuotesSchema(CommonFields):
    """逐笔成交快照 — datadir 144B tick 记录的标准形态。"""

    trade_date: Optional[str] = None      # 'YYYY-MM-DD'，分区键/清理维度
    time_ms: Optional[int] = None         # 当日毫秒时刻（校准后），唯一键之一
    datetime: Optional[str] = None        # 'YYYY-MM-DD HH:MM:SS' 可读冗余列
    last_price: Optional[float] = None    # 最新价
    open: Optional[float] = None          # 当日快照 OHLC（datadir tick 语义）
    high: Optional[float] = None
    low: Optional[float] = None
    last_close: Optional[float] = None    # 昨收（preClose）
    volume: Optional[float] = None        # **当日累计**成交量（股；源为手，Adapter ×100）
    amount: Optional[float] = None        # **当日累计**成交额（元）
    transaction_num: Optional[int] = None  # 成交笔数
    market_phase_status: Optional[int] = None  # 市场阶段（集合竞价段 = 12；15 = 收盘后）
    ask_price: Optional[List[float]] = None    # 卖五档价格（卖一→卖五）
    ask_vol: Optional[List[int]] = None        # 卖五档量
    bid_price: Optional[List[float]] = None    # 买五档价格（买一→买五）
    bid_vol: Optional[List[int]] = None        # 买五档量
