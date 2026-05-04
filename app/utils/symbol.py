"""
股票代码符号工具集

集中管理 A 股 / 港股 / 美股代码的格式转换与规范化逻辑，
替代分散在 services、providers、routers 中的重复实现。

支持的输入格式示例:
    600000 / sh600000 / SH600000 / 600000.SH / 600000.SS
    000001 / sz000001 / SZ000001 / 000001.SZ
    430001 / 830001 / 430001.BJ
    00700 / 700.HK / 00700.HK
    AAPL
"""

import re
from typing import Optional, Tuple


# ---------------------------------------------------------------------------
# 正则常量
# ---------------------------------------------------------------------------
_RE_NUMERIC = re.compile(r"^\d+$")
_RE_ALPHA = re.compile(r"^[A-Z]+$")
# 匹配 "600000.SH" / "000001.SZ" / "430001.BJ" 等 Tushare 风格后缀
_RE_SUFFIX_TS = re.compile(r"^(\d{6})\.(SH|SZ|BJ)$", re.IGNORECASE)
# 匹配 "600000.SS" yfinance 风格上海后缀
_RE_SUFFIX_YF_SH = re.compile(r"^(\d{6})\.SS$", re.IGNORECASE)
# 匹配 "00700.HK"
_RE_SUFFIX_HK = re.compile(r"^(\d{1,5})\.HK$", re.IGNORECASE)
# 匹配 "sh600000" / "sz000001" 带市场前缀的格式
_RE_PREFIX_MARKET = re.compile(r"^(SH|SZ|BJ)(\d{6})$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

def _strip_raw(raw: str) -> str:
    """去除首尾空白并转大写。"""
    return raw.strip().upper()


def _extract_code_from_common_formats(raw: str) -> Tuple[Optional[str], Optional[str]]:
    """
    尝试从常见格式中提取纯数字代码和隐含市场信息。

    Returns:
        (code, market_hint): code 为纯 6 位数字(或 None),
            market_hint 为 "SH"/"SZ"/"BJ" 或 None
    """
    upper = raw.strip().upper()

    # 600000.SH → Tushare 格式
    m = _RE_SUFFIX_TS.match(upper)
    if m:
        return m.group(1), m.group(2).upper()

    # 600000.SS → yfinance 上海格式
    m = _RE_SUFFIX_YF_SH.match(upper)
    if m:
        return m.group(1), "SH"

    # SH600000 → 前缀格式
    m = _RE_PREFIX_MARKET.match(upper)
    if m:
        return m.group(2), m.group(1).upper()

    return None, None


def _normalize_code_for_market(code_str: str, market: str) -> str:
    """
    根据市场类型规范化代码：
      - CN: 去除前缀/后缀后 zfill(6)
      - HK: 去除前缀/后缀后 zfill(5)
      - US: 大写原样
    """
    market = market.upper()
    # 先尝试从常见 A 股格式中提取纯代码
    extracted, _ = _extract_code_from_common_formats(code_str)
    if extracted is not None:
        return extracted

    upper = code_str.strip().upper()

    # 移除可能的前缀
    for prefix in ("SH", "SZ", "BJ"):
        if upper.startswith(prefix):
            upper = upper[len(prefix):]
            break

    # 移除 .HK 后缀
    m = _RE_SUFFIX_HK.match(upper)
    if m:
        upper = m.group(1)

    if market == "HK":
        return upper.zfill(5)
    if market == "US":
        return upper
    # CN 及默认
    if _RE_NUMERIC.match(upper):
        return upper.zfill(6)
    return upper


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------

def to_six_digit(code: str) -> str:
    """
    将股票代码规范化为 6 位数字字符串。

    处理逻辑:
      - 去除前缀（sh/sz/bj）和后缀（.SH/.SZ/.BJ/.SS）
      - 纯数字输入：左补零至 6 位
      - 非数字输入（如美股代码）：原样返回（去除空白并大写）

    Examples::

        >>> to_six_digit("sh600000")
        '600000'
        >>> to_six_digit("600000.SH")
        '600000'
        >>> to_six_digit("1")
        '000001'
        >>> to_six_digit("AAPL")
        'AAPL'
    """
    if not code:
        return ""

    code_str = str(code).strip()

    # 尝试从带前缀/后缀格式中提取
    extracted, _ = _extract_code_from_common_formats(code_str)
    if extracted is not None:
        return extracted

    upper = code_str.upper()

    # 纯数字 → 左补零到 6 位
    if _RE_NUMERIC.match(upper):
        return upper.zfill(6)

    # 移除可能残留的前缀（如 sh/sz/bj 后面跟的不是 6 位的情况）
    for prefix in ("SH", "SZ", "BJ"):
        if upper.startswith(prefix):
            remainder = upper[len(prefix):]
            if _RE_NUMERIC.match(remainder):
                return remainder.zfill(6)
            return remainder

    # 非数字（美股等），原样大写返回
    return upper


def detect_market_and_code(raw: str) -> Tuple[str, str]:
    """
    检测股票代码所属市场并返回标准化代码。

    Args:
        raw: 原始股票代码字符串。

    Returns:
        (market, normalized_code):
            market  — "CN" / "HK" / "US"
            normalized_code — 标准化后的代码字符串

    Examples::

        >>> detect_market_and_code("600000")
        ('CN', '600000')
        >>> detect_market_and_code("00700.HK")
        ('HK', '00700')
        >>> detect_market_and_code("AAPL")
        ('US', 'AAPL')
    """
    if not raw:
        return ("CN", "")

    upper = _strip_raw(raw)

    # 先尝试从常见 A 股格式中提取
    extracted, _ = _extract_code_from_common_formats(upper)
    if extracted is not None:
        return ("CN", extracted)

    # 港股：带 .HK 后缀
    m = _RE_SUFFIX_HK.match(upper)
    if m:
        return ("HK", m.group(1).zfill(5))

    # 美股：纯字母
    if _RE_ALPHA.match(upper):
        return ("US", upper)

    # 港股：4-5 位纯数字
    if re.match(r"^\d{4,5}$", upper):
        return ("HK", upper.zfill(5))

    # A 股：6 位纯数字
    if re.match(r"^\d{6}$", upper):
        return ("CN", upper)

    # 去除可能的前缀后再试
    for prefix in ("SH", "SZ", "BJ"):
        if upper.startswith(prefix):
            remainder = upper[len(prefix):]
            if _RE_NUMERIC.match(remainder):
                return ("CN", remainder.zfill(6))

    # 默认当作 A 股处理
    return ("CN", to_six_digit(upper))


def _cn_code_to_ts(code: str) -> str:
    """
    根据代码前缀判断 A 股交易所并返回 Tushare 后缀。

    规则:
      - 60/68/90 开头 → .SH（上海证券交易所）
      - 00/30/20 开头 → .SZ（深圳证券交易所）
      - 8/4 开头 → .BJ（北京证券交易所）
    """
    if not code or not _RE_NUMERIC.match(code):
        return code

    if code.startswith(("60", "68", "90")):
        return f"{code}.SH"
    elif code.startswith(("00", "30", "20")):
        return f"{code}.SZ"
    elif code.startswith(("8", "4")):
        return f"{code}.BJ"
    else:
        return code


def _cn_code_to_yf(code: str) -> str:
    """
    根据代码前缀判断 A 股交易所并返回 yfinance 后缀。
    """
    if not code or not _RE_NUMERIC.match(code):
        return code

    if code.startswith(("60", "68", "90")):
        return f"{code}.SS"
    elif code.startswith(("00", "30", "20")):
        return f"{code}.SZ"
    elif code.startswith(("8", "4")):
        return f"{code}.BJ"
    else:
        return code


def to_full_symbol(code: str, market: Optional[str] = None) -> str:
    """
    生成 Tushare 风格的完整股票代码（带 .SH/.SZ/.BJ/.HK 后缀）。

    Args:
        code: 6 位股票代码或原始输入（会自动标准化）。
        market: 可选市场标识（"CN"/"HK"/"US"）。
            若不提供则自动检测。

    Returns:
        Tushare 风格的完整代码。

    Examples::

        >>> to_full_symbol("600000")
        '600000.SH'
        >>> to_full_symbol("000001")
        '000001.SZ'
        >>> to_full_symbol("430001")
        '430001.BJ'
        >>> to_full_symbol("00700", market="HK")
        '00700.HK'
        >>> to_full_symbol("AAPL", market="US")
        'AAPL'
    """
    if not code:
        return ""

    code_str = str(code).strip()

    # 已带有后缀 → 直接返回（统一后缀格式）
    upper = code_str.upper()

    # 已经是完整 Tushare 格式
    if _RE_SUFFIX_TS.match(upper):
        return upper
    if _RE_SUFFIX_YF_SH.match(upper):
        # .SS → .SH
        return f"{_RE_SUFFIX_YF_SH.match(upper).group(1)}.SH"
    if _RE_SUFFIX_HK.match(upper):
        return f"{_RE_SUFFIX_HK.match(upper).group(1).zfill(5)}.HK"

    # 规范化代码
    if market is None:
        market, code_str = detect_market_and_code(code_str)
    else:
        market = market.upper()
        code_str = _normalize_code_for_market(code_str, market)

    if market == "HK":
        return f"{code_str.zfill(5)}.HK"
    if market == "US":
        return code_str
    if market == "CN":
        return _cn_code_to_ts(code_str)

    # 无法识别 → 原样返回
    return code_str


def to_yf_symbol(code: str, market: Optional[str] = None) -> str:
    """
    生成 yfinance 风格的股票代码。

    Args:
        code: 6 位股票代码或原始输入（会自动标准化）。
        market: 可选市场标识（"CN"/"HK"/"US"）。
            若不提供则自动检测。

    Returns:
        yfinance 风格的完整代码。

    Mapping:
      - 上海 (SH) → .SS
      - 深圳 (SZ) → .SZ（与 Tushare 一致）
      - 北交所 (BJ) → .BJ（yfinance 暂无官方北交所后缀，保持 .BJ）
      - 港股 → .HK
      - 美股 → 无后缀

    Examples::

        >>> to_yf_symbol("600000")
        '600000.SS'
        >>> to_yf_symbol("000001")
        '000001.SZ'
        >>> to_yf_symbol("00700", market="HK")
        '00700.HK'
        >>> to_yf_symbol("AAPL", market="US")
        'AAPL'
    """
    if not code:
        return ""

    code_str = str(code).strip()
    upper = code_str.upper()

    # 已经是完整格式 → 转换
    m = _RE_SUFFIX_TS.match(upper)
    if m:
        c, suffix = m.group(1), m.group(2).upper()
        if suffix == "SH":
            return f"{c}.SS"
        return upper  # SZ/BJ 在 yfinance 中相同

    m = _RE_SUFFIX_YF_SH.match(upper)
    if m:
        return upper  # 已经是 .SS 格式

    m = _RE_SUFFIX_HK.match(upper)
    if m:
        return f"{m.group(1).zfill(5)}.HK"

    # 规范化代码
    if market is None:
        market, code_str = detect_market_and_code(code_str)
    else:
        market = market.upper()
        code_str = _normalize_code_for_market(code_str, market)

    if market == "HK":
        return f"{code_str.zfill(5)}.HK"
    if market == "US":
        return code_str
    if market == "CN":
        return _cn_code_to_yf(code_str)

    return code_str


def normalize_stock_code(raw: str) -> str:
    """
    通用股票代码规范化。

    - 去除首尾空白
    - A 股数字代码：左补零到 6 位
    - 港股数字代码：左补零到 5 位
    - 美股字母代码：大写
    - 去除已知的后缀 (.SH/.SZ/.BJ/.SS/.HK)，保留纯代码部分
    - 去除已知的前缀 (sh/sz/bj)

    Examples::

        >>> normalize_stock_code(" sh600000 ")
        '600000'
        >>> normalize_stock_code("600000.SH")
        '600000'
        >>> normalize_stock_code("00700.HK")
        '00700'
        >>> normalize_stock_code(" aapl ")
        'AAPL'
    """
    if not raw:
        return ""

    s = _strip_raw(raw)

    # 尝试提取 A 股带后缀的代码
    extracted, _ = _extract_code_from_common_formats(s)
    if extracted is not None:
        return extracted

    # 尝试提取 A 股带前缀的代码
    m = _RE_PREFIX_MARKET.match(s)
    if m:
        return m.group(2)

    # 港股带 .HK 后缀
    m = _RE_SUFFIX_HK.match(s)
    if m:
        return m.group(1).zfill(5)

    # 纯数字：根据位数判断
    if _RE_NUMERIC.match(s):
        if len(s) <= 6:
            # 可能是 A 股（6 位）或港股（4-5 位）
            # 如果补零后是 6 位且以 6/0/3/2/8/4 开头 → A 股
            padded6 = s.zfill(6)
            if len(s) == 6 or padded6[0] in ("6", "0", "3", "2", "8", "4"):
                return padded6
            # 否则当作港股 5 位
            return s.zfill(5)

    # 纯字母 → 美股
    if _RE_ALPHA.match(s):
        return s

    # 移除可能的前缀
    for prefix in ("SH", "SZ", "BJ"):
        if s.startswith(prefix):
            remainder = s[len(prefix):]
            if _RE_NUMERIC.match(remainder):
                return remainder.zfill(6)
            return remainder

    return s
