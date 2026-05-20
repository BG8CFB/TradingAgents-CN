"""
数据源适配器包（内部实现，与 app.data.sources/ 职责重叠）

仅被 screening_service、stock_data_service 等模块引用。
新代码请直接使用 app.data.sources/ 下的 Provider + Adapter。
"""
from .base import DataSourceAdapter
from .tushare_adapter import TushareAdapter
from .akshare_adapter import AKShareAdapter
from .baostock_adapter import BaoStockAdapter
from .manager import DataSourceManager

