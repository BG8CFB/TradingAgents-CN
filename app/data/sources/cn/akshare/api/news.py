"""
AKShare 新闻 API（个股定向获取）

策略链（按优先级）：
1. 东方财富个股公告 → 精确匹配 symbol
2. 东方财富搜索（按股票名称）→ 相关新闻
3. 新浪财经搜索（按股票名称）→ 兜底
"""
import asyncio
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from app.data.sources.base.exceptions import DataNotFoundError

from app.data.sources.cn.stock_name_utils import get_stock_name_sync

logger = logging.getLogger(__name__)

_DOMAIN = "news"


def _get_stock_name_sync(symbol: str) -> Optional[str]:
    """兼容层 — 委托给共享工具函数。"""
    return get_stock_name_sync(symbol)


async def _get_stock_name(symbol: str) -> Optional[str]:
    """异步获取股票名称"""
    return await asyncio.to_thread(_get_stock_name_sync, symbol)


async def fetch_news(
    symbol: str = None, limit: int = 10
) -> List[Dict[str, Any]]:
    """获取个股新闻（优先获取与指定股票直接相关的新闻和公告）

    策略链:
    1. 东方财富个股公告（精确匹配 symbol）
    2. 东方财富搜索（按股票名称搜索相关新闻）
    3. 新浪财经搜索（兜底）

    Raises:
        DataNotFoundError: 所有策略均无数据，或 symbol 为空（不可重试）
    """
    if not symbol:
        # 市场级新闻（symbol=None）：抓全市场财经快讯，不依赖逐 symbol
        return await fetch_market_news(limit=limit)

    all_news: List[Dict[str, Any]] = []
    seen_titles: set = set()

    # 策略 1: 个股公告
    notices = await _fetch_em_notices(symbol, limit=limit)
    for item in notices:
        if item["title"] not in seen_titles:
            seen_titles.add(item["title"])
            all_news.append(item)

    # 策略 2: 按名称搜索新闻
    stock_name = await _get_stock_name(symbol)
    if stock_name:
        news = await _fetch_em_search(stock_name, symbol, limit=limit)
        for item in news:
            if item["title"] not in seen_titles:
                seen_titles.add(item["title"])
                all_news.append(item)

    # 策略 3: 新浪兜底
    if len(all_news) < limit and stock_name:
        sina_news = await _fetch_sina_news(stock_name, symbol, limit=limit)
        for item in sina_news:
            if item["title"] not in seen_titles:
                seen_titles.add(item["title"])
                all_news.append(item)

    if not all_news:
        # 所有策略链均无结果 → 业务空数据
        logger.warning(f"AKShare 个股新闻: symbol={symbol} 所有策略链均无结果")
        raise DataNotFoundError("akshare", _DOMAIN, f"symbol={symbol} 无相关新闻")

    logger.info(f"AKShare 个股新闻 ({symbol}): 共 {len(all_news)} 条")
    return all_news


async def fetch_market_news(limit: int = 100) -> List[Dict[str, Any]]:
    """获取全市场财经快讯（市场级新闻，不依赖逐 symbol）。

    数据源：东方财富全球财经直播 stock_info_global_em，返回 A 股/港股/美股
    全球财经快讯，字段为中文列名（标题/摘要/发布时间/链接），由 adapter 统一映射。

    Raises:
        DataNotFoundError: 所有策略均无数据
    """
    import akshare as ak

    def _fetch_global() -> List[Dict[str, Any]]:
        try:
            df = ak.stock_info_global_em()
            if df is None or df.empty:
                return []
            items = []
            for _, row in df.head(limit).iterrows():
                title = str(row.get("标题", "")).strip()
                if not title:
                    continue
                items.append({
                    "title": title,
                    "content": str(row.get("摘要", "") or title),
                    "publish_time": str(row.get("发布时间", "") or ""),
                    "url": str(row.get("链接", "") or ""),
                    "source": "东方财富",
                    "category": "market_news",
                    "data_source": "akshare",
                    "original_source": "stock_info_global_em",
                })
            return items
        except Exception as e:
            logger.debug(f"stock_info_global_em 获取失败: {e}")
            return []

    results = await asyncio.to_thread(_fetch_global)

    if not results:
        logger.warning("AKShare 市场级新闻: 无数据")
        raise DataNotFoundError("akshare", _DOMAIN, "市场级新闻无数据")

    logger.info(f"AKShare 市场级新闻: 共 {len(results)} 条")
    return results


