"""指数基准宇宙与基准映射 — 单一事实源。

宇宙固定（<10 只基准指数），与各市场源 adapter 的能力耦合（改宇宙必伴随
改接入代码），因此用 Python 常量而非 yaml 配置。symbol 为指数规范码：
CN 带交易所后缀（与 tushare ts_code 一致、与 6 位股票码天然区分），
HK/US 用公认缩写（HSI / SPX），源方言（如 yfinance 的 ^HSI / ^GSPC）
一律在 adapter 内转换。
"""

from typing import Any, Dict, List, Optional

INDEX_UNIVERSE: Dict[str, Dict[str, Dict[str, Any]]] = {
    "CN": {
        "000300.SH": {"name": "沪深300", "boards": ["主板"], "default": True},
        "399006.SZ": {"name": "创业板指", "boards": ["创业板"]},
        "000688.SH": {"name": "科创50", "boards": ["科创板"]},
        "899050.BJ": {"name": "北证50", "boards": ["北交所"]},
    },
    "HK": {
        "HSI": {"name": "恒生指数", "boards": [], "default": True},
    },
    "US": {
        "SPX": {"name": "标普500", "boards": [], "default": True},
    },
}


def get_index_symbols(market: str) -> List[str]:
    """该市场需同步的指数规范码列表。"""
    return list(INDEX_UNIVERSE.get(market, {}).keys())


def resolve_benchmark(market: str, board: Optional[str]) -> Optional[str]:
    """market(+board) → 基准指数规范码。

    CN 按 board 精确匹配 boards 列表，未匹配/None → 该市场 default；
    HK/US 恒为市场 default。市场无宇宙（源未接入）返回 None。
    """
    universe = INDEX_UNIVERSE.get(market)
    if not universe:
        return None
    if market == "CN" and board:
        for symbol, meta in universe.items():
            if board in (meta.get("boards") or []):
                return symbol
    for symbol, meta in universe.items():
        if meta.get("default"):
            return symbol
    return None
