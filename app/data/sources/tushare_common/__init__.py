"""Tushare 三市场（CN / HK / US）共享基础设施。

设计原则：保留市场差异，仅消除结构性重复。

- 各市场保留独立 Token / 积分门槛 / endpoint 名称 / 代码转换规则
  （CN 前缀启发式、HK zfill(5)、US code_resolver 后缀解析）。
- 连接管理、调用模板（异常映射 + 空结果判定）、Provider 委托模板、
  通用 Adapter 字段映射收敛到本包，由市场子类注入差异参数。
"""

from app.data.sources.tushare_common.client import TushareClient, classify_tushare_error
from app.data.sources.tushare_common.caller import call_tushare
from app.data.sources.tushare_common.base_provider import TushareBaseProvider

__all__ = [
    "TushareClient",
    "classify_tushare_error",
    "call_tushare",
    "TushareBaseProvider",
]