async def _fetch_em_notices(symbol: str, limit: int = 10) -> List[Dict[str, Any]]:
    """策略 1: 东方财富个股公告（精确匹配 symbol，含公告+新闻）"""
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
                    "data_source": "em_notice",
                    "type": "announcement",
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


async def _fetch_em_search(
    stock_name: str, symbol: str, limit: int = 10
) -> List[Dict[str, Any]]:
    """策略 2: 东方财富搜索（按股票名称搜索相关新闻）"""
    import requests as req

    def _fetch():
        url = "https://search-api-web.eastmoney.com/search/jsonp"
        ts_ms = int(time.time() * 1000)
        cb = f"jQuery{ts_ms}"
        param = json.dumps({
            "uid": "",
            "keyword": stock_name,
            "type": ["cmsArticleWebOld"],
            "client": "web",
            "clientType": "web",
            "clientVersion": "curr",
            "param": {
                "cmsArticleWebOld": {
                    "searchScope": "default",
                    "sort": "default",
                    "pageIndex": 1,
                    "pageSize": limit,
                    "preTag": "",
                    "postTag": "",
                }
            },
        }, ensure_ascii=False)
        params = {"cb": cb, "param": param, "_": str(ts_ms)}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136.0.0.0 Safari/537.36",
            "Referer": f"https://so.eastmoney.com/news/s?keyword={stock_name}",
        }
        try:
            resp = req.get(url, params=params, headers=headers, timeout=15)
            text = resp.text
            match = re.search(r"\((.+)\);?$", text, re.DOTALL)
            if not match:
                return []
            data = json.loads(match.group(1))
            articles = data.get("result", {}).get("cmsArticleWebOld", {}).get("list", [])
            results = []
            for art in articles:
                title = art.get("title", "").replace("<em>", "").replace("</em>", "")
                content = art.get("content", "").replace("\u3000", " ").replace("\r\n", " ")
                # 相关性过滤: 标题或内容包含股票名称
                full_text = f"{title} {content}"
                if stock_name not in full_text and symbol not in full_text:
                    continue
                results.append({
                    "title": title,
                    "content": content,
                    "summary": content[:200] if len(content) > 200 else content,
                    "url": art.get("url", ""),
                    "source": art.get("mediaName", "东方财富"),
                    "publish_time": art.get("date", ""),
                    "data_source": "em_search",
                    "type": "news",
                    "symbol": symbol,
                })
            return results
        except Exception as e:
            logger.debug(f"东方财富搜索失败: {e}")
            return []

    results = await asyncio.to_thread(_fetch)
    if results:
        logger.info(f"  东方财富搜索 ({stock_name}): {len(results)} 条")
    return results


async def _fetch_sina_news(
    stock_name: str, symbol: str, limit: int = 10
) -> List[Dict[str, Any]]:
    """策略 3: 新浪财经搜索（兜底）"""
    import requests as req

    def _fetch():
        url = "https://feed.mix.sina.com.cn/api/roll/get"
        params = {
            "pageid": "153",
            "lid": "2516",
            "k": stock_name,
            "num": str(limit),
            "page": "1",
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136.0.0.0 Safari/537.36",
        }
        try:
            resp = req.get(url, params=params, headers=headers, timeout=15)
            if resp.status_code != 200:
                return []
            data = resp.json()
            items = data.get("result", {}).get("data", [])
            results = []
            for item in items:
                title = str(item.get("title", ""))
                intro = str(item.get("intro", ""))
                full_text = f"{title} {intro}"
                # 相关性过滤
                if stock_name not in full_text and symbol not in full_text:
                    continue
                ctime = item.get("ctime", "")
                publish_time = ""
                if ctime:
                    try:
                        from datetime import datetime
                        dt = datetime.fromtimestamp(int(ctime))
                        publish_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                    except (ValueError, TypeError, OSError):
                        pass
                results.append({
                    "title": title,
                    "content": intro or title,
                    "summary": intro[:200] if intro else title,
                    "url": str(item.get("url", "")),
                    "source": str(item.get("media_name", "新浪财经")),
                    "publish_time": publish_time,
                    "data_source": "sina",
                    "type": "news",
                    "symbol": symbol,
                })
            return results
        except Exception as e:
            logger.debug(f"新浪搜索失败: {e}")
            return []

    results = await asyncio.to_thread(_fetch)
    if results:
        logger.info(f"  新浪搜索 ({stock_name}): {len(results)} 条")
    return results
