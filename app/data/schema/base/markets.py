"""市场枚举与元信息。"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict


class MarketType(str, Enum):
    CN = "CN"
    HK = "HK"
    US = "US"


@dataclass(frozen=True)
class MarketMeta:
    code: str
    name_zh: str
    timezone: str  # IANA 时区名
    currency: str
    trading_hours_morning: str  # 如 "09:30-12:00"
    trading_hours_afternoon: str  # 如 "13:00-16:00" 或空字符串
    symbol_format: str  # regex 描述
    exchanges: list  # 交易所代码列表
    collection_suffix: str  # _hk / _us；CN 为空字符串（基础名不加后缀）


MARKET_META: Dict[MarketType, MarketMeta] = {
    MarketType.CN: MarketMeta(
        code="CN",
        name_zh="A股",
        timezone="Asia/Shanghai",
        currency="CNY",
        trading_hours_morning="09:30-11:30",
        trading_hours_afternoon="13:00-15:00",
        symbol_format="6位数字(000001-689999)",
        exchanges=["SSE", "SZSE", "BSE"],
        collection_suffix="",
    ),
    MarketType.HK: MarketMeta(
        code="HK",
        name_zh="港股",
        timezone="Asia/Hong_Kong",
        currency="HKD",
        trading_hours_morning="09:30-12:00",
        trading_hours_afternoon="13:00-16:00",
        symbol_format="5位数字(00001-09999)",
        exchanges=["HKEX"],
        collection_suffix="_hk",
    ),
    MarketType.US: MarketMeta(
        code="US",
        name_zh="美股",
        timezone="America/New_York",
        currency="USD",
        trading_hours_morning="09:30-16:00",
        trading_hours_afternoon="",
        symbol_format="1-5位字母(AAPL, MSFT)",
        exchanges=["NYSE", "NASDAQ", "AMEX"],
        collection_suffix="_us",
    ),
}


def get_full_symbol(symbol: str, market: str, exchange: str = "") -> str:
    """返回带交易所后缀的完整代码。

    Args:
        symbol: 股票代码
        market: 市场 (CN/HK/US)
        exchange: 交易所（可选）
    """
    if market == "HK":
        code = str(symbol).replace(".HK", "").zfill(5)
        return f"{code}.HK"
    elif market == "CN":
        code = str(symbol)
        if exchange == "SSE" or code.startswith(("60", "68", "90")):
            # 注意：900xxx 是沪 B，60/68 是沪 A 主板/科创板
            return f"{code}.SH"
        elif exchange == "BSE" or code.startswith(("4", "8", "92")):
            return f"{code}.BJ"
        else:
            return f"{code}.SZ"
    else:
        return str(symbol).upper()


def normalize_symbol(symbol: str, market: str) -> str:
    """标准化股票代码（去掉后缀，补零）。

    .. deprecated:: 查询归一化的唯一权威是 ``app.data.core.symbols.normalize_symbol``
        （CN 补零 6 位、支持前缀/更多后缀）；本函数仅为 ``get_full_symbol``
        的伴生工具保留，勿在新代码中使用。
    """
    if market == "HK":
        return str(symbol).upper().replace(".HK", "").lstrip("0").zfill(5)
    elif market == "CN":
        s = str(symbol).upper()
        return s.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
    else:
        return str(symbol).upper()
