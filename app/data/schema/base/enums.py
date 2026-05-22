"""公共枚举定义。"""

from enum import Enum


class ListStatus(str, Enum):
    LISTED = "L"        # 上市
    DELISTED = "D"      # 退市
    SUSPENDED = "P"     # 暂停 (A 股) / 暂停 (HK)
    SUSPENDED_HK = "S"  # 港股暂停


class StatementType(str, Enum):
    INCOME = "income"           # 利润表
    BALANCE = "balance"         # 资产负债表
    CASHFLOW = "cashflow"       # 现金流量表
    INDICATOR = "indicator"     # 财务指标


class ReportType(str, Enum):
    # A 股 / 港股
    Q1 = "Q1"
    Q2 = "Q2"         # 半年报 (H1)
    Q3 = "Q3"
    FY = "FY"         # 年报
    H1 = "H1"         # 中报 (港股)
    H2 = "H2"         # 全年报 (港股)
    # A 股特有
    CONSOLIDATED = "1"     # 合并报表
    SINGLE_QUARTER = "2"   # 单季合并
    PARENT = "4"           # 母公司报表


class ActionType(str, Enum):
    CASH_DIVIDEND = "cash_dividend"
    SPECIAL_DIVIDEND = "special_dividend"
    STOCK_SPLIT = "stock_split"
    REVERSE_SPLIT = "reverse_split"
    CONSOLIDATION = "consolidation"  # 港股并股
    BONUS_ISSUE = "bonus_issue"      # 港股红股
    RIGHTS_ISSUE = "rights_issue"    # 港股供股
    MERGER = "merger"
    SPINOFF = "spinoff"              # 美股
    PRIVATIZATION = "privatization"  # 港股私有化


class DataPeriod(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class SupportLevel(str, Enum):
    FULL = "full"
    PARTIAL = "partial"
    NONE = "none"


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class RefreshStatus(str, Enum):
    FRESH = "fresh"
    REFRESHED = "refreshed"
    PARTIAL = "partial"
    TIMEOUT = "timeout"
    FAILED = "failed"


class FreshnessState(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


class QuoteSourceType(str, Enum):
    DELAYED = "delayed"     # 延迟 15 分钟
    REALTIME = "realtime"   # 准实时


class MarketSession(str, Enum):
    PRE_OPEN = "pre_open"
    MORNING = "morning"
    LUNCH_BREAK = "lunch_break"
    AFTERNOON = "afternoon"
    CLOSING_AUCTION = "closing_auction"
    PRE = "pre"          # 美股盘前
    REGULAR = "regular"  # 美股正常交易
    POST = "post"        # 美股盘后
    CLOSED = "closed"
