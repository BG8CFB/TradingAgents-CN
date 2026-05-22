"""
AKShare 反爬虫与限流工具

复用 app/utils/anti_scraping.py 中的 AntiScrapingSession 和 ThreadSafeRateLimiter。
"""

import logging

logger = logging.getLogger(__name__)

_session = None
_rate_limiter = None


def get_anti_scraping_session():
    """获取反爬虫会话单例"""
    global _session
    if _session is None:
        try:
            from app.utils.anti_scraping import AntiScrapingSession
            _session = AntiScrapingSession()
        except ImportError:
            logger.debug("AntiScrapingSession 不可用，使用标准请求")
    return _session


def get_rate_limiter():
    """获取限流器单例"""
    global _rate_limiter
    if _rate_limiter is None:
        try:
            from app.utils.anti_scraping import ThreadSafeRateLimiter
            _rate_limiter = ThreadSafeRateLimiter(min_interval=0.3, burst=3)
        except ImportError:
            _rate_limiter = None
    return _rate_limiter


def wait_rate_limit():
    """执行限流等待"""
    limiter = get_rate_limiter()
    if limiter:
        limiter.wait()
