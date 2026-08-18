"""股票代码清洗工具"""
import re


def clean_symbol(symbol: str, market: str = "CN") -> str:
    """清洗股票代码，去掉交易所后缀以匹配数据库存储格式。

    Args:
        symbol: 原始股票代码，如 "000001.SZ"、"00700.HK"、"AAPL"
        market: 市场类型 "CN" / "HK" / "US"
    """
    if not symbol:
        return symbol
    if market == "CN":
        return re.sub(r'\.(SH|SZ|BJ|SS|XSHE|XSHG)$', '', symbol, flags=re.IGNORECASE).zfill(6)
    elif market == "HK":
        return re.sub(r'\.HK$', '', symbol, flags=re.IGNORECASE).zfill(5)
    return symbol.upper()
