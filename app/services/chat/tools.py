"""AI 问答助手的 5 个选股数据工具（func_to_tooldef 包装）。

约定：
- 参数全标量（func_to_tooldef 不支持嵌套 schema，复杂参数一律文本化）
- 全部只读（is_concurrency_safe=True，可同轮并发执行）
- 返回文本截断 ~2000 字符，超出部分以提示标记截断
- docstring 首段中文说明「何时该调用本工具」（供模型工具选择）
"""

import logging
from datetime import timedelta
from typing import Annotated, Any, Dict, List

from app.data.core.interface import DataInterface
from app.data.schema.domains.factor_scores import FACTOR_FIELDS, SCORE_FIELDS
from app.data.storage.mongo.repositories.factor_scores_repo import FactorScoresRepo
from app.llm.tools.wrappers import func_to_tooldef
from app.services.screening.strategy_service import StrategyService
from app.utils.timezone import now_tz

logger = logging.getLogger(__name__)

MAX_RESULT_CHARS = 2000


def _clip(text: str) -> str:
    """结果文本截断：超过上限保留前缀并标记，控制回传给模型的体积。"""
    if len(text) <= MAX_RESULT_CHARS:
        return text
    return text[:MAX_RESULT_CHARS] + "…(结果过长已截断，可缩小范围后重试)"


def _fmt(value: Any) -> str:
    """数值友好格式化：浮点保留 4 位有效小数，None 已在上游过滤。"""
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


async def search_stock(keyword: Annotated[str, "股票名称、拼音缩写或代码片段，如「平安」「000001」"]) -> str:
    """当用户用股票名称/简称提问、或需要把模糊说法解析成标准 6 位 A 股代码时调用本工具；
    返回候选列表（代码/名称/行业），命中多条时应向用户确认是哪一只。"""
    rows = await DataInterface.get_instance().search_basic_info("CN", keyword, limit=10)
    if not rows:
        return f"未找到与「{keyword}」匹配的 A 股，请确认名称或代码"
    lines = [f"「{keyword}」匹配到 {len(rows)} 只："]
    for r in rows:
        lines.append(f"- {r.get('symbol')} {r.get('name') or ''} 行业:{r.get('industry') or '未知'}")
    return _clip("\n".join(lines))


async def query_stock_factors(
    symbol: Annotated[str, "6 位 A 股代码，如 000001（名称需先经 search_stock 解析）"],
) -> str:
    """当用户询问某只个股的量化因子表现（动量/趋势/量能/资金/估值/质量 19 因子）
    或短线/均衡/价值风格评分时调用本工具；数据为每日批算的最新交易日快照。"""
    trade_date = await FactorScoresRepo().get_latest_trade_date("CN")
    if not trade_date:
        return "factor_scores 无数据（因子尚未批算），数据未同步，请建议用户先在数据中心完成同步"
    result = await DataInterface.get_instance().screen(
        "CN", "factor_scores", filters={"symbol": symbol, "trade_date": trade_date}, limit=1
    )
    items = result.get("items", [])
    if not items:
        return f"{symbol} 在最新因子日 {trade_date} 无数据（可能是未纳入计算的新股或代码有误）"
    r = items[0]
    lines = [f"{r.get('name') or symbol}({symbol}) 行业:{r.get('industry') or '未知'} 因子日期:{trade_date}"]
    factors = [f"{f}={_fmt(r[f])}" for f in FACTOR_FIELDS if r.get(f) is not None]
    scores = [f"{s}={_fmt(r[s])}" for s in SCORE_FIELDS if r.get(s) is not None]
    if factors:
        lines.append("因子: " + ", ".join(factors))
    if scores:
        lines.append("风格分: " + ", ".join(scores))
    if not factors and not scores:
        lines.append("该股因子值全部为空（输入数据不足）")
    return _clip("\n".join(lines))


