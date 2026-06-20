"""
Tushare 新闻 API

多策略获取：news 快讯 → major_news 长篇通讯 → cctv_news 新闻联播
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.data.sources.base.exceptions import DataSourceUnavailableError
from app.data.sources.base.mappers import map_network_exception, map_tushare_code
from app.utils.time_utils import now_utc

from .connection import TushareConnection

logger = logging.getLogger(__name__)

_DOMAIN = "news"

NEWS_SOURCES = [
    "eastmoney", "sina", "10jqka", "wallstreetcn",
    "cls", "yicai", "jinrongjie", "yuncaijing", "fenghuang",
]

SOURCE_NAMES = {
    "sina": "新浪财经", "eastmoney": "东方财富", "10jqka": "同花顺",
    "wallstreetcn": "华尔街见闻", "cls": "财联社", "yicai": "第一财经",
    "jinrongjie": "金融界", "yuncaijing": "云财经", "fenghuang": "凤凰新闻",
}


async def fetch_news(
    conn: TushareConnection,
    symbol: str = None,
    limit: int = 10,
    hours_back: int = 24,
    src: str = None,
) -> Optional[List[Dict[str, Any]]]:
    """获取股票/市场新闻（多策略回退）

    策略链：
    0. 个股公告/定向新闻（东方财富公告 API，按 symbol 精确匹配）
    1. news 快讯（全市场，支持按 symbol 文本匹配）
    2. major_news 长篇通讯（带标题和 URL，质量更高）
    3. cctv_news 新闻联播（权威来源兜底）
    """
    if not conn.is_available():
        return None
    try:
        end_time = now_utc()
        start_time = end_time - timedelta(hours=hours_back)
        start_date = start_time.strftime("%Y-%m-%d %H:%M:%S")
        end_date = end_time.strftime("%Y-%m-%d %H:%M:%S")

        all_news: List[Dict[str, Any]] = []
        seen_titles: set = set()

        # 策略 0: 个股定向获取（东方财富公告 + 名称搜索）
        if symbol:
            targeted = await _fetch_targeted_news(symbol, limit)
            for item in targeted:
                if item["title"] not in seen_titles:
                    seen_titles.add(item["title"])
                    all_news.append(item)

            if len(all_news) >= limit:
                return _deduplicate_and_sort(all_news, limit)

        # 策略 1: news 快讯
        fast_news = await _fetch_news_fast(conn, symbol, start_date, end_date, src, limit)
        for item in fast_news:
            if item["title"] not in seen_titles:
                seen_titles.add(item["title"])
                all_news.append(item)

        if len(all_news) >= limit:
            return _deduplicate_and_sort(all_news, limit)

        # 策略 2: major_news 长篇通讯
        major_items = await _fetch_major_news(conn, start_date, end_date, limit)
        if major_items:
            for item in major_items:
                if item["title"] not in seen_titles:
                    seen_titles.add(item["title"])
                    all_news.append(item)

        if len(all_news) >= limit:
            return _deduplicate_and_sort(all_news, limit)

        # 策略 3: cctv_news 新闻联播
        cctv_items = await _fetch_cctv_news(conn, limit)
        if cctv_items:
            for item in cctv_items:
                if item["title"] not in seen_titles:
                    seen_titles.add(item["title"])
                    all_news.append(item)

        if not all_news:
            return []

        return _deduplicate_and_sort(all_news, limit)

    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        # 编排逻辑中触发的网络异常：透传给上层 retry_policy
        raise map_network_exception(exc, "tushare", _DOMAIN)
    except Exception as exc:
        # 致命业务异常（鉴权/积分等）：透传给上层
        error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
        mapped = map_tushare_code(error_code, "tushare", _DOMAIN, str(exc))
        if mapped is not None:
            raise mapped
        # 子策略函数已有自己的 try/except，到这里通常意味着编排逻辑本身出错
        raise DataSourceUnavailableError("tushare", _DOMAIN, str(exc))


async def _fetch_targeted_news(
    symbol: str, limit: int = 10
) -> List[Dict[str, Any]]:
    """策略 0: 个股定向新闻（东方财富公告 API）"""
    import requests as req

    def _fetch():
        url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
        params = {
            "sr": "-1",
            "page_size": str(min(limit, 20)),
            "page_index": "1",
            "ann_type": "A",
            "client_source": "web",
            "f_node": "0",
            "s_node": "0",
            "stock_list": symbol,
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136.0.0.0 Safari/537.36",
            "Referer": "https://data.eastmoney.com/notices/stock.html",
        }
        try:
            resp = req.get(url, params=params, headers=headers, timeout=15)
            data = resp.json()
            notices = data.get("data", {}).get("list", [])
            results = []
            for notice in notices:
                art_code = notice.get("art_code", "")
                title = notice.get("title", "")
                results.append({
                    "title": title,
                    "content": title,
                    "summary": title[:200],
                    "url": f"https://data.eastmoney.com/notices/detail/{symbol}/{art_code}.html",
                    "source": "东方财富公告",
                    "publish_time": notice.get("notice_date", ""),
                    "category": "company_announcement",
                    "sentiment": "neutral",
                    "importance": "high",
                    "keywords": [],
                    "data_source": "tushare",
                    "original_source": "em_notice",
                    "symbol": symbol,
                })
            return results
        except Exception as e:
            logger.debug(f"东方财富公告获取失败: {e}")
            return []

    results = await asyncio.to_thread(_fetch)
    if results:
        logger.info(f"  个股公告 ({symbol}): {len(results)} 条")
    return results


async def _fetch_news_fast(
    conn: TushareConnection, symbol: str,
    start_date: str, end_date: str, src: str, limit: int,
) -> List[Dict[str, Any]]:
    """策略 1: 快讯接口（eastmoney 源有 title）"""
    sources = [src] if src and src in NEWS_SOURCES else NEWS_SOURCES[:3]
    all_news: List[Dict[str, Any]] = []

    for source in sources:
        try:
            df = await asyncio.to_thread(
                conn.api.news, src=source, start_date=start_date, end_date=end_date
            )
            if df is not None and not df.empty:
                items = _process_news(df, source, symbol, limit)
                all_news.extend(items)
                if len(all_news) >= limit:
                    break
        except Exception as e:
            logger.debug(f"获取新闻数据失败: {e}")
            continue
        await asyncio.sleep(0.2)

    return all_news


async def _fetch_major_news(
    conn: TushareConnection, start_date: str, end_date: str, limit: int,
) -> List[Dict[str, Any]]:
    """策略 2: 长篇通讯（带 title/url，质量更高）"""
    try:
        df = await asyncio.to_thread(
            conn.api.major_news, start_date=start_date, end_date=end_date
        )
        if df is None or df.empty:
            return []

        items = []
        for _, row in df.head(limit).iterrows():
            title = str(row.get("title", ""))
            if not title:
                continue
            pub_time = _parse_time(row.get("pub_time", ""))
            items.append({
                "title": title,
                "content": title,
                "summary": title,
                "url": str(row.get("url", "")),
                "source": str(row.get("src", "tushare_major")),
                "publish_time": pub_time,
                "category": "major_news",
                "sentiment": "neutral",
                "importance": "high",
                "keywords": [],
                "data_source": "tushare",
                "original_source": "major_news",
            })
        return items
    except Exception as e:
        logger.debug(f"Tushare major_news 失败（可能积分不足）: {e}")
        return []


async def _fetch_cctv_news(
    conn: TushareConnection, limit: int,
) -> List[Dict[str, Any]]:
    """策略 3: 新闻联播（权威来源）"""
    try:
        today = now_utc().strftime("%Y%m%d")
        df = await asyncio.to_thread(conn.api.cctv_news, date=today)
        if df is None or df.empty:
            return []

        items = []
        for _, row in df.head(limit).iterrows():
            title = str(row.get("title", ""))
            if not title:
                continue
            items.append({
                "title": title,
                "content": str(row.get("content", "")),
                "summary": str(row.get("content", ""))[:200],
                "url": "",
                "source": "央视新闻联播",
                "publish_time": _parse_time(row.get("date", "")),
                "category": "cctv_news",
                "sentiment": "neutral",
                "importance": "high",
                "keywords": [],
                "data_source": "tushare",
                "original_source": "cctv_news",
            })
        return items
    except Exception as e:
        logger.debug(f"Tushare cctv_news 失败: {e}")
        return []


def _deduplicate_and_sort(
    news_list: List[Dict[str, Any]], limit: int
) -> List[Dict[str, Any]]:
    """去重并排序：个股相关的在前（按时间倒序），全市场的在后"""
    seen: set = set()
    unique = [n for n in news_list if n["title"] not in seen and not seen.add(n["title"])]

    def _sort_key(item):
        pt = item.get("publish_time", "")
        if isinstance(pt, datetime):
            time_val = pt
        elif isinstance(pt, str) and pt:
            try:
                time_val = datetime.strptime(pt, "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                try:
                    time_val = datetime.strptime(pt, "%Y-%m-%d")
                except (ValueError, TypeError):
                    time_val = datetime.min
        else:
            time_val = datetime.min
        # 个股定向的排在前面（0），全市场的排在后面（1）
        is_targeted = 0 if item.get("original_source") in ("em_notice", "em_search", "sina") else 1
        return (is_targeted, -time_val.timestamp())

    return sorted(unique, key=_sort_key)[:limit]


def _process_news(
    df, source: str, symbol: str = None, limit: int = 10
) -> List[Dict[str, Any]]:
    items = []
    for _, row in df.head(limit * 2).iterrows():
        content = str(row.get("content", ""))
        raw_title = row.get("title", "")
        # eastmoney 源有 title，sina 等源 title 为 None
        title = str(raw_title) if raw_title else content[:50].rstrip("。") + "..."
        item = {
            "title": title,
            "content": content,
            "summary": content[:200] + "..." if len(content) > 200 else content,
            "url": "",
            "source": SOURCE_NAMES.get(source, source),
            "publish_time": _parse_time(row.get("datetime", "")),
            "category": _classify(row.get("channels", ""), content),
            "sentiment": _sentiment(content, title),
            "importance": _importance(content, title),
            "keywords": _keywords(content, title),
            "data_source": "tushare",
            "original_source": source,
        }
        if not symbol or _is_relevant(item, symbol):
            items.append(item)
    return items


def _parse_time(time_str) -> Optional[datetime]:
    if not time_str:
        return now_utc()
    try:
        return datetime.strptime(str(time_str), "%Y-%m-%d %H:%M:%S")
    except Exception as e:
        logger.debug(f"解析日期格式失败: {e}")
        # 尝试纯日期格式（cctv_news 返回 YYYYMMDD）
        try:
            return datetime.strptime(str(time_str), "%Y%m%d")
        except Exception as e:
            return now_utc()


def _classify(channels: str, content: str) -> str:
    text = f"{channels} {content}".lower()
    for kw, cat in [("公告|业绩|财报", "company_announcement"), ("政策|监管|央行", "policy_news"),
                     ("行业|板块", "industry_news"), ("市场|指数|大盘", "market_news")]:
        if any(k in text for k in kw.split("|")):
            return cat
    return "other"


def _sentiment(content: str, title: str) -> str:
    text = f"{title} {content}"
    pos = sum(1 for k in ["利好", "上涨", "增长", "盈利", "突破"] if k in text)
    neg = sum(1 for k in ["利空", "下跌", "亏损", "风险", "暴跌"] if k in text)
    return "positive" if pos > neg else ("negative" if neg > pos else "neutral")


def _importance(content: str, title: str) -> str:
    text = f"{title} {content}"
    if any(k in text for k in ["业绩", "财报", "重大", "公告", "监管", "并购"]):
        return "high"
    if any(k in text for k in ["分析", "预测", "行业", "市场"]):
        return "medium"
    return "low"


def _keywords(content: str, title: str) -> List[str]:
    text = f"{title} {content}"
    pool = ["股票", "公司", "市场", "投资", "业绩", "财报", "政策", "行业", "分析", "预测"]
    return [k for k in pool if k in text][:5]


def _is_relevant(item: Dict, symbol: str) -> bool:
    clean = symbol.replace(".SH", "").replace(".SZ", "").replace(".BJ", "").zfill(6)
    text = f"{item.get('content', '')} {item.get('title', '')}"
    if clean in text or symbol in text:
        return True
    # 尝试用股票名称匹配
    try:
        from app.data.sources.cn.stock_name_utils import get_stock_name_sync
        name = get_stock_name_sync(clean)
        if name and name in text:
            return True
    except Exception as e:
        logger.debug(f"检查股票名称匹配失败: {e}")
        pass
    return False
