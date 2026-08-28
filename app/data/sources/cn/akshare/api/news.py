"""
AKShare 新闻 API（个股定向获取）

策略链（按优先级）：
1. 东方财富个股公告 → 精确匹配 symbol
2. 东方财富搜索（按股票名称）→ 相关新闻
3. 新浪财经搜索（按股票名称）→ 兜底
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

from app.data.sources.base.exceptions import DataNotFoundError

from app.data.sources.cn.stock_name_utils import get_stock_name, get_stock_name_sync
# 直连通道实现收拢在 cn/shared，本模块只做策略编排
from app.data.sources.cn.shared.news_channels import (
    fetch_em_notices as _fetch_em_notices,
    fetch_em_search as _fetch_em_search,
    fetch_sina_news as _fetch_sina_news,
)

logger = logging.getLogger(__name__)

_DOMAIN = "news"


def _get_stock_name_sync(symbol: str) -> Optional[str]:
    """兼容层 — 委托给共享工具函数。"""
    return get_stock_name_sync(symbol)


async def _get_stock_name(symbol: str) -> Optional[str]:
    """异步获取股票名称 — 使用 async 版本，避免在事件循环线程中
    通过 to_thread 调用 get_stock_name_sync 触发 run_async 嵌套死锁（R13-DS-03）。"""
    return await get_stock_name(symbol)


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

    logger.debug(f"AKShare 个股新闻 ({symbol}): 共 {len(all_news)} 条")
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

    logger.debug(f"AKShare 市场级新闻: 共 {len(results)} 条")
    return results


