"""A 股股票名称查询工具 — 通过腾讯行情接口获取，供所有数据源共享使用。"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_name_cache: Dict[str, str] = {}


def infer_exchange(symbol: str) -> str:
    """根据股票代码推断交易所。

    Args:
        symbol: 6位纯数字股票代码（不带后缀），如 "000001"

    Returns:
        交易所代码: "SSE"（上交所）/ "SZSE"（深交所）/ "BSE"（北交所）/ ""（未知）
    """
    if symbol.startswith(("60", "68", "90")):
        return "SSE"
    elif symbol.startswith(("00", "30", "20")):
        return "SZSE"
    elif symbol.startswith(("4", "8")):
        return "BSE"
    return ""


def get_stock_name_sync(symbol: str) -> Optional[str]:
    """通过腾讯行情接口快速获取股票名称（同步版本）。

    Args:
        symbol: 6位纯数字股票代码（不带后缀），如 "000001"
    """
    if symbol in _name_cache:
        return _name_cache[symbol]

    import requests as req

    if symbol.startswith(("6", "9")):
        code = f"sh{symbol}"
    elif symbol.startswith(("4", "8")):
        code = f"bj{symbol}"
    else:
        code = f"sz{symbol}"

    try:
        resp = req.get(f"http://qt.gtimg.cn/q={code}", timeout=5)
        parts = resp.text.split("~")
        if len(parts) > 1 and parts[1]:
            name = parts[1].strip()
            _name_cache[symbol] = name
            return name
    except Exception as e:
        logger.debug(f"腾讯行情接口获取股票名称失败: {e}")

    # 备选: 从 DataInterface 获取
    try:
        from app.data.core.interface import DataInterface

        async def _read():
            di = DataInterface.get_instance()
            result = await di.read("CN", "basic_info", symbol=symbol)
            data = result.get("data")
            if data:
                doc = data[0] if isinstance(data, list) and data else data
                return doc.get("name")
            return None

        from app.core.async_utils import run_async
        name = run_async(_read())
        if name:
            _name_cache[symbol] = name
            return name
    except Exception as e:
        logger.debug(f"DataInterface 获取股票名称失败: {e}")

    return None
