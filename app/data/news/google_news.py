import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import time
import random
import os
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    retry_if_result,
)

from app.engine.config.runtime_settings import get_float
# 导入日志模块
from app.utils.logging_manager import get_logger
logger = get_logger('agents')

SLEEP_MIN = get_float("TA_GOOGLE_NEWS_SLEEP_MIN_SECONDS", "ta_google_news_sleep_min_seconds", 2.0)
SLEEP_MAX = get_float("TA_GOOGLE_NEWS_SLEEP_MAX_SECONDS", "ta_google_news_sleep_max_seconds", 6.0)


def is_rate_limited(response):
    """Check if the response indicates rate limiting (status code 429)"""
    return response.status_code == 429


# 全局变量缓存连接状态
_GOOGLE_CONNECTABLE = None
_LAST_CHECK_TIME = 0
_CHECK_INTERVAL = 300  # 5分钟检查一次

def check_google_connectivity():
    """快速检查能否连接到Google"""
    global _GOOGLE_CONNECTABLE, _LAST_CHECK_TIME
    
    # 如果已有缓存且未过期，直接返回缓存结果
    now = time.time()
    if _GOOGLE_CONNECTABLE is not None and (now - _LAST_CHECK_TIME < _CHECK_INTERVAL):
        return _GOOGLE_CONNECTABLE
        
    try:
        # 尝试连接Google主页，超时设为3秒
        logger.info("正在检查Google连通性...")
        requests.get("https://www.google.com", timeout=3)
        _GOOGLE_CONNECTABLE = True
        _LAST_CHECK_TIME = now
        logger.info("Google连通性检查通过")
        return True
    except Exception:
        _GOOGLE_CONNECTABLE = False
        _LAST_CHECK_TIME = now
        logger.warning("Google连通性检查失败，将跳过Google新闻源")
        return False

@retry(
    retry=(retry_if_result(is_rate_limited) | retry_if_exception_type(requests.exceptions.ConnectionError) | retry_if_exception_type(requests.exceptions.Timeout)),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_attempt(2),
)
def make_request(url, headers):
    """Make a request with retry logic for rate limiting and connection issues"""
    # 检查网络连通性
    if not check_google_connectivity():
        raise requests.exceptions.ConnectionError("Google不可访问")

    # Random delay before each request to avoid detection
    time.sleep(random.uniform(SLEEP_MIN, SLEEP_MAX))
    # 添加超时参数，设置连接超时和读取超时
    # 缩短超时时间以避免长时间阻塞
    response = requests.get(url, headers=headers, timeout=(5, 10))  # 连接超时5秒，读取超时10秒
    return response


def getNewsData(query, start_date, end_date):
    """
    Scrape Google News search results for a given query and date range.
    query: str - search query
    start_date: str - start date in the format yyyy-mm-dd or mm/dd/yyyy
    end_date: str - end date in the format yyyy-mm-dd or mm/dd/yyyy
    """
    if "-" in start_date:
        start_date = datetime.strptime(start_date, "%Y-%m-%d")
        start_date = start_date.strftime("%m/%d/%Y")
    if "-" in end_date:
        end_date = datetime.strptime(end_date, "%Y-%m-%d")
        end_date = end_date.strftime("%m/%d/%Y")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/101.0.4951.54 Safari/537.36"
        )
    }

    news_results = []
    page = 0
    while True:
        offset = page * 10
        url = (
            f"https://www.google.com/search?q={query}"
            f"&tbs=cdr:1,cd_min:{start_date},cd_max:{end_date}"
            f"&tbm=nws&start={offset}"
        )

        try:
            response = make_request(url, headers)
            soup = BeautifulSoup(response.content, "html.parser")
            results_on_page = soup.select("div.SoaBEf")

            if not results_on_page:
                break  # No more results found

            for el in results_on_page:
                try:
                    link = el.find("a")["href"]
                    title = el.select_one("div.MBeuO").get_text()
                    snippet = el.select_one(".GI74Re").get_text()
                    date = el.select_one(".LfVVr").get_text()
                    source = el.select_one(".NUnG9d span").get_text()
                    news_results.append(
                        {
                            "link": link,
                            "title": title,
                            "snippet": snippet,
                            "date": date,
                            "source": source,
                        }
                    )
                except Exception as e:
                    logger.error(f"Error processing result: {e}")
                    # If one of the fields is not found, skip this result
                    continue

            # Update the progress bar with the current count of results scraped

            # Check for the "Next" link (pagination)
            next_link = soup.find("a", id="pnnext")
            if not next_link:
                break

            page += 1

        except requests.exceptions.Timeout as e:
            logger.error(f"连接超时: {e}")
            # 不立即中断，记录错误后继续尝试下一页
            page += 1
            if page > 3:  # 如果连续多页都超时，则退出循环
                logger.error("多次连接超时，停止获取Google新闻")
                break
            continue
        except requests.exceptions.ConnectionError as e:
            logger.error(f"连接错误: {e}")
            # 不立即中断，记录错误后继续尝试下一页
            page += 1
            if page > 3:  # 如果连续多页都连接错误，则退出循环
                logger.error("多次连接错误，停止获取Google新闻")
                break
            continue
        except Exception as e:
            logger.error(f"获取Google新闻失败: {e}")
            break

    return news_results
