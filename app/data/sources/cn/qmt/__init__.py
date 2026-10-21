"""QMT 数据源（datadir 本地直读，国金 QMT 基线）。

架构与口径见 docs/技术方案-QMT数据源接入.md；产品口径见
docs/PRD-QMT数据源接入.md（D-1 同机部署 / D-2 兜底源 / D-5 格式一致 /
D-7 仅本地直读）。
"""

from .adapter import QmtAdapter
from .datadir_reader import QmtDatadirReader, QmtSelfCheckReport
from .health import QmtErrorCode, QmtHealthProbe, QmtHealthState
from .provider import QmtProvider

__all__ = [
    "QmtAdapter",
    "QmtDatadirReader",
    "QmtProvider",
    "QmtErrorCode",
    "QmtHealthProbe",
    "QmtHealthState",
    "QmtSelfCheckReport",
]
