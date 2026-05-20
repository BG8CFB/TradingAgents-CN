"""
统一数据源提供器包（DEPRECATED — 计划删除）

⚠️⚠️⚠️ 本目录已废弃，将在未来版本中删除。⚠️⚠️⚠️

新架构位于 app.data.sources/，采用 Provider + Adapter + api/ 独立调用层设计。
所有新代码必须使用 app.data.sources/ 下的对应数据源。

仍引用本目录的模块（optimized.py、ForeignStockService、alpha_vantage 等）
将在后续迭代中逐步迁移。

⚠️ 新架构位于 app.data.sources/，采用 Provider + Adapter 分层设计。
本目录为旧版实现，仍被 engine/tools、worker、data/interface 等模块引用。
新代码请使用 app.data.sources/ 下的对应数据源。
"""
try:
    from .base_provider import BaseStockDataProvider
except ImportError:
    BaseStockDataProvider = None

# 导入中国市场提供器（新路径）
try:
    from .china import (
        AKShareProvider,
        TushareProvider,
        BaostockProvider as BaoStockProvider,
        AKSHARE_AVAILABLE,
        TUSHARE_AVAILABLE,
        BAOSTOCK_AVAILABLE
    )
except ImportError:
    # 向后兼容：尝试从旧路径导入
    try:
        from .tushare_provider import TushareProvider
    except ImportError:
        TushareProvider = None

    try:
        from .akshare_provider import AKShareProvider
    except ImportError:
        AKShareProvider = None

    try:
        from .baostock_provider import BaoStockProvider
    except ImportError:
        BaoStockProvider = None

    AKSHARE_AVAILABLE = AKShareProvider is not None
    TUSHARE_AVAILABLE = TushareProvider is not None
    BAOSTOCK_AVAILABLE = BaoStockProvider is not None

# 导入港股提供器
try:
    from .hk import (
        ImprovedHKStockProvider,
        get_improved_hk_provider,
        HK_PROVIDER_AVAILABLE
    )
except ImportError:
    ImprovedHKStockProvider = None
    get_improved_hk_provider = None
    HK_PROVIDER_AVAILABLE = False

# 导入美股提供器
try:
    from .us import (
        YFinanceUtils,
        OptimizedUSDataProvider,
        get_data_in_range,
        YFINANCE_AVAILABLE,
        OPTIMIZED_US_AVAILABLE,
        FINNHUB_AVAILABLE
    )
except ImportError:
    # 向后兼容：尝试从旧路径导入
    try:
        from ..yfin_utils import YFinanceUtils
    except ImportError:
        YFinanceUtils = None

    try:
        from ..optimized_us_data import OptimizedUSDataProvider
    except ImportError:
        OptimizedUSDataProvider = None

    try:
        from ..finnhub_utils import get_data_in_range
    except ImportError:
        get_data_in_range = None

    YFINANCE_AVAILABLE = YFinanceUtils is not None
    OPTIMIZED_US_AVAILABLE = OptimizedUSDataProvider is not None
    FINNHUB_AVAILABLE = get_data_in_range is not None


__all__ = [
    # 中国市场
    'TushareProvider',
    'AKShareProvider',
    'BaoStockProvider',
    'AKSHARE_AVAILABLE',
    'TUSHARE_AVAILABLE',
    'BAOSTOCK_AVAILABLE',

    # 港股
    'ImprovedHKStockProvider',
    'get_improved_hk_provider',
    'HK_PROVIDER_AVAILABLE',

    # 美股
    'YFinanceUtils',
    'OptimizedUSDataProvider',
    'get_data_in_range',
    'YFINANCE_AVAILABLE',
    'OPTIMIZED_US_AVAILABLE',
    'FINNHUB_AVAILABLE',

]
