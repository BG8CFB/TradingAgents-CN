"""
智能搜索工具 — 基于 Bing 的网页搜索

统一两种搜索模式：
1) 个股定向搜索：传入 stock_code（及可选 data_type），自动解析公司名并在权威财经站点
   （东方财富/同花顺/新浪/雪球）做多轮定向搜索。当数据库缺少某只股票的具体数据时使用。
2) 泛化网络搜索：仅传入 query，做自由关键词的互联网搜索，适合获取宏观市场、政策、
   行业动态等外围最新信息。

无需 API Key，通过 Bing HTML 搜索获取结果。
"""
import datetime
import logging
import re
from typing import Optional
from html import unescape
from urllib.parse import urlparse

import requests

from app.engine.tools.common.tool_result import success_result, error_result, format_tool_result, ErrorCodes

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


# ── 通用 Bing 搜索 ──

def _search_bing(query: str, max_results: int, time_filter: str = "") -> list:
    """通过 Bing 搜索获取结果。

    time_filter: 追加到查询的时效限定后缀（如 " after:2026-07-01"）。
    """
    url = "https://www.bing.com/search"
    params = {"q": (query + time_filter).strip(), "count": str(max_results * 2)}

    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.debug(f"Bing 请求失败: {e}")
        return []

    return _parse_bing_results(resp.text, max_results)


def _parse_bing_results(html: str, max_results: int) -> list:
    """从 Bing 搜索结果页面解析，附加发布时间与来源可信分级。"""
    results = []

    # Bing 结果格式: <li class="b_algo"><h2><a href="URL">TITLE</a></h2><p>SNIPPET</p>
    # 或者 <div class="b_algo"><h2><a href="URL">TITLE</a></h2><div class="b_caption"><p>SNIPPET</p>
    item_pattern = re.compile(
        r'<li[^>]*class="b_algo"[^>]*>(.*?)</li>',
        re.DOTALL
    )
    link_pattern = re.compile(
        r'<h2[^>]*><a[^>]*href="([^"]*)"[^>]*>(.*?)</a></h2>',
        re.DOTALL
    )
    snippet_pattern = re.compile(
        r'<p[^>]*>(.*?)</p>',
        re.DOTALL
    )

    items = item_pattern.findall(html)

    for item_html in items:
        if len(results) >= max_results:
            break

        link_match = link_pattern.search(item_html)
        if not link_match:
            continue

        url = link_match.group(1)
        title = _strip_tags(unescape(link_match.group(2))).strip()

        if not title or not url:
            continue
        # 过滤 Bing 自身链接
        if "bing.com" in url or "microsoft.com" in url:
            continue

        snippet = ""
        snippet_match = snippet_pattern.search(item_html)
        if snippet_match:
            snippet = _strip_tags(unescape(snippet_match.group(1))).strip()

        results.append({
            "title": title,
            "url": url,
            "snippet": snippet or "无摘要",
            "publish_date": _extract_date(item_html),
            "source_tier": _classify_source(url),
        })

    # 如果 Bing 标准格式解析失败，尝试备用格式
    if not results:
        results = _parse_bing_fallback(html, max_results)

    return results


