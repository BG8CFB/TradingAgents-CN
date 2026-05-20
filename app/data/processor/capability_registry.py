"""
能力注册表 (Capability Registry)

静态定义每个数据源对每个数据域的支持情况。
FallbackRouter 的所有决策（过滤、排序）均基于此表。

支持级别：
  "full"    - 完整支持
  "partial" - 部分字段支持
  "none"    - 不支持
"""

from enum import Enum
from typing import Dict, List, Optional


class SupportLevel(str, Enum):
    FULL = "full"
    PARTIAL = "partial"
    NONE = "none"


# A 股数据源能力矩阵
# 键: 数据域 → 值: {数据源 → 支持级别}
CN_CAPABILITY_MATRIX: Dict[str, Dict[str, SupportLevel]] = {
    "basic_info": {
        "tushare": SupportLevel.FULL,
        "akshare": SupportLevel.FULL,
        "baostock": SupportLevel.FULL,
    },
    "trade_calendar": {
        "tushare": SupportLevel.FULL,
        "akshare": SupportLevel.FULL,
        "baostock": SupportLevel.FULL,
    },
    "daily_quotes": {
        "tushare": SupportLevel.FULL,
        "akshare": SupportLevel.FULL,
        "baostock": SupportLevel.FULL,
    },
    "daily_indicators": {
        "tushare": SupportLevel.FULL,
        "akshare": SupportLevel.PARTIAL,
        "baostock": SupportLevel.NONE,
    },
    "adj_factors": {
        "tushare": SupportLevel.FULL,
        "akshare": SupportLevel.FULL,
        "baostock": SupportLevel.FULL,
    },
    "financial": {
        "tushare": SupportLevel.FULL,
        "akshare": SupportLevel.PARTIAL,
        "baostock": SupportLevel.NONE,
    },
    "market_quotes": {
        "tushare": SupportLevel.FULL,
        "akshare": SupportLevel.FULL,
        "baostock": SupportLevel.NONE,
    },
    "news": {
        "tushare": SupportLevel.FULL,
        "akshare": SupportLevel.PARTIAL,
        "baostock": SupportLevel.NONE,
    },
}

# 港股数据源能力矩阵
HK_CAPABILITY_MATRIX: Dict[str, Dict[str, SupportLevel]] = {
    "basic_info": {
        "akshare_hk": SupportLevel.FULL,
        "yfinance_hk": SupportLevel.FULL,
    },
    "daily_quotes": {
        "akshare_hk": SupportLevel.FULL,
        "yfinance_hk": SupportLevel.FULL,
    },
    "financial": {
        "yfinance_hk": SupportLevel.PARTIAL,
    },
    "news": {
        "akshare_hk": SupportLevel.PARTIAL,
    },
}

# 美股数据源能力矩阵
US_CAPABILITY_MATRIX: Dict[str, Dict[str, SupportLevel]] = {
    "basic_info": {
        "yfinance_us": SupportLevel.FULL,
        "finnhub_us": SupportLevel.FULL,
    },
    "daily_quotes": {
        "yfinance_us": SupportLevel.FULL,
        "finnhub_us": SupportLevel.FULL,
    },
    "financial": {
        "yfinance_us": SupportLevel.PARTIAL,
        "finnhub_us": SupportLevel.PARTIAL,
    },
    "news": {
        "finnhub_us": SupportLevel.FULL,
    },
}

# 默认优先级排序（支持级别从高到低）
_DEFAULT_PRIORITY: Dict[str, List[str]] = {
    "basic_info": ["tushare", "akshare", "baostock"],
    "trade_calendar": ["tushare", "akshare", "baostock"],
    "daily_quotes": ["tushare", "akshare", "baostock"],
    "daily_indicators": ["tushare", "akshare"],
    "adj_factors": ["tushare", "akshare", "baostock"],
    "financial": ["tushare", "akshare"],
    "market_quotes": ["tushare", "akshare"],
    "news": ["tushare", "akshare"],
}

# 数据域定义
ALL_DOMAINS = list(CN_CAPABILITY_MATRIX.keys())


class CapabilityRegistry:
    """能力注册表：查询数据源能力"""

    _MARKET_MATRICES = {
        "CN": CN_CAPABILITY_MATRIX,
        "HK": HK_CAPABILITY_MATRIX,
        "US": US_CAPABILITY_MATRIX,
    }

    def __init__(
        self,
        matrix: Optional[Dict[str, Dict[str, SupportLevel]]] = None,
        market: str = "CN",
    ):
        self._matrix = matrix or self._MARKET_MATRICES.get(market, CN_CAPABILITY_MATRIX)
        self._priorities: Dict[str, List[str]] = {}

    def get_support_level(self, domain: str, source: str) -> SupportLevel:
        """获取指定数据域+数据源的支持级别"""
        domain_caps = self._matrix.get(domain, {})
        return domain_caps.get(source, SupportLevel.NONE)

    def get_available_sources(self, domain: str) -> List[str]:
        """获取指定数据域所有可用数据源（排除不支持的和熔断的）"""
        domain_caps = self._matrix.get(domain, {})
        return [
            src for src, level in domain_caps.items()
            if level != SupportLevel.NONE
        ]

    def get_ordered_sources(
        self,
        domain: str,
        user_priority: Optional[List[str]] = None,
        disabled_sources: Optional[List[str]] = None,
    ) -> List[str]:
        """
        获取指定数据域的候选数据源，按优先级排序。

        Args:
            domain: 数据域
            user_priority: 用户自定义优先级（覆盖默认）
            disabled_sources: 被禁用的数据源列表

        Returns:
            排序后的候选数据源列表（已排除不支持和禁用的）
        """
        disabled = set(disabled_sources or [])
        available = self.get_available_sources(domain)

        priority = user_priority or self._priorities.get(domain) or _DEFAULT_PRIORITY.get(domain, [])

        # 按优先级排序，过滤禁用和不支持的
        ordered = [src for src in priority if src in available and src not in disabled]

        # 补充不在优先级列表中但可用的源
        for src in available:
            if src not in ordered and src not in disabled:
                ordered.append(src)

        return ordered

    def set_user_priority(self, domain: str, sources: List[str]) -> None:
        """设置用户自定义优先级"""
        self._priorities[domain] = sources

    @staticmethod
    def get_default_priority(domain: str) -> List[str]:
        """获取默认优先级"""
        return list(_DEFAULT_PRIORITY.get(domain, []))

    def get_all_domains(self) -> List[str]:
        """获取所有数据域"""
        return list(self._matrix.keys())

    def get_matrix_summary(self) -> Dict[str, Dict[str, str]]:
        """获取完整能力矩阵摘要（用于前端展示）"""
        return {
            domain: {src: level.value for src, level in caps.items()}
            for domain, caps in self._matrix.items()
        }
