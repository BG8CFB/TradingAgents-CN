"""
AKShare 新闻 API（EM 搜索 + ak.stock_news_em 回退）
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


async def fetch_news(
    symbol: str = None, limit: int = 10
) -> Optional[List[Dict[str, Any]]]:
    """获取股票新闻（两级回退：EM 直接 → ak API）"""
    for strategy_name, strategy_fn in [
        ("em_direct", _fetch_em_news),
        ("ak_api", _fetch_ak_news),
    ]:
        try:
            result = await strategy_fn(symbol, limit)
            if result:
                return result
        except Exception as e:
            logger.debug(f"AKShare 新闻 {strategy_name} 失败: {e}")
            continue

    return None


async def _fetch_em_news(symbol: str, limit: int) -> Optional[List[Dict[str, Any]]]:
    """策略 1: 东方财富搜索 API（绕过 akshare，直接 HTTP）"""
    try:
        from app.utils.anti_scraping import AntiScrapingSession
        session = AntiScrapingSession()
        # 尝试通过 curl_cffi 直接请求
        items = await asyncio.to_thread(session.fetch_news_em, symbol, limit)
        return items
    except (ImportError, AttributeError, Exception):
        return None


async def _fetch_ak_news(symbol: str, limit: int) -> Optional[List[Dict[str, Any]]]:
    """策略 2: AKShare API"""
    try:
        import akshare as ak

        def _fetch():
            if symbol:
                return ak.stock_news_em(symbol=symbol)
            return ak.news_cctv(date=None)

        df = await asyncio.to_thread(_fetch)
        if df is None or df.empty:
            return None

        items = []
        for _, row in df.head(limit).iterrows():
            items.append({
                "title": str(row.get("新闻标题", row.get("title", ""))),
                "content": str(row.get("新闻内容", row.get("content", ""))),
                "source": str(row.get("来源", row.get("source", "akshare"))),
                "url": str(row.get("新闻链接", row.get("url", ""))),
                "publish_time": str(row.get("发布时间", row.get("datetime", ""))),
                "data_source": "akshare",
            })
        return items
    except Exception:
        return None
