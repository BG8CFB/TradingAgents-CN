"""
内置工具统一注册表

替代各模块的 TOOL_FUNCTIONS / DATA_SOURCE_MAP / ANALYST_MAP 三件套。
所有工具元数据集中管理，按数据域组织。
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class BuiltinToolSpec:
    """内置工具规格声明"""

    tool_id: str
    display_name: str
    domains: List[str]
    markets: List[str]
    fn: Callable
    inject_args: Dict[str, Any]
    description: str
    non_standard: bool = False
    availability_check: Optional[str] = None


def _resolve_market_type(ctx: dict) -> str:
    """根据 ticker 动态推导 market_type"""
    from app.utils.stock_utils import StockUtils, StockMarket
    market = StockUtils.identify_stock_market(ctx.get("ticker", ""))
    if market == StockMarket.HONG_KONG:
        return "hk"
    elif market == StockMarket.US:
        return "us"
    return "cn"


def _lazy_import(module_path: str, func_name: str) -> Callable:
    """延迟导入工具函数，避免循环依赖"""
    def wrapper(*args, **kwargs):
        import importlib
        mod = importlib.import_module(module_path)
        fn = getattr(mod, func_name)
        return fn(*args, **kwargs)

    wrapper.__name__ = func_name
    wrapper.__qualname__ = func_name
    wrapper.__doc__ = ""
    return wrapper


def _build_registry() -> List[BuiltinToolSpec]:
    """构建全量工具注册表（延迟导入避免循环依赖）"""
    _M = "app.engine.tools.builtin.tools"

    return [
        # ── 标准数据域 ──

        BuiltinToolSpec(
            tool_id="daily_quotes",
            display_name="日线行情",
            domains=["daily_quotes"],
            markets=["CN", "HK", "US"],
            fn=_lazy_import(f"{_M}.market", "get_stock_data"),
            inject_args={"stock_code": "ticker"},
            description="股票日线行情数据（开盘价、最高价、最低价、收盘价、成交量）",
        ),
        BuiltinToolSpec(
            tool_id="intraday_quotes",
            display_name="分钟级行情",
            domains=["intraday_quotes"],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.market", "get_stock_data_minutes"),
            inject_args={
                "stock_code": "ticker",
                "market_type": _resolve_market_type,
                "freq": "30min",
            },
            description="分钟级 K 线数据（1min/5min/15min/30min/60min）",
        ),
        BuiltinToolSpec(
            tool_id="market_quotes",
            display_name="指数行情",
            domains=["market_quotes"],
            markets=["CN", "HK", "US"],
            fn=_lazy_import(f"{_M}.market", "get_index_data"),
            inject_args={"stock_code": "ticker"},
            description="指数日线行情数据",
        ),
        BuiltinToolSpec(
            tool_id="financial_data",
            display_name="财务报表",
            domains=["financial_data"],
            markets=["CN", "HK", "US"],
            fn=_lazy_import(f"{_M}.fundamentals", "get_company_performance_unified"),
            inject_args={"stock_code": "ticker"},
            description="公司业绩预告、快报、财务指标、利润表、资产负债表、现金流量表",
        ),
        BuiltinToolSpec(
            tool_id="fundamentals",
            display_name="基本面综合",
            domains=["daily_quotes", "financial_data", "basic_info"],
            markets=["CN", "HK", "US"],
            fn=_lazy_import(f"{_M}.fundamentals", "get_stock_fundamentals"),
            inject_args={"stock_code": "ticker", "current_date": "trade_date"},
            description="基本面综合分析（价格走势 + 财务数据 + 公司信息）",
        ),
        BuiltinToolSpec(
            tool_id="news",
            display_name="新闻数据",
            domains=["news"],
            markets=["CN", "HK", "US"],
            fn=_lazy_import(f"{_M}.news", "get_stock_news"),
            inject_args={"stock_code": "ticker", "max_results": 15},
            description="股票相关新闻（标题、来源、时间、摘要、情绪）",
        ),
        BuiltinToolSpec(
            tool_id="sentiment",
            display_name="情绪分析",
            domains=["news"],
            markets=["CN", "HK", "US"],
            fn=_lazy_import(f"{_M}.sentiment", "get_stock_sentiment"),
            inject_args={"stock_code": "ticker", "current_date": "trade_date"},
            description="基于新闻情感标签的市场情绪统计（正面/负面/中性计数与评分）",
        ),

        # ── CN 特定数据域（已纳入标准 DataInterface 域） ──

        BuiltinToolSpec(
            tool_id="china_market",
            display_name="市场概览",
            domains=["market_quotes"],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.china_market", "get_china_market_overview"),
            inject_args={"date": "trade_date"},
            description="A股市场指数 + 板块涨跌概览",
        ),
        BuiltinToolSpec(
            tool_id="dragon_tiger",
            display_name="龙虎榜",
            domains=["dragon_tiger"],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.china_market", "get_dragon_tiger_inst"),
            inject_args={"ts_code": "ticker", "trade_date": "trade_date_compact"},
            description="龙虎榜机构明细",
        ),
        BuiltinToolSpec(
            tool_id="block_trade",
            display_name="大宗交易",
            domains=["block_trade"],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.china_market", "get_block_trade"),
            inject_args={"code": "ticker"},
            description="大宗交易数据",
        ),
        BuiltinToolSpec(
            tool_id="money_flow",
            display_name="资金流向",
            domains=["money_flow"],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.capital_flow", "get_money_flow"),
            inject_args={"ts_code": "ticker", "query_type": "stock"},
            description="个股资金流向数据",
        ),
        BuiltinToolSpec(
            tool_id="margin_trade",
            display_name="融资融券",
            domains=["margin_trading"],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.capital_flow", "get_margin_trade"),
            inject_args={"data_type": "margin", "ts_code": "ticker"},
            description="融资融券数据",
        ),
        BuiltinToolSpec(
            tool_id="daily_indicators",
            display_name="估值指标",
            domains=["daily_indicators"],
            markets=["CN", "HK", "US"],
            fn=_lazy_import(f"{_M}.market", "get_stock_indicators"),
            inject_args={"stock_code": "ticker"},
            description="股票估值指标（PE/PB/PS/市值/换手率等）",
        ),
    ]


BUILTIN_TOOL_REGISTRY: List[BuiltinToolSpec] = _build_registry()

# 按工具 ID 查找的索引
_TOOL_ID_INDEX: Dict[str, BuiltinToolSpec] = {s.tool_id: s for s in BUILTIN_TOOL_REGISTRY}


def get_spec_by_id(tool_id: str) -> Optional[BuiltinToolSpec]:
    """按 tool_id 查找工具规格"""
    return _TOOL_ID_INDEX.get(tool_id)


def get_specs_by_ids(tool_ids: List[str]) -> List[BuiltinToolSpec]:
    """按 tool_id 列表查找，忽略不存在的"""
    return [_TOOL_ID_INDEX[tid] for tid in tool_ids if tid in _TOOL_ID_INDEX]
