"""
Tushare 新闻 API
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.utils.time_utils import now_utc

from .connection import TushareConnection

logger = logging.getLogger(__name__)

NEWS_SOURCES = [
    "sina", "eastmoney", "10jqka", "wallstreetcn",
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
    """获取股票/市场新闻"""
    if not conn.is_available():
        return None
    try:
        end_time = now_utc()
        start_time = end_time - timedelta(hours=hours_back)
        start_date = start_time.strftime("%Y-%m-%d %H:%M:%S")
        end_date = end_time.strftime("%Y-%m-%d %H:%M:%S")

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
            except Exception:
                continue
            await asyncio.sleep(0.2)

        if not all_news:
            return []

        seen: set = set()
        unique = [n for n in all_news if n["title"] not in seen and not seen.add(n["title"])]
        return sorted(unique, key=lambda x: x.get("publish_time", datetime.min), reverse=True)[:limit]

    except Exception as e:
        logger.error(f"Tushare 获取新闻失败: {e}")
        return None


def _process_news(
    df, source: str, symbol: str = None, limit: int = 10
) -> List[Dict[str, Any]]:
    items = []
    for _, row in df.head(limit * 2).iterrows():
        content = str(row.get("content", ""))
        title = str(row.get("title", "") or content[:50] + "...")
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
    except Exception:
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
    clean = symbol.replace(".SH", "").replace(".SZ", "").zfill(6)
    text = f"{item.get('content', '')} {item.get('title', '')}".lower()
    return clean in text or symbol in text