async def run_strategy_screening(
    strategy_id: Annotated[str, "策略模板 id；不确定时传 list 获取策略清单"],
    top_n: Annotated[int, "返回前 N 条，默认 10"] = 10,
    industry: Annotated[str, "按行业过滤（可选），如「银行」；留空不过滤"] = "",
) -> str:
    """当用户要按某个策略筛选股票（如「短线强势」「均衡选股」「低估值」）时调用本工具；
    传入 strategy_id 前若不知道有哪些策略，先传 "list" 获取全部策略清单（id/名称/描述）。"""
    if not strategy_id or strategy_id == "list":
        strategies = await StrategyService().list_strategies()
        lines = [f"共 {len(strategies)} 个策略模板："]
        for s in strategies:
            lines.append(f"- {s['id']}: {s['name']}（{s.get('description', '')}）")
        return _clip("\n".join(lines))

    extra = None
    if industry:
        extra = [{"field": "industry", "op": "==", "value": industry}]
    try:
        result = await StrategyService().run_strategy(strategy_id, extra_conditions=extra, limit=max(1, min(top_n, 50)))
    except ValueError as e:
        return f"策略执行失败: {e}（可传 strategy_id=list 查看可用策略）"
    if not result.get("as_of"):
        return "factor_scores 无数据（因子尚未批算），数据未同步"
    lines = [
        f"策略 {result['strategy']}（风格 {result['style']}） "
        f"数据日 {result['as_of']} 共命中 {result['total']} 只，"
        f"返回前 {len(result['items'])} 只："
    ]
    for it in result["items"]:
        factors = ", ".join(f"{k}={_fmt(v)}" for k, v in (it.get("factors") or {}).items())
        lines.append(
            f"- {it.get('symbol')} {it.get('name') or ''} "
            f"行业:{it.get('industry') or '未知'} "
            f"得分:{_fmt(it.get('score'))}" + (f" {factors}" if factors else "")
        )
    return _clip("\n".join(lines))


async def query_daily_recommendations(
    strategy_id: Annotated[str, "策略 id（可选）；留空返回全部策略的当日推荐摘要"] = "",
) -> str:
    """当用户问「今天的推荐股票」「今日选股结果」或想看某策略当日落库推荐时调用本工具；
    读取的是每日定时任务生成的最新交易日推荐结论（含 AI 研判文字，若已生成）。"""
    data = await StrategyService().get_daily(strategy_id or None)
    trade_date = data.get("trade_date")
    if not trade_date:
        return "暂无当日推荐（每日推荐任务尚未生成），建议用户先在数据中心完成同步并等待定时任务执行"
    strategies = data.get("strategies", [])
    lines = [f"最新推荐交易日 {trade_date}："]
    for s in strategies:
        lines.append(
            f"- 策略 {s.get('strategy_name') or s.get('strategy_id')}"
            f"（风格 {s.get('style') or '未知'}）共 {s.get('total', 0)} 只"
        )
        for it in (s.get("items") or [])[:10]:
            insight = f" 研判:{it['insight']}" if it.get("insight") else ""
            lines.append(f"  · {it.get('symbol')} {it.get('name') or ''} 得分:{_fmt(it.get('score'))}{insight}")
    return _clip("\n".join(lines))


async def query_stock_quotes(
    symbol: Annotated[str, "6 位 A 股代码，如 000001"],
    days: Annotated[int, "回看交易日天数，默认 30"] = 30,
) -> str:
    """当用户询问某只个股近期行情（区间涨跌幅、最新成交量/成交额）或估值指标
    （PE/PB/股息率）时调用本工具；行情为日线序列，估值为最新交易日指标。"""
    di = DataInterface.get_instance()
    days = max(1, min(days, 120))
    # 自然日窗口取 2 倍，保证覆盖 days 个交易日
    start = (now_tz() - timedelta(days=days * 2)).strftime("%Y-%m-%d")
    quotes_resp = await di.read("CN", "daily_quotes", symbol, start_date=start)
    quotes: List[Dict] = quotes_resp.get("data") or []
    if not quotes:
        return f"{symbol} 无日线行情数据，数据未同步"
    quotes.sort(key=lambda q: q.get("trade_date") or "")
    first, last = quotes[0], quotes[-1]
    close_first, close_last = first.get("close"), last.get("close")
    lines = [f"{symbol} 日线行情（{first.get('trade_date')} ~ {last.get('trade_date')}，共 {len(quotes)} 个交易日）："]
    if close_first and close_last:
        chg = (close_last / close_first - 1) * 100
        lines.append(f"区间涨跌幅: {chg:.2f}%（{close_first} → {close_last}）")
    if last.get("volume") is not None:
        lines.append(f"最新成交量: {_fmt(last['volume'])}")
    if last.get("amount") is not None:
        lines.append(f"最新成交额: {_fmt(last['amount'])}")

    try:
        ind = await di.read_latest("CN", "daily_indicators", symbol)
    except Exception as e:  # noqa: BLE001 - 指标缺失不阻断行情输出
        logger.warning(f"[chat.tools] {symbol} daily_indicators 读取失败: {e}")
        ind = None
    if ind:
        val = [f"{k}={_fmt(ind[k])}" for k in ("pe_ttm", "pb", "dividend_yield") if ind.get(k) is not None]
        if val:
            lines.append(f"最新估值（{ind.get('trade_date') or '最新'}）: " + ", ".join(val))
    return _clip("\n".join(lines))


CHAT_TOOLS = [
    func_to_tooldef(f, is_concurrency_safe=True)
    for f in (
        search_stock,
        query_stock_factors,
        run_strategy_screening,
        query_daily_recommendations,
        query_stock_quotes,
    )
]