def _parse_bing_fallback(html: str, max_results: int) -> list:
    """Bing 备用解析（<div class="b_algo"> 格式）。"""
    results = []
    item_pattern = re.compile(
        r'<div[^>]*class="b_algo"[^>]*>(.*?)</div>\s*</div>',
        re.DOTALL
    )
    link_pattern = re.compile(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', re.DOTALL)

    for item_html in item_pattern.findall(html):
        if len(results) >= max_results:
            break
        links = link_pattern.findall(item_html)
        for url, title in links:
            title = _strip_tags(unescape(title)).strip()
            if title and url and "bing.com" not in url:
                results.append({
                    "title": title,
                    "url": url,
                    "snippet": "无摘要",
                    "publish_date": _extract_date(item_html),
                    "source_tier": _classify_source(url),
                })
                break

    return results


def _strip_tags(html_str: str) -> str:
    """移除 HTML 标签。"""
    return re.sub(r"<[^>]+>", "", html_str)


# ── 来源可信分级 & 时效 ──

# 来源域名 → 可信层级
#   official: 交易所/监管机构/央行/统计局/政府/巨潮等官方披露
#   media:    主流财经媒体、券商研报平台
#   forum:    股吧、微博等社交/论坛（仅作情绪参考，须标注待验证）
_SOURCE_TIERS = {
    # 官方 / 监管
    "cninfo.com.cn": "official",
    "sse.com.cn": "official",
    "szse.cn": "official",
    "csrc.gov.cn": "official",
    "pbc.gov.cn": "official",
    "stats.gov.cn": "official",
    "ndrc.gov.cn": "official",
    "mof.gov.cn": "official",
    "gov.cn": "official",
    # 主流媒体 / 研报
    "eastmoney.com": "media",
    "finance.sina.com.cn": "media",
    "10jqka.com.cn": "media",
    "stcn.com": "media",
    "cs.com.cn": "media",
    "cnstock.com": "media",
    "yicai.com": "media",
    "21jingji.com": "media",
    "xueqiu.com": "media",
    # 论坛 / 社交
    "guba.eastmoney.com": "forum",
    "weibo.com": "forum",
}


def _classify_source(url: str) -> str:
    """根据来源域名返回可信层级 official/media/forum/other（取最长匹配域名，避免父域误判）。"""
    try:
        host = (urlparse(url).netloc or "").lower()
    except Exception:
        return "other"
    best = None
    for domain, tier in _SOURCE_TIERS.items():
        if host == domain or host.endswith("." + domain):
            if best is None or len(domain) > len(best[0]):
                best = (domain, tier)
    return best[1] if best else "other"


# 发布时间提取（最佳努力）：匹配 2026年7月1日 / 2026-07-01 / 2026/7/1
_DATE_PATTERN = re.compile(
    r"(\d{4})\s*[-年/]\s*(\d{1,2})\s*[-月/]\s*(\d{1,2})\s*日?"
)


def _extract_date(item_html: str) -> Optional[str]:
    """从结果片段中尽力提取发布日期，返回 YYYY-MM-DD 或 None。"""
    m = _DATE_PATTERN.search(item_html or "")
    if not m:
        return None
    try:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    except Exception:
        return None
    return None


# time_range 别名 → 天数
_TIME_RANGE_DAYS = {
    "day": 1,
    "week": 7,
    "month": 30,
    "quarter": 90,
    "year": 365,
}


def _build_time_filter(time_range) -> str:
    """将 time_range 转为 Bing 的 after:YYYY-MM-DD 后缀；无效值返回空串。"""
    if not time_range:
        return ""
    s = str(time_range).strip().lower()
    if s in _TIME_RANGE_DAYS:
        after = (datetime.date.today() - datetime.timedelta(days=_TIME_RANGE_DAYS[s]))
        return f" after:{after.strftime('%Y-%m-%d')}"
    # 支持 after:YYYY-MM-DD 或裸日期 YYYY-MM-DD / YYYY/MM/DD
    m = re.match(r"(?:after:)?(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", s)
    if m:
        return f" after:{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ""


# ── 个股定向搜索 ──

# 权威财经站点优先级
_AUTHORITATIVE_SITES = [
    "eastmoney.com",    # 东方财富
    "finance.sina.com.cn",  # 新浪财经
    "10jqka.com.cn",    # 同花顺
    "xueqiu.com",       # 雪球
    "stockpage.10jqka.com.cn",  # 同花顺个股
    "quote.eastmoney.com",  # 东方财富行情
]

# 数据类型 → 搜索关键词映射
_DATA_TYPE_KEYWORDS = {
    "news": "最新新闻 公告",
    "financial": "财务报表 业绩",
    "dragon_tiger": "龙虎榜",
    "margin": "融资融券",
    "block_trade": "大宗交易",
    "northbound": "北向资金 持仓",
    "chip": "筹码分布",
    "sentiment": "股吧 讨论 研报",
    "analyst": "研报 分析师 评级",
    "dividend": "分红 送股",
    "pledge": "股权质押",
    "unlock": "解禁 限售股",
    "announcement": "公告",
    # 多层级搜索
    "market": "A股市场 行情 政策",
    "industry": "行业 动态 趋势",
    "industry_chain": "产业链 上下游 供需",
    "upstream": "上游 原材料 供应",
    "downstream": "下游 需求 应用",
    # 政策相关搜索
    "policy": "政策 产业政策 扶持",
    "monetary_policy": "货币政策 降准 降息 MLF LPR",
    "fiscal_policy": "财政政策 基建投资 减税降费 专项债",
    "regulatory_policy": "监管政策 证监会 退市 减持",
    "industrial_policy": "产业政策 新能源 半导体 高端制造 机器人",
}


def web_search(
    query: str = None,
    stock_code: str = None,
    data_type: str = "news",
    max_results: int = 5,
    time_range: str = None,
    **kwargs,
) -> str:
    """
    统一智能搜索工具，支持两种模式 + 时效/来源增强：

    1) 个股定向搜索：传入 stock_code（及可选 data_type），自动解析公司名并在权威财经站点
       （东方财富/同花顺/新浪/雪球）做多轮定向搜索。当数据库缺少某只股票的具体数据
       （新闻/财务/龙虎榜/融资融券/筹码/政策/行业等）时使用。
    2) 泛化网络搜索：仅传入 query，做自由关键词的互联网搜索，适合获取宏观市场、政策、
       行业动态等外围最新信息。

    时效与来源：
    - time_range: 限定结果时效，取值 day/week/month/quarter/year 或具体日期 after:YYYY-MM-DD。
      强烈建议每次都指定，以保证"最新"。
    - 每条结果携带 publish_date（尽力提取的发布时间）与 source_tier（official/media/forum/other），
      便于引用与可信度判断；底层为网页检索（snippet 级），非权威结构化数据，须交叉验证。

    调用约定（由 LLM 自行选择模式）：
      - 查某只股票的具体信息 → web_search(stock_code="000001", data_type="news", time_range="week")
      - 查宏观/政策/行业等无特定个股的信息 → web_search(query="央行最新货币政策", time_range="day")

    Args:
        query: 泛化搜索关键词（与 stock_code 二选一，stock_code 优先）
        stock_code: 股票代码，如 "000001"、"000001.SZ"（个股模式）
        data_type: 个股模式的数据类型: news/financial/dragon_tiger/margin/block_trade/
                   northbound/chip/sentiment/analyst/dividend/pledge/unlock/announcement/
                   market/industry/industry_chain/upstream/downstream/
                   policy/monetary_policy/fiscal_policy/regulatory_policy/industrial_policy
        max_results: 最大返回结果数，默认 5
        time_range: 时效窗口，day/week/month/quarter/year 或 after:YYYY-MM-DD

    Returns:
        JSON 格式的 ToolResult，包含搜索结果
    """
    # 兼容不同参数名
    if not query:
        query = kwargs.get("keyword") or kwargs.get("q") or kwargs.get("search_query") or kwargs.get("keywords")
    if not stock_code:
        stock_code = kwargs.get("ts_code") or kwargs.get("ticker") or kwargs.get("symbol")
    if not time_range:
        time_range = kwargs.get("time_range") or kwargs.get("timerange") or kwargs.get("since")

    if stock_code:
        return _stock_specific_search(stock_code, data_type, max_results, time_range=time_range, **kwargs)
    if query and str(query).strip():
        return _general_web_search(str(query).strip(), max_results, time_range=time_range)

    return format_tool_result(error_result(
        ErrorCodes.INVALID_PARAM,
        "必须提供 query（泛化搜索）或 stock_code（个股定向搜索）之一"
    ))


def _general_web_search(query: str, max_results: int, time_range: str = None) -> str:
    """泛化网络搜索：自由关键词，无站点过滤。"""
    try:
        results = _search_bing(query, max_results, _build_time_filter(time_range))
        if not results:
            return format_tool_result(error_result(
                ErrorCodes.DATA_FETCH_ERROR,
                f"未找到与 '{query}' 相关的结果",
                suggestion="尝试使用不同的关键词、放宽 time_range 或更简洁的搜索词"
            ))

        lines = [f"## 搜索结果: {query}\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"### {i}. {r['title']}")
            lines.append(f"**来源**: {r['url']}")
            if r.get("publish_date"):
                lines.append(f"**发布时间**: {r['publish_date']}")
            lines.append(f"**来源分级**: {r.get('source_tier', 'other')}")
            lines.append(f"{r['snippet']}\n")

        return format_tool_result(success_result("\n".join(lines)))

    except Exception as e:
        logger.error(f"web_search failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR,
            f"搜索失败: {str(e)}",
            suggestion="网络搜索暂时不可用，请稍后重试"
        ))


def _stock_specific_search(
    stock_code: str,
    data_type: str = "news",
    max_results: int = 5,
    time_range: str = None,
    **kwargs,
) -> str:
    """
    搜索特定股票的相关信息，自动使用公司名称在权威财经网站查找。

    当数据库中没有对应数据时，使用此工具从权威财经网站获取信息。
    比泛化搜索更精准，会自动识别公司名称并限定搜索范围。

    Args:
        stock_code: 股票代码，如 "000001"、"000001.SZ"
        data_type: 数据类型: news/financial/dragon_tiger/margin/block_trade/
                   northbound/chip/sentiment/analyst/dividend/pledge/unlock/announcement/
                   market/industry/industry_chain/upstream/downstream/
                   policy/monetary_policy/fiscal_policy/regulatory_policy/industrial_policy
        max_results: 最大返回结果数，默认 5
        time_range: 时效窗口，day/week/month/quarter/year 或 after:YYYY-MM-DD

    Returns:
        JSON 格式的 ToolResult，包含搜索结果
    """
    # 清洗代码
    clean_code = stock_code.replace('.SZ', '').replace('.SH', '').replace('.BJ', '') \
                           .replace('.sz', '').replace('.sh', '').replace('.bj', '').zfill(6)

    # 获取公司名称
    stock_name = _get_stock_name(clean_code)
    name_part = f"{stock_name}" if stock_name else clean_code

    # 构建搜索关键词
    keywords = _DATA_TYPE_KEYWORDS.get(data_type, data_type)

    # 行业相关搜索：先获取行业名称，用行业名作为主关键词
    industry_name = None
    if data_type in ("industry", "industry_chain", "upstream", "downstream"):
        industry_name = _get_stock_industry(clean_code)
        if industry_name:
            name_part = industry_name.replace("(A股)", "").strip()

    # 构建多轮搜索策略：先精准，再宽泛
    if data_type in ("industry", "industry_chain", "upstream", "downstream") and industry_name:
        queries = [
            f"{name_part} {keywords} site:eastmoney.com OR site:10jqka.com.cn",
            f"{name_part} {keywords} site:finance.sina.com.cn",
            f"{name_part} {keywords} 最新",
        ]
    elif data_type == "market":
        queries = [
            f"A股 {keywords} site:eastmoney.com OR site:10jqka.com.cn",
            f"A股 {keywords} 最新",
        ]
    elif data_type in ("policy", "monetary_policy", "fiscal_policy", "regulatory_policy", "industrial_policy"):
        # 政策相关搜索：使用更精准的关键词
        policy_keywords = {
            "policy": "政策 产业政策 扶持 2025 2026",
            "monetary_policy": "货币政策 降准 降息 MLF LPR 2025 2026",
            "fiscal_policy": "财政政策 基建投资 减税降费 专项债 2025 2026",
            "regulatory_policy": "监管政策 证监会 退市 减持 2025 2026",
            "industrial_policy": "产业政策 新能源 半导体 高端制造 机器人 2025 2026",
        }
        policy_kw = policy_keywords.get(data_type, keywords)
        queries = [
            f"{name_part} {policy_kw} site:eastmoney.com OR site:10jqka.com.cn",
            f"{name_part} {policy_kw} site:finance.sina.com.cn OR site:xueqiu.com",
            f"{name_part} {policy_kw} 最新",
        ]
    else:
        queries = [
            f"{clean_code} {name_part} {keywords} site:eastmoney.com OR site:10jqka.com.cn",
            f"{name_part} {keywords} site:finance.sina.com.cn OR site:xueqiu.com",
            f"{name_part} {keywords} 最新",
        ]

    # 时效限定：统一追加到每轮查询
    time_filter = _build_time_filter(time_range)
    if time_filter:
        queries = [q + time_filter for q in queries]

    # 搜索（逐轮尝试，直到有结果）
    try:
        results = []
        for q in queries:
            results = _search_bing(q, max_results)
            if results:
                break

        if not results:
            return format_tool_result(error_result(
                ErrorCodes.DATA_FETCH_ERROR,
                f"未找到 {name_part}({clean_code}) 的{data_type}相关信息",
                suggestion="尝试不同的 data_type 或确认股票代码正确"
            ))

        lines = [f"## {name_part}({clean_code}) {data_type} 搜索结果\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"### {i}. {r['title']}")
            lines.append(f"**来源**: {r['url']}")
            if r.get("publish_date"):
                lines.append(f"**发布时间**: {r['publish_date']}")
            lines.append(f"**来源分级**: {r.get('source_tier', 'other')}")
            lines.append(f"{r['snippet']}\n")

        return format_tool_result(success_result("\n".join(lines)))

    except Exception as e:
        logger.error(f"_stock_specific_search failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR, str(e)
        ))


def _get_stock_name(symbol: str) -> Optional[str]:
    """获取股票名称（同步）。"""
    try:
        from app.data.sources.cn.stock_name_utils import get_stock_name_sync
        return get_stock_name_sync(symbol)
    except Exception:
        return None


def _get_stock_industry(symbol: str) -> Optional[str]:
    """获取股票所属行业名称（同步，缓存结果）。"""
    ts_code = f"{symbol}.SZ" if symbol.startswith(('0', '3')) else f"{symbol}.SH"
    try:
        from app.data.sources.cn.tushare.api.connection import get_tushare_api
        conn = get_tushare_api()
        if not conn.is_available():
            return None
        df = conn.api.ths_index(type='I')
        if df is None or df.empty:
            return None
        for _, row in df.iterrows():
            try:
                m = conn.api.ths_member(ts_code=row['ts_code'])
                if m is not None and not m.empty and ts_code in m['con_code'].values:
                    return row['name']
            except Exception:
                continue
    except Exception:
        pass
    return None


def get_industry_average(
    stock_code: str = None,
    **kwargs,
) -> str:
    """
    获取股票所在行业的平均估值指标（PE/PB/PS/市值）。

    通过 tushare 行业分类获取同行业成分股，批量获取估值数据后计算平均值。

    Args:
        stock_code: 股票代码，如 "000001"、"000001.SZ"

    Returns:
        JSON 格式的 ToolResult，包含行业平均估值和个股对比
    """
    if not stock_code:
        stock_code = kwargs.get("ts_code") or kwargs.get("ticker") or kwargs.get("symbol")
    if not stock_code:
        return format_tool_result(error_result(
            ErrorCodes.INVALID_PARAM, "股票代码不能为空"
        ))

    clean_code = stock_code.replace('.SZ', '').replace('.SH', '').replace('.BJ', '') \
                           .replace('.sz', '').replace('.sh', '').replace('.bj', '').zfill(6)
    ts_code = f"{clean_code}.SZ" if clean_code.startswith(('0', '3')) else f"{clean_code}.SH"

    try:
        from app.data.sources.cn.tushare.api.connection import get_tushare_api
        import pandas as pd
        conn = get_tushare_api()
        if not conn.is_available():
            return format_tool_result(error_result(
                ErrorCodes.DATA_FETCH_ERROR, "Tushare 连接不可用"
            ))

        # 1. 获取股票所属行业（同花顺）
        df_members = conn.api.ths_member(ts_code='700408.TI')  # 先查软件行业
        industry_name = "未知"
        member_codes = []

        # 遍历主要行业找到该股票所属行业
        df_industries = conn.api.ths_index(type='I')
        if df_industries is not None and not df_industries.empty:
            for _, row in df_industries.iterrows():
                try:
                    m = conn.api.ths_member(ts_code=row['ts_code'])
                    if m is not None and not m.empty:
                        codes = m['con_code'].tolist()
                        if ts_code in codes:
                            industry_name = row['name']
                            member_codes = codes
                            break
                except Exception:
                    continue

        if not member_codes:
            # 降级：用申万分类
            df_sw = conn.api.index_classify(level='L1', src='SW2021')
            if df_sw is not None and not df_sw.empty:
                for _, row in df_sw.iterrows():
                    try:
                        m = conn.api.index_member(index_code=row['index_code'])
                        if m is not None and not m.empty:
                            codes = m['con_code'].tolist()
                            if ts_code in codes:
                                industry_name = row['industry_name']
                                member_codes = codes
                                break
                    except Exception:
                        continue

        if not member_codes:
            return format_tool_result(error_result(
                ErrorCodes.DATA_FETCH_ERROR,
                f"无法确定 {stock_code} 所属行业",
                suggestion="请确认股票代码正确"
            ))

        # 2. 批量获取全市场估值数据（1次API调用）
        from app.utils.time_utils import now_utc
        today = now_utc().strftime('%Y%m%d')
        df_basic = None
        for days_back in range(7):
            date_str = (now_utc() - __import__('datetime').timedelta(days=days_back)).strftime('%Y%m%d')
            try:
                df_basic = conn.api.daily_basic(trade_date=date_str,
                                                 fields='ts_code,pe_ttm,pb,ps_ttm,total_mv')
                if df_basic is not None and not df_basic.empty:
                    break
            except Exception:
                continue

        if df_basic is None or df_basic.empty:
            return format_tool_result(error_result(
                ErrorCodes.DATA_FETCH_ERROR, "无法获取市场估值数据"
            ))

        # 3. 过滤行业成分股并计算平均值
        df_basic['ts_code'] = df_basic['ts_code'].str.strip()
        industry_data = df_basic[df_basic['ts_code'].isin(member_codes)].copy()

        if industry_data.empty:
            return format_tool_result(error_result(
                ErrorCodes.DATA_FETCH_ERROR, f"行业 {industry_name} 无估值数据"
            ))

        # 计算行业平均值（排除 NaN）
        avg_pe = industry_data['pe_ttm'].dropna().median()
        avg_pb = industry_data['pb'].dropna().median()
        avg_ps = industry_data['ps_ttm'].dropna().median()
        avg_mv = industry_data['total_mv'].dropna().median() / 10000  # 转为亿

        # 获取个股数据
        stock_data = industry_data[industry_data['ts_code'] == ts_code]
        stock_pe = stock_data['pe_ttm'].values[0] if not stock_data.empty and 'pe_ttm' in stock_data else None
        stock_pb = stock_data['pb'].values[0] if not stock_data.empty and 'pb' in stock_data else None

        stock_name = _get_stock_name(clean_code) or clean_code

        def _fmt(val, ref=None):
            if val is None or val != val:
                return "N/A"
            s = f"{val:.2f}"
            if ref is not None and ref == ref:
                s += " (低估)" if val < ref else " (高估)" if val > ref else " (持平)"
            return s

        result = f"""# {stock_name}({clean_code}) 行业对比分析

## 所属行业: {industry_name}
- 成分股数量: {len(member_codes)} 只
- 有效估值数据: {len(industry_data)} 只

## 行业平均估值（中位数）
| 指标 | 行业中位数 | {stock_name} |
|------|-----------|-------------|
| PE(TTM) | {avg_pe:.2f} | {_fmt(stock_pe, avg_pe)} |
| PB | {avg_pb:.2f} | {_fmt(stock_pb, avg_pb)} |
| PS(TTM) | {avg_ps:.2f} | - |
| 总市值(亿) | {avg_mv:.1f} | - |
"""
        return format_tool_result(success_result(result))

    except Exception as e:
        logger.error(f"get_industry_average failed: {e}")
        return format_tool_result(error_result(
            ErrorCodes.DATA_FETCH_ERROR, str(e)
        ))
