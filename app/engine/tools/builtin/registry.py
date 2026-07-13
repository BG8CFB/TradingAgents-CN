"""
内置工具统一注册表

替代各模块的 TOOL_FUNCTIONS / DATA_SOURCE_MAP / ANALYST_MAP 三件套。
所有工具元数据集中管理，按数据域组织。
"""
import logging
from dataclasses import dataclass
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
    # callable=True 的内置工具不预注入、而是作为 LLM 可主动调用的工具
    # （如 web_search，需按需实时检索；其余数据工具仍仅预注入）
    callable: bool = False


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
    """延迟导入工具函数，避免循环依赖

    保留 _lazy_module / _lazy_func_name 元信息，
    以便调用方通过 inspect 检测真实函数的异步属性。
    """
    _real_fn = None

    def wrapper(*args, **kwargs):
        nonlocal _real_fn
        if _real_fn is None:
            import importlib
            mod = importlib.import_module(module_path)
            _real_fn = getattr(mod, func_name)
        return _real_fn(*args, **kwargs)

    wrapper.__name__ = func_name
    wrapper.__qualname__ = func_name
    wrapper.__doc__ = ""
    wrapper._lazy_module = module_path
    wrapper._lazy_func_name = func_name
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
            inject_args={"stock_code": "ticker", "start_date": "start_date_90d"},
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
            display_name="历史日线",
            domains=["market_quotes"],
            markets=["CN", "HK", "US"],
            fn=_lazy_import(f"{_M}.market", "get_index_data"),
            inject_args={"stock_code": "ticker"},
            description="个股历史日线数据快照",
        ),
        BuiltinToolSpec(
            tool_id="financial_data",
            display_name="财务报表",
            domains=["financial_data"],
            markets=["CN", "HK", "US"],
            fn=_lazy_import(f"{_M}.fundamentals", "get_company_performance_unified"),
            inject_args={"stock_code": "ticker", "data_type": "indicators"},
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
            inject_args={"data_type": "margin", "ts_code": "ticker", "start_date": "start_date_30d"},
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
        BuiltinToolSpec(
            tool_id="technical_indicators",
            display_name="技术指标",
            domains=["daily_quotes"],
            markets=["CN", "HK", "US"],
            fn=_lazy_import(f"{_M}.market", "get_stock_technical_indicators"),
            inject_args={"stock_code": "ticker", "start_date": "start_date_90d"},
            description="股票技术指标（MA5/10/20/60、MACD、RSI、KDJ、布林带）",
        ),
        BuiltinToolSpec(
            tool_id="basic_info",
            display_name="基本信息",
            domains=["basic_info"],
            markets=["CN", "HK", "US"],
            fn=_lazy_import(f"{_M}.fundamentals", "get_stock_basic_info"),
            inject_args={"stock_code": "ticker"},
            description="股票基本信息（名称、行业、上市日期等）",
        ),

        # ── B 类新增数据域 ──

        BuiltinToolSpec(
            tool_id="northbound_flow",
            display_name="北向资金",
            domains=["northbound_flow"],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.capital_flow", "get_northbound_flow"),
            inject_args={"trade_date": "trade_date_compact"},
            description="沪深港通每日资金流向（北向/南向净流入）",
        ),
        BuiltinToolSpec(
            tool_id="northbound_holding",
            display_name="外资持仓",
            domains=["northbound_holding"],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.capital_flow", "get_northbound_holding"),
            inject_args={"ts_code": "ticker", "trade_date": "trade_date_compact"},
            description="沪深股通持股明细（外资持仓变动）",
        ),
        BuiltinToolSpec(
            tool_id="share_unlock",
            display_name="限售解禁",
            domains=["share_unlock"],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.fundamentals", "get_share_unlock"),
            inject_args={"stock_code": "ticker"},
            description="限售股解禁数据（减持压力评估）",
        ),
        BuiltinToolSpec(
            tool_id="pledge",
            display_name="股权质押",
            domains=["pledge"],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.fundamentals", "get_pledge_data"),
            inject_args={"stock_code": "ticker"},
            description="股权质押统计数据（质押比例、爆仓风险）",
        ),
        BuiltinToolSpec(
            tool_id="trading_status",
            display_name="停复牌",
            domains=["trading_status"],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.market", "get_trading_status"),
            inject_args={"stock_code": "ticker", "trade_date": "trade_date_compact"},
            description="每日停复牌信息",
        ),
        BuiltinToolSpec(
            tool_id="price_limit",
            display_name="涨跌停价格",
            domains=["price_limit"],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.market", "get_price_limit"),
            inject_args={"stock_code": "ticker", "trade_date": "trade_date_compact"},
            description="每日涨跌停价格数据",
        ),
        BuiltinToolSpec(
            tool_id="index_data",
            display_name="指数行情",
            domains=["index_data"],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.market", "get_index_daily_data"),
            inject_args={"stock_code": "ticker"},
            description="指数日线行情和成分权重",
        ),
        BuiltinToolSpec(
            tool_id="chip_distribution",
            display_name="筹码分布",
            domains=["chip_distribution"],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.market", "get_chip_distribution"),
            inject_args={"stock_code": "ticker", "trade_date": "trade_date_compact"},
            description="每日筹码分布和胜率数据",
        ),

        # ── 行业板块 / 业绩 / 连板 / 分红 ──

        BuiltinToolSpec(
            tool_id="sw_daily",
            display_name="申万行业指数",
            domains=["sw_daily"],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.sector", "get_sw_daily"),
            inject_args={"trade_date": "trade_date_compact"},
            description="申万行业指数日行情（板块强弱、行业轮动分析）",
        ),
        BuiltinToolSpec(
            tool_id="ths_daily",
            display_name="同花顺板块行情",
            domains=["ths_daily"],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.sector", "get_ths_daily"),
            inject_args={"trade_date": "trade_date_compact"},
            description="同花顺概念/行业板块行情",
        ),
        BuiltinToolSpec(
            tool_id="forecast",
            display_name="业绩预告",
            domains=["forecast"],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.fundamentals", "get_forecast"),
            inject_args={"stock_code": "ticker"},
            description="上市公司业绩预告（预增/预减/扭亏/首亏等）",
        ),
        BuiltinToolSpec(
            tool_id="express",
            display_name="业绩快报",
            domains=["express"],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.fundamentals", "get_express"),
            inject_args={"stock_code": "ticker"},
            description="上市公司业绩快报（提前披露的营收/净利润等）",
        ),
        BuiltinToolSpec(
            tool_id="limit_step",
            display_name="连板天梯",
            domains=["limit_step"],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.limit_step_tool", "get_limit_step"),
            inject_args={"trade_date": "trade_date_compact"},
            description="涨停连板天梯数据（连板梯队、市场情绪）",
        ),
        BuiltinToolSpec(
            tool_id="moneyflow_ind_dc",
            display_name="板块资金流向",
            domains=["moneyflow_ind_dc"],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.sector", "get_moneyflow_ind_dc"),
            inject_args={"trade_date": "trade_date_compact"},
            description="东方财富板块资金流向（哪个板块在吸金/出逃）",
        ),
        BuiltinToolSpec(
            tool_id="dividend",
            display_name="分红送股",
            domains=["dividend"],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.fundamentals", "get_dividend"),
            inject_args={"stock_code": "ticker"},
            description="上市公司分红送股数据（股息率、送转股）",
        ),

        # ── 通用工具 ──

        BuiltinToolSpec(
            tool_id="web_search",
            display_name="智能搜索",
            domains=[],
            markets=["CN", "HK", "US"],
            fn=_lazy_import(f"{_M}.web_search", "web_search"),
            inject_args={"stock_code": "ticker"},
            callable=True,
            description="统一智能搜索：传 stock_code+data_type 做个股定向权威站点搜索(news/financial/margin/chip/policy/industry...)，仅传 query 做自由网络搜索(宏观/政策/行业动态等外围最新信息)。支持 time_range=day/week/month/quarter/year 或 after:YYYY-MM-DD 限定时效；结果附 publish_date(发布时间)与 source_tier(来源分级 official/media/forum)，便于引用与可信度判断。",
        ),
        BuiltinToolSpec(
            tool_id="industry_average",
            display_name="行业平均估值",
            domains=[],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.web_search", "get_industry_average"),
            inject_args={"stock_code": "ticker"},
            description="获取股票所在行业的平均PE/PB/PS估值指标，用于行业对比分析",
        ),
        BuiltinToolSpec(
            tool_id="community_sentiment",
            display_name="社区情绪",
            domains=[],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.community", "get_community_sentiment"),
            inject_args={"stock_code": "ticker"},
             description="个股社区讨论热度、综合评分、机构参与度等量化指标",
        ),

        # ── 补齐数据域（此前未暴露为工具） ──

        BuiltinToolSpec(
            tool_id="adj_factors",
            display_name="复权因子",
            domains=["adj_factors"],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.market", "get_adj_factors"),
            inject_args={"stock_code": "ticker", "start_date": "start_date_90d"},
            description="股票复权因子数据（前/后复权比例，用于精确收益计算）",
        ),
        BuiltinToolSpec(
            tool_id="trade_calendar",
            display_name="交易日历",
            domains=["trade_calendar"],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.market", "get_trade_calendar"),
            inject_args={"start_date": "start_date_90d"},
            description="A股交易日历（开市/休市日期，用于交易窗口判断）",
        ),
        BuiltinToolSpec(
            tool_id="index_basic",
            display_name="指数基本信息",
            domains=["index_basic"],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.market", "get_index_basic"),
            inject_args={},
            description="指数列表及元数据（指数代码、名称、类别、成分股数）",
        ),
        BuiltinToolSpec(
            tool_id="index_dailybasic",
            display_name="指数每日指标",
            domains=["index_dailybasic"],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.market", "get_index_daily_basic"),
            inject_args={"stock_code": "ticker", "start_date": "start_date_90d"},
            description="指数每日指标（换手率、市盈率、市净率、市值等）",
        ),
        BuiltinToolSpec(
            tool_id="index_global",
            display_name="国际指数",
            domains=["index_global"],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.market", "get_index_global"),
            inject_args={},
            description="国际/海外指数行情（如美股三大指数、恒生、日经等）",
        ),
        BuiltinToolSpec(
            tool_id="index_weight",
            display_name="指数成分权重",
            domains=["index_weight"],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.market", "get_index_weight"),
            inject_args={"stock_code": "ticker", "trade_date": "trade_date_compact"},
            description="指数成分股及权重（用于分析指数贡献度、调仓影响）",
        ),
        BuiltinToolSpec(
            tool_id="announcement",
            display_name="公司公告",
            domains=["announcement"],
            markets=["CN"],
            fn=_lazy_import(f"{_M}.news", "get_announcements"),
            inject_args={"stock_code": "ticker", "start_date": "start_date_90d"},
            description="上市公司公告（重大事项、股东大会、业绩披露等）",
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


def register_skill_entrypoint(spec: BuiltinToolSpec) -> bool:
    """
    运行时追加注册 skill 脚本入口为 builtin 工具。

    由 SkillRegistry 发现 skill 的 entrypoints 后调用。
    同名 tool_id 重复注册会被拒绝（避免覆盖）。

    Args:
        spec: skill 脚本的 BuiltinToolSpec（tool_id 形如 {skill}.{entrypoint}）

    Returns:
        注册是否成功
    """
    if spec.tool_id in _TOOL_ID_INDEX:
        logger.warning(f"[BuiltinRegistry] tool_id 已存在，拒绝覆盖: {spec.tool_id}")
        return False
    BUILTIN_TOOL_REGISTRY.append(spec)
    _TOOL_ID_INDEX[spec.tool_id] = spec
    logger.info(f"[BuiltinRegistry] 已注册 skill 入口: {spec.tool_id}")
    return True


def unregister_skill_entrypoints(prefix: str) -> int:
    """
    按前缀（通常是 {skill_name}.）批量卸载 skill 工具。

    Args:
        prefix: skill_name 前缀（自动加 '.'）

    Returns:
        卸载的工具数量
    """
    full_prefix = prefix if prefix.endswith(".") else prefix + "."
    to_remove = [tid for tid in _TOOL_ID_INDEX if tid.startswith(full_prefix)]
    for tid in to_remove:
        spec = _TOOL_ID_INDEX.pop(tid)
        BUILTIN_TOOL_REGISTRY.remove(spec)
    if to_remove:
        logger.info(f"[BuiltinRegistry] 已卸载 {len(to_remove)} 个 skill 入口: {prefix}")
    return len(to_remove)


def is_skill_tool(tool_id: str) -> bool:
    """判断 tool_id 是否属于 skill 脚本入口（通过约定：含 '.' 分隔）"""
    return "." in tool_id and tool_id in _TOOL_ID_INDEX
