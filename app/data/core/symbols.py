"""symbol 查询归一化 —— 全项目唯一权威。

消费方传入多种写法（交易所后缀/前缀、位数残缺、大小写不一）时，
统一归一为各域集合的存储口径后再查询：

- CN：6 位数字（``000001.SZ`` / ``sz000001`` / ``1`` → ``000001``）
- HK：5 位数字（``00700.HK`` / ``700`` → ``00700``）
- US：大写 ticker（``aapl`` → ``AAPL``）

非数字残码不做补零（如误传 ``AAPL`` 到 CN），保留原样由查询自然落空，
避免拼出 ``00AAPL`` 这类静默错码。
"""

import re

# 交易所后缀（大小写不敏感）：沪深北 + 沪深交所英文码 + 港交所 + 美股三大交易所
_SUFFIX_RE = re.compile(r"\.(SH|SZ|SS|BJ|XSHE|XSHG|HK|N|O|P)$", re.IGNORECASE)
# 交易所前缀（akshare 等源的习惯写法）：sz000001 / SH600000 / bj830799
_PREFIX_RE = re.compile(r"^(?:sz|sh|bj)", re.IGNORECASE)


def normalize_symbol(symbol: str, market: str) -> str:
    """查询符号归一（与各域集合存储口径一致）。

    Args:
        symbol: 任意写法的股票代码
        market: 市场类型（CN/HK/US，大小写不敏感）

    Returns:
        归一化后的 symbol；未知市场原样返回（去后缀后）。
    """
    s = str(symbol or "").strip()
    s = _SUFFIX_RE.sub("", s)
    m = (market or "").strip().upper()
    if m == "CN":
        s = _PREFIX_RE.sub("", s)
        return s.zfill(6) if s.isdigit() else s
    if m == "HK":
        return s.zfill(5) if s.isdigit() else s
    if m == "US":
        return s.upper()
    return s
