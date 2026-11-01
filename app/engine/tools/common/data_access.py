"""工具层数据访问公共函数。

「读取 → 库空自动补数 → 再读」的编排已下沉到数据层
（DataInterface.read(auto_refresh=True)，见 app/data/core/interface.py）；
本模块保留为同步上下文的薄封装，engine 工具统一经此取数，
符号归一化（000001.SZ/sz000001/1 → 000001）同样由数据层完成。
"""

import logging
from typing import Any, Dict, Optional

from app.core.async_utils import run_async

logger = logging.getLogger(__name__)


def read_with_refresh(
    market: str,
    domain: str,
    symbol: Optional[str] = None,
    timeout: int = 30,
    **read_kwargs: Any,
) -> Optional[Dict[str, Any]]:
    """经 DataInterface 读取数据；库空时数据层自动补数后重读一次。

    Args:
        market: 市场类型（CN/HK/US）
        domain: 数据域（daily_quotes / financial_data / ...）
        symbol: 股票代码（容忍多种写法，数据层自动归一）；无 symbol 时不触发补数
        timeout: 数据层按需刷新超时秒数
        **read_kwargs: 透传给 di.read 的参数（start_date/end_date/filters 等）

    Returns:
        DataInterface.read 的完整 envelope（含 data/freshness/auto_refreshed 等），
        无数据或读取失败时返回 None。不抛异常，失败只记 warning。
    """
    from app.data.core.interface import DataInterface

    di = DataInterface.get_instance()

    try:
        result = run_async(
            di.read(
                market, domain, symbol=symbol,
                auto_refresh=True, refresh_timeout=timeout,
                **read_kwargs,
            )
        )
    except Exception as e:
        logger.warning(f"[data_access] 读取 {market}/{domain}/{symbol} 失败: {e}")
        return None

    if result.get("data"):
        return result
    return None
