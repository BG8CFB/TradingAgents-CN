"""CN 个股新闻直连通道（跨源共享）。

背景：akshare 的个股新闻接口（stock_news_em 等）在当前环境下解析失败
（pyarrow 正则异常）、tushare news 受积分限制，因此个股公告/新闻依赖
以下直连 HTTP 通道。它们是整个 news 域的实际数据来源，被 akshare 与
tushare 两个 Provider 的 news API 共用——收拢在此避免各源重复实现。

通道：
1. 东方财富个股公告 API（np-anotice-stock）
2. 东方财富搜索 API（search-api-web，jsonp）
3. 新浪财经滚动搜索（feed.mix.sina）
"""

import asyncio
import json
import logging
import re
import time
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


async def fetch_em_notices(symbol: str, limit: int = 10) -> List[Dict[str, Any]]:
    """东方财富个股公告（精确匹配 symbol，含公告+新闻）"""
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


async def fetch_em_search(
    stock_name: str, symbol: str, limit: int = 10
) -> List[Dict[str, Any]]:
    """东方财富搜索（按股票名称搜索相关新闻）"""
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
                content = art.get("content", "").replace("　", " ").replace("\r\n", " ")
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


async def fetch_sina_news(
    stock_name: str, symbol: str, limit: int = 10
) -> List[Dict[str, Any]]:
    """新浪财经滚动搜索（兜底通道）"""
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
