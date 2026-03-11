"""
News Data Tools Logic
"""
import asyncio
import json
import logging
from app.data.manager import DataSourceManager

logger = logging.getLogger(__name__)

async def get_finance_news_logic(manager: DataSourceManager, code: str, days: int, limit: int) -> str:
    """
    Logic for get_finance_news tool.
    """
    try:
        items, source = await asyncio.to_thread(
            manager.get_news_with_fallback,
            code=code,
            days=days,
            limit=limit,
            include_announcements=True
        )
        
        if not items:
            return json.dumps({
                "status": "warning",
                "message": f"No news found for {code} in last {days} days."
            }, ensure_ascii=False)
            
        return json.dumps({
            "code": code,
            "source": source,
            "count": len(items),
            "news": items
        }, ensure_ascii=False, default=str)

    except Exception as e:
        logger.error(f"Error in get_finance_news_logic: {e}")
        return json.dumps({
            "status": "error",
            "message": str(e)
        }, ensure_ascii=False)
