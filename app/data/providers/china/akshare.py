"""
AKShare统一数据提供器
基于AKShare SDK的统一数据同步方案，提供标准化的数据接口
"""
import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Union
import pandas as pd

from app.engine.config.runtime_settings import get_int
from app.utils.stock_utils import StockUtils, StockMarket
from app.utils.time_utils import now_utc, now_config_tz, format_iso
from app.utils.anti_scraping import (
    AntiScrapingSession,
    ThreadSafeRateLimiter,
    get_random_ua,
    EASTMONEY_HEADERS,
    fetch_em_spot_direct,
    fetch_em_hist_direct,
    fetch_em_bid_ask_direct,
    fetch_tencent_spot_batch,
)
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from ..base_provider import BaseStockDataProvider

logger = logging.getLogger(__name__)


class AKShareProvider(BaseStockDataProvider):
    """
    AKShare统一数据提供器
    
    提供标准化的股票数据接口，支持：
    - 股票基础信息获取
    - 历史行情数据
    - 实时行情数据
    - 财务数据
    - 港股数据支持
    """
    
    def __init__(self):
        super().__init__("AKShare")
        self.ak = None
        self.connected = False
        self._stock_list_cache = None  # 缓存股票列表，避免重复获取
        self._cache_time = None  # 缓存时间
        self._initialize_akshare()
    
    def _initialize_akshare(self):
        """初始化 AKShare 连接，配置反爬虫策略"""
        try:
            # Patch pandas read_excel（在导入 akshare 之前）
            self._patch_pandas_read_excel()

            import akshare as ak
            import requests

            # 初始化反爬虫会话（curl_cffi + 现代指纹）
            self._anti_session = AntiScrapingSession()
            self._rate_limiter = ThreadSafeRateLimiter(min_interval=0.3, burst=3)
            self._default_timeout = get_int("TA_AKSHARE_TIMEOUT", "ta_akshare_timeout", 30)

            if self._anti_session.is_curl_available:
                logger.info(f"反爬虫: curl_cffi 已就绪，指纹 {self._anti_session.impersonate_target}")
            else:
                logger.warning("反爬虫: curl_cffi 不可用，回退到标准 requests（建议安装 curl-cffi>=0.6.0）")

            # Patch requests.get：为所有经 AKShare 发出的请求添加反爬虫增强
            if not hasattr(requests, '_akshare_headers_patched'):
                original_get = requests.get
                rate_limiter = self._rate_limiter
                default_timeout = self._default_timeout
                anti_session = self._anti_session

                # 东方财富 CDN 封锁了 push2 域名，自动替换为可用域名
                # 注意: push2his (历史K线) 无可用替代域名，不重写
                _EM_DOMAIN_REWRITE = {
                    ".push2.eastmoney.com": ".push2delay.eastmoney.com",
                    "push2.eastmoney.com": "push2delay.eastmoney.com",
                }

                def _rewrite_em_url(url: str) -> str:
                    for old, new in _EM_DOMAIN_REWRITE.items():
                        if old in url:
                            url = url.replace(old, new)
                            break
                    return url

                def _rewrite_headers(kwargs):
                    hdrs = kwargs.get('headers') or {}
                    if isinstance(hdrs, dict) and 'Host' in hdrs:
                        for old, new in _EM_DOMAIN_REWRITE.items():
                            if old in hdrs['Host']:
                                hdrs['Host'] = hdrs['Host'].replace(old, new)
                                break
                        kwargs['headers'] = hdrs

                def patched_get(url, **kwargs):
                    url = _rewrite_em_url(url)
                    _rewrite_headers(kwargs)

                    headers = kwargs.get('headers', {}) or {}
                    headers.setdefault('User-Agent', get_random_ua())
                    headers.setdefault('Accept', '*/*')
                    headers.setdefault('Accept-Language', 'zh-CN,zh;q=0.9,en;q=0.8')
                    headers.setdefault('Accept-Encoding', 'gzip, deflate, br')
                    headers.setdefault('Connection', 'keep-alive')
                    headers.setdefault('Sec-Fetch-Dest', 'empty')
                    headers.setdefault('Sec-Fetch-Mode', 'cors')
                    headers.setdefault('Sec-Fetch-Site', 'same-site')
                    headers.setdefault('Sec-Ch-Ua', '"Chromium";v="136", "Google Chrome";v="136", "Not-A.Brand";v="99"')
                    headers.setdefault('Sec-Ch-Ua-Mobile', '?0')
                    headers.setdefault('Sec-Ch-Ua-Platform', '"Windows"')

                    if 'Referer' not in headers:
                        if 'eastmoney.com' in url:
                            headers['Referer'] = 'https://data.eastmoney.com/'
                        else:
                            headers['Referer'] = 'https://eastmoney.com/'

                    kwargs['headers'] = headers
                    if 'timeout' not in kwargs:
                        kwargs['timeout'] = default_timeout

                    rate_limiter.acquire()

                    if anti_session.is_curl_available:
                        try:
                            curl_kwargs = kwargs.copy()
                            curl_kwargs.pop('proxies', None)
                            return anti_session._curl_session.get(url, **curl_kwargs)
                        except Exception as e:
                            logger.debug(f"curl_cffi 请求失败，回退: {e}")

                    return original_get(url, **kwargs)

                requests.get = patched_get

                # 同时 patch requests.Session.get（AKShare request_with_retry 使用 session 方式调用）
                original_session_get = requests.Session.get

                def patched_session_get(self_session, url, **kwargs):
                    url = _rewrite_em_url(url)
                    _rewrite_headers(kwargs)
                    return original_session_get(self_session, url, **kwargs)

                requests.Session.get = patched_session_get

                requests._akshare_headers_patched = True
                logger.info("已应用 requests 全局补丁 (Headers/Timeout/RateLimit/TLS指纹/域名重写push2→push2delay)")

            self.ak = ak
            self.connected = True
            self._configure_timeout()
            logger.info("AKShare 初始化成功")
        except ImportError as e:
            logger.error(f"AKShare 未安装: {e}")
            self.connected = False
        except Exception as e:
            logger.error(f"AKShare 初始化失败: {e}")
            self.connected = False

    @staticmethod
    def _patch_pandas_read_excel():
        import pandas as pd
        if hasattr(pd, '_read_excel_patched'):
            return
        original = pd.read_excel

        def patched(io, **kwargs):
            if 'engine' not in kwargs:
                try:
                    return original(io, engine='openpyxl', **kwargs)
                except Exception:
                    try:
                        return original(io, engine='xlrd', **kwargs)
                    except Exception:
                        pass
            return original(io, **kwargs)

        pd.read_excel = patched
        pd._read_excel_patched = True
        logger.info("已应用 pandas.read_excel 补丁")

    def _get_stock_news_direct(self, symbol: str, limit: int = 10) -> Optional[pd.DataFrame]:
        """
        直接调用东方财富网新闻 API（绕过 AKShare）
        优先使用 curl_cffi 模拟真实浏览器，如果失败则回退到 requests

        Args:
            symbol: 股票代码
            limit: 返回数量限制

        Returns:
            新闻 DataFrame 或 None
        """
        import json
        import time
        
        # 标准化股票代码
        symbol_6 = symbol.zfill(6)
        
        # 获取超时配置
        request_timeout = get_int("TA_AKSHARE_TIMEOUT", "ta_akshare_timeout", 30)

        # 构建请求参数
        # 🔥 关键修复：优先使用 HTTP 协议，避免 Docker 环境下 HTTPS TLS 指纹被识别导致超时
        # 经测试，HTTP 协议目前可绕过反爬虫
        url_http = "http://search-api-web.eastmoney.com/search/jsonp"
        url_https = "https://search-api-web.eastmoney.com/search/jsonp"
        
        param = {
            "uid": "",
            "keyword": symbol_6,
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
                    "preTag": "<em>",
                    "postTag": "</em>"
                }
            }
        }

        params = {
            "cb": f"jQuery{int(time.time() * 1000)}",
            "param": json.dumps(param),
            "_": str(int(time.time() * 1000))
        }

        response_text = None
        
        # 1. 尝试使用标准 requests + HTTP (最快，经测试在 Docker/服务器环境可行)
        try:
            import requests
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': f'https://so.eastmoney.com/news/s?keyword={symbol_6}',
                'Host': 'search-api-web.eastmoney.com',
                'Accept': '*/*',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Connection': 'keep-alive'
            }
            
            # 缩短 HTTP 超时时间，快速失败
            http_timeout = min(request_timeout, 5)
            
            response = requests.get(
                url_http,
                params=params,
                headers=headers,
                timeout=http_timeout
            )
            
            if response.status_code == 200:
                response_text = response.text
                # 简单验证是否包含数据
                if "cmsArticleWebOld" not in response_text:
                    self.logger.warning(f"⚠️ {symbol} HTTP 请求返回 200 但内容似乎无效，尝试 HTTPS")
                    response_text = None
            else:
                self.logger.warning(f"⚠️ {symbol} HTTP 请求返回错误: {response.status_code}")
                
        except Exception as e:
            self.logger.warning(f"⚠️ {symbol} HTTP 请求失败: {e}")

        # 2. 如果 HTTP 失败，尝试使用 curl_cffi + HTTPS (模拟浏览器指纹)
        if response_text is None:
            try:
                from curl_cffi import requests as curl_requests
                
                # 使用 curl_cffi 发送请求
                response = curl_requests.get(
                    url_https,
                    params=params,
                    timeout=request_timeout,
                    impersonate="chrome136"
                )

                if response.status_code == 200:
                    response_text = response.text
                else:
                    self.logger.warning(f"⚠️ {symbol} curl_cffi (HTTPS) 请求返回状态码: {response.status_code}")

            except Exception as e:
                self.logger.warning(f"⚠️ {symbol} curl_cffi (HTTPS) 请求失败: {e}")

        # 3. 如果 curl_cffi 也失败，最后尝试标准 requests + HTTPS (回退)
        if response_text is None:
            try:
                import requests
                
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Referer': 'https://www.eastmoney.com/',
                    'Accept': '*/*',
                    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                    'Connection': 'keep-alive'
                }
                
                response = requests.get(
                    url_https,
                    params=params,
                    headers=headers,
                    timeout=request_timeout
                )
                
                if response.status_code == 200:
                    response_text = response.text
                else:
                    self.logger.error(f"❌ {symbol} requests (HTTPS) 请求返回错误: {response.status_code}")
                    return None
                    
            except Exception as e:
                self.logger.error(f"❌ {symbol} 直接调用 API (所有方法) 彻底失败: {e}")
                return None

        try:
            # 解析 JSONP 响应
            if response_text.startswith("jQuery"):
                response_text = response_text[response_text.find("(")+1:response_text.rfind(")")]

            data = json.loads(response_text)

            # 检查返回数据
            if "result" not in data or "cmsArticleWebOld" not in data["result"]:
                self.logger.error(f"❌ {symbol} 东方财富网 API 返回数据结构异常")
                return None

            articles = data["result"]["cmsArticleWebOld"]

            if not articles:
                self.logger.warning(f"⚠️ {symbol} 未获取到新闻")
                return None

            # 转换为 DataFrame（与 AKShare 格式兼容）
            news_data = []
            for article in articles:
                news_data.append({
                    "新闻标题": article.get("title", ""),
                    "新闻内容": article.get("content", ""),
                    "发布时间": article.get("date", ""),
                    "新闻链接": article.get("url", ""),
                    "关键词": article.get("keywords", ""),
                    "新闻来源": article.get("source", "东方财富网"),
                    "新闻类型": article.get("type", "")
                })

            df = pd.DataFrame(news_data)
            self.logger.info(f"✅ {symbol} 直接调用 API 获取新闻成功: {len(df)} 条")
            return df

        except Exception as e:
            self.logger.error(f"❌ {symbol} 直接调用 API 失败: {e}")
            return None

    def _configure_timeout(self):
        """配置AKShare的超时设置"""
        try:
            import socket
            socket.setdefaulttimeout(60)  # 60秒超时
            logger.info("🔧 AKShare超时配置完成: 60秒")
        except Exception as e:
            logger.warning(f"⚠️ AKShare超时配置失败: {e}")
    
    async def connect(self) -> bool:
        """连接到AKShare数据源"""
        return await self.test_connection()

    async def test_connection(self) -> bool:
        """测试AKShare连接"""
        if not self.connected:
            return False

        # AKShare 是基于网络爬虫的库，不需要传统的"连接"测试
        # 只要库已经导入成功，就认为可用
        # 实际的网络请求会在具体调用时进行，并有各自的错误处理
        logger.info("✅ AKShare连接测试成功（库已加载）")
        return True
    
    def get_stock_list_sync(self) -> Optional[pd.DataFrame]:
        """获取股票列表（同步版本）"""
        if not self.connected:
            return None

        try:
            logger.info("📋 获取AKShare股票列表（同步）...")
            stock_df = self.ak.stock_info_a_code_name()

            if stock_df is None or stock_df.empty:
                logger.warning("⚠️ AKShare股票列表为空")
                return None

            logger.info(f"✅ AKShare股票列表获取成功: {len(stock_df)}只股票")
            return stock_df

        except Exception as e:
            logger.error(f"❌ AKShare获取股票列表失败: {e}")
            return None

    def get_kline(self, code: str, period: str = "daily", start_date: str = None, end_date: str = None, adjust: str = "") -> Optional[List[Dict]]:
        """
        获取K线数据（同步版本）

        优先使用直接 API 调用，失败时回退到 AKShare。
        """
        if not self.connected:
            return None

        try:
            logger.info(f"📊 获取K线: {code}, {period}, {start_date}-{end_date}")

            # --- 优先路径：直接调用东方财富 API ---
            symbol = code.split(".")[0] if "." in code else code
            ak_period = {"daily": "daily", "day": "daily", "weekly": "weekly", "month": "monthly"}.get(period, "daily")
            klines = fetch_em_hist_direct(symbol, ak_period, start_date, end_date, adjust)
            if klines:
                items = []
                for line in klines:
                    parts = line.split(",")
                    if len(parts) >= 11:
                        items.append({
                            "time": parts[0],
                            "open": float(parts[1]),
                            "close": float(parts[2]),
                            "high": float(parts[3]),
                            "low": float(parts[4]),
                            "volume": float(parts[5]),
                            "amount": float(parts[6]),
                            "amplitude": float(parts[7]) if len(parts) > 7 else 0,
                            "change_percent": float(parts[8]) if len(parts) > 8 else 0,
                            "change": float(parts[9]) if len(parts) > 9 else 0,
                            "turnover": float(parts[10]) if len(parts) > 10 else 0,
                        })
                if items:
                    logger.info(f"直接 API K线获取成功: {code} {len(items)} 条")
                    return items

            # --- 回退路径：AKShare ---
            logger.info(f"直接 API K线未命中，回退 AKShare: {code}")
            df = self.ak.stock_zh_a_hist(symbol=symbol, period=ak_period, start_date=start_date, end_date=end_date, adjust=adjust)
            if df is None or df.empty:
                logger.warning(f"K线数据为空: {code}")
                return None

            items = []
            time_col = next((c for c in ["日期", "date", "trade_date"] if c in df.columns), None)
            if time_col is None:
                logger.warning(f"无法识别时间列: {list(df.columns)}")
                return None
            for _, row in df.iterrows():
                items.append({
                    "time": str(row[time_col]),
                    "open": float(row.get("开盘", row.get("open", 0))),
                    "high": float(row.get("最高", row.get("high", 0))),
                    "low": float(row.get("最低", row.get("low", 0))),
                    "close": float(row.get("收盘", row.get("close", 0))),
                    "volume": float(row.get("成交量", row.get("volume", 0))),
                    "amount": float(row.get("成交额", row.get("amount", 0))),
                })
            logger.info(f"AKShare K线获取成功: {len(items)} 条")
            return items

        except Exception as e:
            logger.error(f"获取K线失败: {code}: {e}")
            return None

    async def get_stock_list(self, market: str = None) -> List[Dict[str, Any]]:
        """
        获取股票列表
        
        Args:
            market: 市场代码 (CN, HK, US)
            
        Returns:
            股票列表，包含代码和名称
        """
        if not self.connected:
            return []

        try:
            stock_list = []
            
            # 1. 获取A股列表 (默认或指定CN)
            if not market or market == "CN":
                logger.info("📋 获取AKShare A股列表...")
                
                stock_df = None
                
                # 尝试方法1: stock_info_a_code_name
                try:
                    def fetch_stock_list():
                        return self.ak.stock_info_a_code_name()
                    stock_df = await asyncio.to_thread(fetch_stock_list)
                except Exception as e:
                    logger.warning(f"⚠️ stock_info_a_code_name 失败: {e}")
                
                # 尝试方法2: stock_zh_a_spot_em (作为备选)
                if stock_df is None or stock_df.empty:
                    logger.info("🔄 尝试使用 stock_zh_a_spot_em 获取A股列表...")
                    try:
                        def fetch_spot_list():
                            return self.ak.stock_zh_a_spot_em()
                        stock_df = await asyncio.to_thread(fetch_spot_list)
                    except Exception as e:
                        logger.error(f"❌ stock_zh_a_spot_em 失败: {e}")

                if stock_df is not None and not stock_df.empty:
                    for _, row in stock_df.iterrows():
                        # 兼容不同的列名
                        code = str(row.get("code", "") or row.get("代码", ""))
                        name = str(row.get("name", "") or row.get("名称", ""))
                        
                        if code:
                            stock_list.append({
                                "code": code,
                                "name": name,
                                "market": "CN",
                                "source": "akshare"
                            })
                    logger.info(f"✅ AKShare A股列表获取成功: {len(stock_list)}只")
                else:
                    logger.warning("⚠️ AKShare A股列表为空")

            # 2. 获取港股列表 (默认或指定HK)
            if not market or market == "HK":
                hk_list = await self._get_hk_stock_list()
                if hk_list:
                    stock_list.extend(hk_list)

            return stock_list

        except Exception as e:
            logger.error(f"❌ AKShare获取股票列表失败: {e}")
            return []

    async def _get_hk_stock_list(self) -> List[Dict[str, Any]]:
        """获取港股列表"""
        try:
            logger.info("📋 获取AKShare港股列表...")
            
            def fetch_hk_list():
                # 使用 stock_hk_spot 获取所有港股实时行情（包含列表信息）
                # 增加重试机制
                import time
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        return self.ak.stock_hk_spot()
                    except Exception as e:
                        if attempt < max_retries - 1:
                            time.sleep(1)
                            continue
                        raise e
                return None

            df = await asyncio.to_thread(fetch_hk_list)
            
            if df is None or df.empty:
                return []
                
            hk_list = []
            for _, row in df.iterrows():
                # AKShare 港股代码通常为 5位数字
                code = str(row.get("code", "") if "code" in row else row.get("代码", ""))
                name = str(row.get("name", "") if "name" in row else row.get("名称", ""))
                
                if code:
                    # 标准化为 5位
                    clean_code = code.zfill(5)
                    # 添加 .HK 后缀以便统一识别 (或者保持纯数字，由 StockUtils 处理)
                    # StockUtils 识别 5位数字为 HK，所以保持纯数字即可，或者加 .HK
                    # Tushare 返回 .HK，为了统一，这里也返回 .HK ?
                    # AKShare 的 fetch functions 通常接受纯数字或 .HK
                    # 这里我们返回带 .HK 后缀的标准代码，方便上层使用
                    full_code = f"{clean_code}.HK"
                    
                    hk_list.append({
                        "code": full_code,
                        "symbol": clean_code,
                        "name": name,
                        "market": "HK",
                        "source": "akshare"
                    })
            
            logger.info(f"✅ AKShare港股列表获取成功: {len(hk_list)}只")
            return hk_list
            
        except Exception as e:
            logger.error(f"❌ 获取港股列表失败: {e}")
            return []
    
    async def get_stock_basic_info(self, code: str) -> Optional[Dict[str, Any]]:
        """
        获取股票基础信息
        
        Args:
            code: 股票代码
            
        Returns:
            标准化的股票基础信息
        """
        if not self.connected:
            return None
        
        try:
            logger.debug(f"📊 获取{code}基础信息...")
            
            # 获取股票基本信息
            stock_info = await self._get_stock_info_detail(code)
            
            if not stock_info:
                logger.warning(f"⚠️ 未找到{code}的基础信息")
                return None
            
            # 转换为标准化字典
            basic_info = {
                "code": code,
                "name": stock_info.get("name", f"股票{code}"),
                "area": stock_info.get("area", "未知"),
                "industry": stock_info.get("industry", "未知"),
                "market": self._determine_market(code),
                "list_date": stock_info.get("list_date", ""),
                # 扩展字段
                "full_symbol": self._get_full_symbol(code),
                "market_info": self._get_market_info(code),
                "data_source": "akshare",
                "last_sync": datetime.now(timezone.utc),
                "sync_status": "success"
            }
            
            logger.debug(f"✅ {code}基础信息获取成功")
            return basic_info
            
        except Exception as e:
            logger.error(f"❌ 获取{code}基础信息失败: {e}")
            return None
    
    async def _get_stock_list_cached(self):
        """获取缓存的股票列表（避免重复获取）"""
        from datetime import datetime, timedelta

        # 如果缓存存在且未过期（1小时），直接返回
        if self._stock_list_cache is not None and self._cache_time is not None:
            if now_utc() - self._cache_time < timedelta(hours=1):
                return self._stock_list_cache

        # 否则重新获取
        def fetch_stock_list():
            return self.ak.stock_info_a_code_name()

        try:
            stock_list = await asyncio.to_thread(fetch_stock_list)
            if stock_list is not None and not stock_list.empty:
                self._stock_list_cache = stock_list
                self._cache_time = now_utc()
                logger.info(f"✅ 股票列表缓存更新: {len(stock_list)} 只股票")
                return stock_list
        except Exception as e:
            logger.error(f"❌ 获取股票列表失败: {e}")

        return None

    async def _get_stock_info_detail(self, code: str) -> Dict[str, Any]:
        """获取股票详细信息"""
        try:
            # 检查是否为港股
            is_hk = False
            if code.endswith('.HK') or (code.isdigit() and len(code) == 5):
                is_hk = True
            
            if is_hk:
                # 港股处理
                try:
                    # 尝试从港股列表获取信息
                    def fetch_hk_list():
                        return self.ak.stock_hk_spot()
                    
                    hk_list = await asyncio.to_thread(fetch_hk_list)
                    if hk_list is not None and not hk_list.empty:
                        # 尝试匹配代码 (支持 00700 和 00700.HK)
                        clean_code = code.replace('.HK', '')
                        # stock_hk_spot 返回的列名是中文: 代码, 中文名称
                        # 确保列名存在
                        if '代码' in hk_list.columns:
                            stock_row = hk_list[hk_list['代码'] == clean_code]
                            
                            if not stock_row.empty:
                                row = stock_row.iloc[0]
                                name = str(row['中文名称']) if '中文名称' in row else f"港股{clean_code}"
                                return {
                                    "code": code,
                                    "name": name,
                                    "industry": "未知", # stock_hk_spot 没有行业信息
                                    "area": "HK",
                                    "list_date": "未知"
                                }
                        # 尝试英文列名 (以防万一)
                        elif 'symbol' in hk_list.columns:
                            stock_row = hk_list[hk_list['symbol'] == clean_code]
                            if not stock_row.empty:
                                row = stock_row.iloc[0]
                                return {
                                    "code": code,
                                    "name": str(row.get('name', f"港股{clean_code}")),
                                    "industry": str(row.get('industry', '未知')),
                                    "area": "HK",
                                    "list_date": "未知"
                                }
                except Exception as e:
                    logger.debug(f"获取港股{code}信息失败: {e}")
                
                return {"code": code, "name": f"港股{code}", "industry": "未知", "area": "HK"}

            # A股处理
            # 方法1: 尝试获取个股详细信息（包含行业、地区等详细信息）
            def fetch_individual_info():
                return self.ak.stock_individual_info_em(symbol=code)

            try:
                stock_info = await asyncio.to_thread(fetch_individual_info)

                if stock_info is not None and not stock_info.empty:
                    # 解析信息
                    info = {"code": code}

                    # 提取股票名称
                    name_row = stock_info[stock_info['item'] == '股票简称']
                    if not name_row.empty:
                        info['name'] = str(name_row['value'].iloc[0])

                    # 提取行业信息
                    industry_row = stock_info[stock_info['item'] == '所属行业']
                    if not industry_row.empty:
                        info['industry'] = str(industry_row['value'].iloc[0])

                    # 提取地区信息
                    area_row = stock_info[stock_info['item'] == '所属地区']
                    if not area_row.empty:
                        info['area'] = str(area_row['value'].iloc[0])

                    # 提取上市日期
                    list_date_row = stock_info[stock_info['item'] == '上市时间']
                    if not list_date_row.empty:
                        info['list_date'] = str(list_date_row['value'].iloc[0])

                    return info
            except Exception as e:
                # 检查是否为 DataFrame 创建错误
                if "If using all scalar values, you must pass an index" in str(e):
                    logger.warning(f"⚠️ AKShare stock_individual_info_em 返回了标量值但未包含索引，尝试兼容处理: {e}")
                    # 某些版本的 AKShare 可能直接返回标量或非标准结构，这里作为降级
                    # 但由于我们也无法直接获取数据内容（它在内部抛出异常），只能跳过并记录
                else:
                    logger.debug(f"获取{code}个股详细信息失败: {e}")

            # 方法2: 从缓存的股票列表中获取基本信息（只有代码和名称）
            try:
                stock_list = await self._get_stock_list_cached()
                if stock_list is not None and not stock_list.empty:
                    stock_row = stock_list[stock_list['code'] == code]
                    if not stock_row.empty:
                        return {
                            "code": code,
                            "name": str(stock_row['name'].iloc[0]),
                            "industry": "未知",
                            "area": "未知"
                        }
            except Exception as e:
                logger.debug(f"从股票列表获取{code}信息失败: {e}")

            # 如果都失败，返回基本信息
            return {"code": code, "name": f"股票{code}", "industry": "未知", "area": "未知"}

        except Exception as e:
            logger.debug(f"获取{code}详细信息失败: {e}")
            return {"code": code, "name": f"股票{code}", "industry": "未知", "area": "未知"}
    
    def _determine_market(self, code: str) -> str:
        """根据股票代码判断市场"""
        if code.startswith(('60', '68')):
            return "上海证券交易所"
        elif code.startswith(('00', '30')):
            return "深圳证券交易所"
        elif code.startswith('8'):
            return "北京证券交易所"
        else:
            return "未知市场"
    
    def _get_full_symbol(self, code: str) -> str:
        """
        获取完整股票代码

        Args:
            code: 6位股票代码

        Returns:
            完整标准化代码，如果无法识别则返回原始代码（确保不为空）
        """
        # 确保 code 不为空
        if not code:
            return ""

        # 标准化为字符串
        code = str(code).strip()

        # 根据代码前缀判断交易所
        if code.startswith(('60', '68', '90')):  # 上海证券交易所（增加90开头的B股）
            return f"{code}.SS"
        elif code.startswith(('00', '30', '20')):  # 深圳证券交易所（增加20开头的B股）
            return f"{code}.SZ"
        elif code.startswith(('8', '4')):  # 北京证券交易所（增加4开头的新三板）
            return f"{code}.BJ"
        else:
            # 无法识别的代码，返回原始代码（确保不为空）
            return code if code else ""
    
    def _get_market_info(self, code: str) -> Dict[str, Any]:
        """获取市场信息"""
        # 使用 StockUtils 识别市场
        market = StockUtils.identify_stock_market(code)
        
        if market == StockMarket.HONG_KONG:
            return {
                "market_type": "HK",
                "exchange": "HKEX",
                "exchange_name": "香港证券交易所",
                "currency": "HKD",
                "timezone": "Asia/Hong_Kong"
            }
        
        # A股判断保持原有逻辑或优化
        from app.engine.config.runtime_settings import get_timezone_name
        cn_timezone = get_timezone_name()

        if code.startswith(('60', '68')):
            return {
                "market_type": "CN",
                "exchange": "SSE",
                "exchange_name": "上海证券交易所",
                "currency": "CNY",
                "timezone": cn_timezone
            }
        elif code.startswith(('00', '30')):
            return {
                "market_type": "CN",
                "exchange": "SZSE",
                "exchange_name": "深圳证券交易所",
                "currency": "CNY",
                "timezone": cn_timezone
            }
        elif code.startswith('8'):
            return {
                "market_type": "CN",
                "exchange": "BSE",
                "exchange_name": "北京证券交易所",
                "currency": "CNY",
                "timezone": cn_timezone
            }
        else:
            return {
                "market_type": "CN",
                "exchange": "UNKNOWN",
                "exchange_name": "未知交易所",
                "currency": "CNY",
                "timezone": cn_timezone
            }
    
    async def get_batch_stock_quotes(self, codes: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        批量获取股票实时行情（优化版：一次获取全市场快照）

        优先使用新浪财经接口（更稳定），失败时回退到东方财富接口

        Args:
            codes: 股票代码列表

        Returns:
            股票代码到行情数据的映射字典
        """
        if not self.connected:
            return {}

        # --- 优先路径：直接调用东方财富 API（绕过 AKShare，反爬能力最强） ---
        try:
            diff_data = await asyncio.to_thread(fetch_em_spot_direct)
            if diff_data:
                quotes_map = {}
                codes_set = set(codes)
                for item in diff_data:
                    raw_code = str(item.get("f12", "")).zfill(6)
                    if raw_code in codes_set:
                        quotes_map[raw_code] = {
                            "code": raw_code,
                            "symbol": raw_code,
                            "name": str(item.get("f14", f"股票{raw_code}")),
                            "price": self._safe_float(item.get("f2", 0)),
                            "change": self._safe_float(item.get("f4", 0)),
                            "change_percent": self._safe_float(item.get("f3", 0)),
                            "volume": self._safe_int(item.get("f5", 0)),
                            "amount": self._safe_float(item.get("f6", 0)),
                            "open_price": self._safe_float(item.get("f17", 0)),
                            "high_price": self._safe_float(item.get("f15", 0)),
                            "low_price": self._safe_float(item.get("f16", 0)),
                            "pre_close": self._safe_float(item.get("f18", 0)),
                            "turnover_rate": self._safe_float(item.get("f8", None)),
                            "volume_ratio": self._safe_float(item.get("f10", None)),
                            "pe": self._safe_float(item.get("f9", None)),
                            "pe_ttm": self._safe_float(item.get("f9", None)),
                            "pb": self._safe_float(item.get("f23", None)),
                            "total_mv": self._safe_float(item.get("f20", None)) / 1e8 if item.get("f20") else None,
                            "circ_mv": self._safe_float(item.get("f21", None)) / 1e8 if item.get("f21") else None,
                            "full_symbol": self._get_full_symbol(raw_code),
                            "market_info": self._get_market_info(raw_code),
                            "data_source": "eastmoney_direct",
                            "last_sync": datetime.now(timezone.utc),
                            "sync_status": "success",
                        }
                logger.info(f"直接 API 批量行情: {len(quotes_map)}/{len(codes)} 只")
                return quotes_map
        except Exception as e:
            logger.warning(f"东方财富直接 API 批量行情失败: {e}")

        # --- 第二优先路径：腾讯行情 API（快速、稳定、不受 push2 封禁影响） ---
        try:
            tencent_data = await asyncio.to_thread(fetch_tencent_spot_batch, codes)
            if tencent_data:
                quotes_map = {}
                for code, item in tencent_data.items():
                    raw_total = None
                    raw_circ = None
                    quotes_map[code] = {
                        "code": code,
                        "symbol": code,
                        "name": item.get("name", f"股票{code}"),
                        "price": item.get("price", 0) or 0,
                        "change": item.get("change", 0) or 0,
                        "change_percent": item.get("change_pct", 0) or 0,
                        "volume": item.get("volume", 0) or 0,
                        "amount": item.get("amount", 0) or 0,
                        "open_price": item.get("open", 0) or 0,
                        "high_price": item.get("high", 0) or 0,
                        "low_price": item.get("low", 0) or 0,
                        "pre_close": item.get("pre_close", 0) or 0,
                        "turnover_rate": item.get("turnover_rate"),
                        "volume_ratio": None,
                        "pe": item.get("pe"),
                        "pe_ttm": item.get("pe"),
                        "pb": None,
                        "total_mv": raw_total / 1e8 if raw_total else None,
                        "circ_mv": raw_circ / 1e8 if raw_circ else None,
                        "full_symbol": self._get_full_symbol(code),
                        "market_info": self._get_market_info(code),
                        "data_source": "tencent",
                        "last_sync": datetime.now(timezone.utc),
                        "sync_status": "success",
                    }
                logger.info(f"腾讯行情批量: {len(quotes_map)}/{len(codes)} 只")
                return quotes_map
        except Exception as e:
            logger.warning(f"腾讯行情批量失败: {e}")

        # --- 第三优先路径：AKShare（新浪 → 东方财富 EM） ---
        max_retries = 2
        for attempt in range(max_retries):
            try:
                try:
                    spot_df = await asyncio.to_thread(lambda: self.ak.stock_zh_a_spot())
                except Exception:
                    spot_df = await asyncio.to_thread(lambda: self.ak.stock_zh_a_spot_em())

                if spot_df is None or spot_df.empty:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(1)
                        continue
                    return {}

                quotes_map = {}
                codes_set = set(codes)
                code_mapping = {}
                for code in codes:
                    code_mapping[code] = code
                    for prefix in ['sh', 'sz', 'bj']:
                        code_mapping[f"{prefix}{code}"] = code

                for _, row in spot_df.iterrows():
                    raw_code = str(row.get("代码", ""))
                    matched_code = code_mapping.get(raw_code) or (raw_code if raw_code in codes_set else None)
                    if not matched_code:
                        continue

                    raw_pe = self._safe_float(row.get("市盈率-动态", None))
                    raw_pb = self._safe_float(row.get("市净率", None))
                    raw_total = self._safe_float(row.get("总市值", None))
                    raw_circ = self._safe_float(row.get("流通市值", None))
                    quotes_map[matched_code] = {
                        "code": matched_code,
                        "symbol": matched_code,
                        "name": str(row.get("名称", f"股票{matched_code}")),
                        "price": self._safe_float(row.get("最新价", 0)),
                        "change": self._safe_float(row.get("涨跌额", 0)),
                        "change_percent": self._safe_float(row.get("涨跌幅", 0)),
                        "volume": self._safe_int(row.get("成交量", 0)),
                        "amount": self._safe_float(row.get("成交额", 0)),
                        "open_price": self._safe_float(row.get("今开", 0)),
                        "high_price": self._safe_float(row.get("最高", 0)),
                        "low_price": self._safe_float(row.get("最低", 0)),
                        "pre_close": self._safe_float(row.get("昨收", 0)),
                        "turnover_rate": self._safe_float(row.get("换手率", None)),
                        "volume_ratio": self._safe_float(row.get("量比", None)),
                        "pe": raw_pe,
                        "pe_ttm": raw_pe,
                        "pb": raw_pb,
                        "total_mv": raw_total / 1e8 if raw_total else None,
                        "circ_mv": raw_circ / 1e8 if raw_circ else None,
                        "full_symbol": self._get_full_symbol(matched_code),
                        "market_info": self._get_market_info(matched_code),
                        "data_source": "akshare",
                        "last_sync": datetime.now(timezone.utc),
                        "sync_status": "success",
                    }

                found_count = len(quotes_map)
                missing_count = len(codes) - found_count
                logger.debug(f"AKShare 批量行情: {found_count}/{len(codes)} 只")
                if missing_count > 0:
                    missing_codes = codes_set - set(quotes_map.keys())
                    logger.debug(f"未找到行情: {list(missing_codes)[:10]}{'...' if missing_count > 10 else ''}")
                return quotes_map

            except Exception as e:
                logger.warning(f"AKShare 批量行情失败 ({attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                else:
                    logger.error(f"批量获取行情失败: {e}")
                    return {}

    def _is_index(self, code: str) -> bool:
        """判断是否为指数代码"""
        # 上证指数：000开头，.SH后缀
        if code.endswith('.SH') and code.startswith('000'):
            return True
        # 深证指数：399开头，.SZ后缀
        if code.endswith('.SZ') and code.startswith('399'):
            return True
        return False

    async def get_stock_quotes(self, code: str) -> Optional[Dict[str, Any]]:
        """
        获取单个股票实时行情
        """
        if not self.connected:
            return None

        try:
            # 识别市场
            market = StockUtils.identify_stock_market(code)
            
            # ========== 港股处理 ==========
            if market == StockMarket.HONG_KONG:
                # 移除 .HK 后缀
                symbol = code.replace(".HK", "")
                logger.info(f"📈 获取港股 {code} (symbol={symbol}) 行情...")
                
                # 使用 stock_hk_hist 获取日线数据作为行情 (因为没有单只港股实时接口)
                # 获取最近3天的数据
                from datetime import datetime, timedelta, timezone
                end_date = format_date_compact(now_config_tz())
                start_date = (now_utc() - timedelta(days=5)).strftime('%Y%m%d')
                
                def fetch_hk_hist():
                    return self.ak.stock_hk_hist(
                        symbol=symbol,
                        period="daily",
                        start_date=start_date,
                        end_date=end_date,
                        adjust=""
                    )
                
                df = await asyncio.to_thread(fetch_hk_hist)
                
                if df is not None and not df.empty:
                    # 取最新一天
                    row = df.iloc[-1]
                    
                    # 映射字段 (akshare hk hist 返回列名通常是中文)
                    # 日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额, ...
                    quotes = {
                        "code": code,
                        "symbol": symbol,
                        "name": f"港股{symbol}", # 历史数据不含名称
                        "price": self._safe_float(row.get("收盘", 0)),
                        "close": self._safe_float(row.get("收盘", 0)),
                        "open": self._safe_float(row.get("开盘", 0)),
                        "high": self._safe_float(row.get("最高", 0)),
                        "low": self._safe_float(row.get("最低", 0)),
                        "volume": self._safe_float(row.get("成交量", 0)),
                        "amount": self._safe_float(row.get("成交额", 0)),
                        "change": self._safe_float(row.get("涨跌额", 0)),
                        "change_percent": self._safe_float(row.get("涨跌幅", 0)),
                        # 补充字段
                        "market_info": self._get_market_info(code),
                        "data_source": "akshare",
                        "last_sync": datetime.now(timezone.utc),
                        "trade_date": str(row.get("日期", ""))
                    }
                    
                    return quotes
                else:
                    logger.warning(f"⚠️ 未找到港股 {code} 的行情数据")
                    return None

            # ========== 指数处理 ==========
            if self._is_index(code):
                logger.info(f"📈 获取指数 {code} 实时行情...")
                
                def fetch_index_spot():
                    # 尝试使用东方财富接口 (stock_zh_index_spot_em)
                    try:
                        # 东方财富指数实时行情，symbol参数通常是 "上证系列指数", "深证系列指数" 等
                        # 或者尝试不传参数获取所有
                        if hasattr(self.ak, 'stock_zh_index_spot_em'):
                            # 尝试获取上证和深证指数
                            df_sh = self.ak.stock_zh_index_spot_em(symbol="上证系列指数")
                            df_sz = self.ak.stock_zh_index_spot_em(symbol="深证系列指数")
                            
                            # 合并数据
                            frames = []
                            if df_sh is not None and not df_sh.empty:
                                frames.append(df_sh)
                            if df_sz is not None and not df_sz.empty:
                                frames.append(df_sz)
                                
                            if frames:
                                return pd.concat(frames, ignore_index=True)
                    except Exception as e:
                        logger.warning(f"⚠️ 东方财富指数接口调用失败: {e}")

                    # 尝试新浪接口 (stock_zh_index_spot_sina)
                    try:
                        if hasattr(self.ak, 'stock_zh_index_spot_sina'):
                            return self.ak.stock_zh_index_spot_sina()
                    except Exception as e:
                        logger.warning(f"⚠️ 新浪指数接口调用失败: {e}")
                        
                    # 尝试旧接口
                    if hasattr(self.ak, 'stock_zh_index_spot'):
                        return self.ak.stock_zh_index_spot()
                        
                    return None

                spot_df = await asyncio.to_thread(fetch_index_spot)
                
                if spot_df is not None and not spot_df.empty:
                    # 查找对应指数
                    # 代码格式通常是 sh000001 或 sz399001
                    symbol = code.replace('.', '').lower() # 000001.SH -> 000001sh (wrong) -> sh000001
                    if code.endswith('.SH'):
                        symbol = f"sh{code[:6]}"
                    elif code.endswith('.SZ'):
                        symbol = f"sz{code[:6]}"
                    
                    # 尝试匹配
                    # stock_zh_index_spot 返回列：代码, 名称, 最新价, 涨跌额, 涨跌幅, ...
                    # 代码列通常是 sh000001 格式
                    
                    target_row = spot_df[spot_df['代码'] == symbol]
                    
                    if target_row.empty:
                        # 尝试不带前缀匹配
                        target_row = spot_df[spot_df['代码'] == code[:6]]
                    
                    if not target_row.empty:
                        row = target_row.iloc[0]

                        now_cn = now_config_tz()

                        quotes = {
                            "code": code,
                            "symbol": code[:6],
                            "name": str(row.get("名称", "")),
                            "price": self._safe_float(row.get("最新价", 0)),
                            "close": self._safe_float(row.get("最新价", 0)),
                            "change": self._safe_float(row.get("涨跌额", 0)),
                            "change_percent": self._safe_float(row.get("涨跌幅", 0)),
                            "volume": self._safe_float(row.get("成交量", 0)),
                            "amount": self._safe_float(row.get("成交额", 0)),
                            "open": self._safe_float(row.get("今开", 0)),
                            "high": self._safe_float(row.get("最高", 0)),
                            "low": self._safe_float(row.get("最低", 0)),
                            "pre_close": self._safe_float(row.get("昨收", 0)),
                            "market_info": self._get_market_info(code),
                            "data_source": "akshare",
                            "last_sync": now_utc(),
                            "updated_at": format_iso(now_cn)
                        }
                        return quotes
                    else:
                        logger.warning(f"⚠️ 未在指数列表中找到 {code} (symbol={symbol})")
                else:
                    logger.warning("⚠️ 获取指数列表为空")
                
                # 如果实时行情失败，尝试获取日线最新一条
                return await self._get_index_latest_daily(code)

            # ========== A股处理 ==========
            symbol = code.split(".")[0] if "." in code else code

            # --- 优先路径 1：直接调用东方财富 API ---
            em_data = await asyncio.to_thread(fetch_em_bid_ask_direct, symbol)
            if em_data:
                price_raw = self._safe_float(em_data.get("f43", 0))
                pre_close_raw = self._safe_float(em_data.get("f60", 0))
                change = round(price_raw - pre_close_raw, 2) if price_raw and pre_close_raw else 0
                change_pct = round(change / pre_close_raw * 100, 2) if pre_close_raw else 0

                from app.utils.time_utils import now_config_tz, format_date_short
                now_cn = now_config_tz()

                raw_total = self._safe_float(em_data.get("f116", None))
                raw_circ = self._safe_float(em_data.get("f117", None))
                quotes = {
                    "code": code,
                    "symbol": code,
                    "name": str(em_data.get("f58", f"股票{code}")),
                    "price": price_raw,
                    "close": price_raw,
                    "current_price": price_raw,
                    "change": change,
                    "change_percent": change_pct,
                    "pct_chg": change_pct,
                    "volume": self._safe_int(em_data.get("f47", 0)),
                    "amount": self._safe_float(em_data.get("f48", 0)),
                    "open": self._safe_float(em_data.get("f46", 0)),
                    "high": self._safe_float(em_data.get("f44", 0)),
                    "low": self._safe_float(em_data.get("f45", 0)),
                    "pre_close": pre_close_raw,
                    "turnover_rate": self._safe_float(em_data.get("f168", None)),
                    "volume_ratio": self._safe_float(em_data.get("f50", None)),
                    "pe": self._safe_float(em_data.get("f162", None)),
                    "pe_ttm": self._safe_float(em_data.get("f162", None)),
                    "pb": self._safe_float(em_data.get("f167", None)),
                    "total_mv": raw_total / 1e8 if raw_total else None,
                    "circ_mv": raw_circ / 1e8 if raw_circ else None,
                    "trade_date": format_date_short(now_cn),
                    "updated_at": now_cn.isoformat(),
                    "full_symbol": self._get_full_symbol(code),
                    "market_info": self._get_market_info(code),
                    "data_source": "eastmoney_direct",
                    "last_sync": datetime.now(timezone.utc),
                    "sync_status": "success",
                }
                logger.info(f"{code} 直接 API 行情: 价={quotes['price']}, 涨跌={change_pct}%")
                return quotes

            # --- 优先路径 2：腾讯行情 API（不受 push2 封禁影响） ---
            try:
                tencent_data = await asyncio.to_thread(fetch_tencent_spot_batch, [symbol])
                if tencent_data and symbol in tencent_data:
                    item = tencent_data[symbol]
                    from app.utils.time_utils import now_config_tz, format_date_short
                    now_cn = now_config_tz()

                    quotes = {
                        "code": code,
                        "symbol": code,
                        "name": item.get("name", f"股票{code}"),
                        "price": item.get("price", 0) or 0,
                        "close": item.get("price", 0) or 0,
                        "current_price": item.get("price", 0) or 0,
                        "change": item.get("change", 0) or 0,
                        "change_percent": item.get("change_pct", 0) or 0,
                        "pct_chg": item.get("change_pct", 0) or 0,
                        "volume": item.get("volume", 0) or 0,
                        "amount": item.get("amount", 0) or 0,
                        "open": item.get("open", 0) or 0,
                        "high": item.get("high", 0) or 0,
                        "low": item.get("low", 0) or 0,
                        "pre_close": item.get("pre_close", 0) or 0,
                        "turnover_rate": item.get("turnover_rate"),
                        "volume_ratio": None,
                        "pe": item.get("pe"),
                        "pe_ttm": item.get("pe"),
                        "pb": None,
                        "total_mv": None,
                        "circ_mv": None,
                        "trade_date": format_date_short(now_cn),
                        "updated_at": now_cn.isoformat(),
                        "full_symbol": self._get_full_symbol(code),
                        "market_info": self._get_market_info(code),
                        "data_source": "tencent",
                        "last_sync": now_utc(),
                        "sync_status": "success",
                    }
                    logger.info(f"{code} 腾讯行情: 价={quotes['price']}, 涨跌={quotes['change_percent']}%")
                    return quotes
            except Exception as e:
                logger.debug(f"{code} 腾讯行情失败: {e}")

            # --- 回退路径：AKShare stock_bid_ask_em ---

            @retry(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=1, max=4),
                retry=retry_if_exception_type((ConnectionError, TimeoutError)),
                reraise=True
            )
            def fetch_bid_ask():
                return self.ak.stock_bid_ask_em(symbol=symbol)

            try:
                bid_ask_df = await asyncio.to_thread(fetch_bid_ask)
            except ConnectionError:
                logger.error(f"AKShare 连接失败 {code}")
                return None
            except TimeoutError:
                logger.warning(f"AKShare 请求超时 {code}")
                return None
            except Exception as e:
                logger.error(f"AKShare 未知错误 {code}: {e}", exc_info=True)
                return None

            if bid_ask_df is None or bid_ask_df.empty:
                logger.warning(f"未找到{code}的行情数据")
                return None

            data_dict = dict(zip(bid_ask_df['item'], bid_ask_df['value']))

            from app.utils.time_utils import now_config_tz, format_date_short
            now_cn = now_config_tz()
            volume_in_shares = int(data_dict.get("总手", 0)) * 100

            quotes = {
                "code": code,
                "symbol": code,
                "name": f"股票{code}",
                "price": float(data_dict.get("最新", 0)),
                "close": float(data_dict.get("最新", 0)),
                "current_price": float(data_dict.get("最新", 0)),
                "change": float(data_dict.get("涨跌", 0)),
                "change_percent": float(data_dict.get("涨幅", 0)),
                "pct_chg": float(data_dict.get("涨幅", 0)),
                "volume": volume_in_shares,
                "amount": float(data_dict.get("金额", 0)),
                "open": float(data_dict.get("今开", 0)),
                "high": float(data_dict.get("最高", 0)),
                "low": float(data_dict.get("最低", 0)),
                "pre_close": float(data_dict.get("昨收", 0)),
                "turnover_rate": float(data_dict.get("换手", 0)),
                "volume_ratio": float(data_dict.get("量比", 0)),
                "pe": None,
                "pe_ttm": None,
                "pb": None,
                "total_mv": None,
                "circ_mv": None,
                "trade_date": format_date_short(now_cn),
                "updated_at": now_cn.isoformat(),
                "full_symbol": self._get_full_symbol(code),
                "market_info": self._get_market_info(code),
                "data_source": "akshare",
                "last_sync": datetime.now(timezone.utc),
                "sync_status": "success",
            }
            logger.info(f"{code} AKShare 行情: 价={quotes['price']}, 涨跌={quotes['change_percent']}%")
            return quotes

        except Exception as e:
            logger.error(f"获取{code}实时行情失败: {e}", exc_info=True)
            return None
    
    async def _get_realtime_quotes_data(self, code: str) -> Dict[str, Any]:
        """获取实时行情数据"""
        try:
            # 方法1: 获取A股实时行情
            def fetch_spot_data():
                return self.ak.stock_zh_a_spot_em()

            try:
                spot_df = await asyncio.to_thread(fetch_spot_data)

                if spot_df is not None and not spot_df.empty:
                    # 查找对应股票
                    stock_data = spot_df[spot_df['代码'] == code]

                    if not stock_data.empty:
                        row = stock_data.iloc[0]

                        # 解析行情数据
                        return {
                            "name": str(row.get("名称", f"股票{code}")),
                            "price": self._safe_float(row.get("最新价", 0)),
                            "change": self._safe_float(row.get("涨跌额", 0)),
                            "change_percent": self._safe_float(row.get("涨跌幅", 0)),
                            "volume": self._safe_int(row.get("成交量", 0)),
                            "amount": self._safe_float(row.get("成交额", 0)),
                            "open": self._safe_float(row.get("今开", 0)),
                            "high": self._safe_float(row.get("最高", 0)),
                            "low": self._safe_float(row.get("最低", 0)),
                            "pre_close": self._safe_float(row.get("昨收", 0)),
                            # 🔥 新增：财务指标字段
                            "turnover_rate": self._safe_float(row.get("换手率", None)),  # 换手率（%）
                            "volume_ratio": self._safe_float(row.get("量比", None)),  # 量比
                            "pe": self._safe_float(row.get("市盈率-动态", None)),  # 动态市盈率
                            "pb": self._safe_float(row.get("市净率", None)),  # 市净率
                            "total_mv": self._safe_float(row.get("总市值", None)),  # 总市值（元）
                            "circ_mv": self._safe_float(row.get("流通市值", None)),  # 流通市值（元）
                        }
            except Exception as e:
                logger.debug(f"获取{code}A股实时行情失败: {e}")

            # 方法2: 尝试获取单只股票实时数据
            def fetch_individual_spot():
                return self.ak.stock_zh_a_hist(symbol=code, period="daily", adjust="")

            try:
                hist_df = await asyncio.to_thread(fetch_individual_spot)
                if hist_df is not None and not hist_df.empty:
                    # 取最新一天的数据作为当前行情
                    latest_row = hist_df.iloc[-1]
                    return {
                        "name": f"股票{code}",
                        "price": self._safe_float(latest_row.get("收盘", 0)),
                        "change": 0,  # 历史数据无法计算涨跌额
                        "change_percent": self._safe_float(latest_row.get("涨跌幅", 0)),
                        "volume": self._safe_int(latest_row.get("成交量", 0)),
                        "amount": self._safe_float(latest_row.get("成交额", 0)),
                        "open": self._safe_float(latest_row.get("开盘", 0)),
                        "high": self._safe_float(latest_row.get("最高", 0)),
                        "low": self._safe_float(latest_row.get("最低", 0)),
                        "pre_close": self._safe_float(latest_row.get("收盘", 0))
                    }
            except Exception as e:
                logger.debug(f"获取{code}历史数据作为行情失败: {e}")

            return {}

        except Exception as e:
            logger.debug(f"获取{code}实时行情数据失败: {e}")
            return {}
    
    async def _get_index_latest_daily(self, code: str) -> Optional[Dict[str, Any]]:
        """获取指数最新日线数据作为行情"""
        try:
            # 构造 symbol
            symbol = code
            if code.endswith('.SH'):
                symbol = f"sh{code[:6]}"
            elif code.endswith('.SZ'):
                symbol = f"sz{code[:6]}"

            def fetch_daily():
                return self.ak.stock_zh_index_daily(symbol=symbol)

            df = await asyncio.to_thread(fetch_daily)
            
            if df is not None and not df.empty:
                row = df.iloc[-1]
                # date, open, high, low, close, volume

                now_cn = now_config_tz()

                quotes = {
                    "code": code,
                    "symbol": code[:6],
                    "name": f"指数{code[:6]}", # 日线数据不含名称
                    "price": self._safe_float(row.get("close", 0)),
                    "close": self._safe_float(row.get("close", 0)),
                    "open": self._safe_float(row.get("open", 0)),
                    "high": self._safe_float(row.get("high", 0)),
                    "low": self._safe_float(row.get("low", 0)),
                    "volume": self._safe_float(row.get("volume", 0)),
                    "amount": 0.0,
                    "change": 0.0,
                    "change_percent": 0.0,
                    "market_info": self._get_market_info(code),
                    "data_source": "akshare",
                    "last_sync": now_utc(),
                    "updated_at": format_iso(now_cn),
                    "trade_date": str(row.get("date", ""))
                }
                return quotes
            return None
        except Exception as e:
            logger.error(f"❌ 获取指数 {code} 日线数据失败: {e}")
            return None

    def _safe_float(self, value: Any) -> float:
        """安全转换为浮点数"""
        try:
            if pd.isna(value) or value is None:
                return 0.0
            return float(value)
        except (ValueError, TypeError):
            return 0.0
    
    def _safe_int(self, value: Any) -> int:
        """安全转换为整数"""
        try:
            if pd.isna(value) or value is None:
                return 0
            return int(float(value))
        except (ValueError, TypeError):
            return 0
    
    def _safe_str(self, value: Any) -> str:
        """安全转换为字符串"""
        try:
            if pd.isna(value) or value is None:
                return ""
            return str(value)
        except:
            return ""

    async def get_historical_data(
        self,
        code: str,
        start_date: str,
        end_date: str,
        period: str = "daily"
    ) -> Optional[pd.DataFrame]:
        """
        获取历史行情数据
        
        Args:
            code: 股票代码
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            period: 周期 (daily, weekly, monthly)
            
        Returns:
            历史行情数据DataFrame
        """
        if not self.connected:
            return None

        try:
            logger.debug(f"📊 获取{code}历史数据: {start_date} 到 {end_date}")

            # 转换周期格式
            period_map = {
                "daily": "daily",
                "weekly": "weekly",
                "monthly": "monthly"
            }
            ak_period = period_map.get(period, "daily")

            # 格式化日期
            start_date_formatted = start_date.replace('-', '')
            end_date_formatted = end_date.replace('-', '')
            
            # 识别市场
            market = StockUtils.identify_stock_market(code)

            # 获取历史数据
            def fetch_historical_data():
                if market == StockMarket.HONG_KONG:
                    # 港股处理
                    symbol = code.replace(".HK", "")
                    return self.ak.stock_hk_hist(
                        symbol=symbol,
                        period=ak_period,
                        start_date=start_date_formatted,
                        end_date=end_date_formatted,
                        adjust="qfq"
                    )
                elif self._is_index(code):
                    # 指数处理
                    symbol = code
                    if code.endswith('.SH'):
                        symbol = f"sh{code[:6]}"
                    elif code.endswith('.SZ'):
                        symbol = f"sz{code[:6]}"
                    
                    df = self.ak.stock_zh_index_daily(symbol=symbol)
                    
                    if df is not None and not df.empty:
                        # 转换日期列为 datetime
                        df['date'] = pd.to_datetime(df['date'])
                        
                        # 筛选日期范围
                        start_dt = pd.to_datetime(start_date)
                        end_dt = pd.to_datetime(end_date)
                        
                        mask = (df['date'] >= start_dt) & (df['date'] <= end_dt)
                        df = df.loc[mask]
                        
                        # 重命名列以匹配标准处理 (stock_zh_index_daily 返回英文列名)
                        # date, open, high, low, close, volume
                        # 只是为了保持一致性，其实 _standardize_historical_columns 会处理
                    
                    return df
                else:
                    # A股处理
                    # 移除后缀 (.SH, .SZ, .BJ)
                    symbol = code
                    if "." in code:
                        symbol = code.split(".")[0]
                        
                    return self.ak.stock_zh_a_hist(
                        symbol=symbol,
                        period=ak_period,
                        start_date=start_date_formatted,
                        end_date=end_date_formatted,
                        adjust="qfq"  # 前复权
                    )

            hist_df = await asyncio.to_thread(fetch_historical_data)

            if hist_df is None or hist_df.empty:
                logger.warning(f"⚠️ {code}历史数据为空")
                return None

            # 标准化列名
            hist_df = self._standardize_historical_columns(hist_df, code)

            logger.debug(f"✅ {code}历史数据获取成功: {len(hist_df)}条记录")
            return hist_df

        except Exception as e:
            logger.error(f"❌ 获取{code}历史数据失败: {e}")
            return None

    def _standardize_historical_columns(self, df: pd.DataFrame, code: str) -> pd.DataFrame:
        """标准化历史数据列名"""
        try:
            # 标准化列名映射
            column_mapping = {
                '日期': 'date',
                '开盘': 'open',
                '收盘': 'close',
                '最高': 'high',
                '最低': 'low',
                '成交量': 'volume',
                '成交额': 'amount',
                '振幅': 'amplitude',
                '涨跌幅': 'change_percent',
                '涨跌额': 'change',
                '换手率': 'turnover'
            }

            # 重命名列
            df = df.rename(columns=column_mapping)

            # 添加标准字段
            df['code'] = code
            df['full_symbol'] = self._get_full_symbol(code)

            # 确保日期格式
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])

            # 数据类型转换
            numeric_columns = ['open', 'close', 'high', 'low', 'volume', 'amount']
            for col in numeric_columns:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

            return df

        except Exception as e:
            logger.error(f"标准化{code}历史数据列名失败: {e}")
            return df

    async def get_financial_data(self, code: str) -> Dict[str, Any]:
        """
        获取财务数据

        Args:
            code: 股票代码（支持多种格式：000001.SZ, 000001, SH600000）

        Returns:
            财务数据字典
        """
        if not self.connected:
            return {}

        try:
            logger.debug(f"💰 获取{code}财务数据...")

            financial_data = {}

            # 标准化股票代码为不同格式
            code_6digit = code.replace('.SH', '').replace('.SZ', '').replace('.sh', '').replace('.sz', '').zfill(6)

            # 判断交易所
            if code.startswith('6'):
                code_shsz = f"SH{code_6digit}"
                exchange = "SH"
            elif code.startswith(('0', '3')):
                code_shsz = f"SZ{code_6digit}"
                exchange = "SZ"
            else:
                # 从原始代码提取交易所信息
                if '.SH' in code.upper() or code.startswith('6'):
                    code_shsz = f"SH{code_6digit}"
                    exchange = "SH"
                else:
                    code_shsz = f"SZ{code_6digit}"
                    exchange = "SZ"

            logger.debug(f"🔧 代码转换: {code} -> 6位:{code_6digit}, SH/SZ格式:{code_shsz}")

            # 1. 获取主要财务指标（使用6位纯数字）
            try:
                def fetch_financial_abstract():
                    return self.ak.stock_financial_abstract(symbol=code_6digit)

                main_indicators = await asyncio.to_thread(fetch_financial_abstract)
                if main_indicators is not None and not main_indicators.empty:
                    financial_data['main_indicators'] = main_indicators.to_dict('records')
                    logger.debug(f"✅ {code}主要财务指标获取成功")
            except Exception as e:
                logger.debug(f"获取{code}主要财务指标失败: {e}")

            # 2. 获取资产负债表（尝试多个接口和参数）
            try:
                def fetch_balance_sheet():
                    # 尝试1: 新版接口（需要带 SH/SZ 前缀的代码）
                    try:
                        return self.ak.stock_balance_sheet_by_report_em(symbol=code_shsz)
                    except (AttributeError, TypeError, KeyError) as e:
                        logger.debug(f"新版资产负债表接口失败: {e}")
                        pass

                    # 尝试2: 旧版接口（注意：这个接口需要 date 参数，不是股票代码）
                    # 旧版接口是获取全市场数据，不适合查询单个股票
                    # 这里跳过旧版接口，直接返回 None
                    return None

                balance_sheet = await asyncio.to_thread(fetch_balance_sheet)
                if balance_sheet is not None and not balance_sheet.empty:
                    financial_data['balance_sheet'] = balance_sheet.to_dict('records')
                    logger.debug(f"✅ {code}资产负债表获取成功")
            except Exception as e:
                logger.debug(f"获取{code}资产负债表失败: {e}")

            # 3. 获取利润表（尝试多个接口和参数）
            try:
                def fetch_income_statement():
                    # 尝试1: 新版接口（需要带 SH/SZ 前缀的代码）
                    try:
                        return self.ak.stock_profit_sheet_by_report_em(symbol=code_shsz)
                    except (AttributeError, TypeError, KeyError) as e:
                        logger.debug(f"新版利润表接口失败: {e}")
                        pass

                    # 尝试2: 旧版接口（使用 stock 参数）
                    try:
                        return self.ak.stock_lrb_em(stock=code_6digit)
                    except (AttributeError, TypeError):
                        pass

                    # 尝试3: 旧版接口（位置参数）
                    try:
                        return self.ak.stock_lrb_em(code_6digit)
                    except:
                        return None

                income_statement = await asyncio.to_thread(fetch_income_statement)
                if income_statement is not None and not income_statement.empty:
                    financial_data['income_statement'] = income_statement.to_dict('records')
                    logger.debug(f"✅ {code}利润表获取成功")
            except Exception as e:
                logger.debug(f"获取{code}利润表失败: {e}")

            # 4. 获取现金流量表（尝试多个接口和参数）
            try:
                def fetch_cash_flow():
                    # 尝试1: 新版接口（需要带 SH/SZ 前缀的代码）
                    try:
                        return self.ak.stock_cash_flow_sheet_by_report_em(symbol=code_shsz)
                    except (AttributeError, TypeError, KeyError) as e:
                        logger.debug(f"新版现金流量表接口失败: {e}")
                        pass

                    # 尝试2: 旧版接口（使用 stock 参数）
                    try:
                        return self.ak.stock_xjllb_em(stock=code_6digit)
                    except (AttributeError, TypeError):
                        pass

                    # 尝试3: 旧版接口（位置参数）
                    try:
                        return self.ak.stock_xjllb_em(code_6digit)
                    except:
                        return None

                cash_flow = await asyncio.to_thread(fetch_cash_flow)
                if cash_flow is not None and not cash_flow.empty:
                    financial_data['cash_flow'] = cash_flow.to_dict('records')
                    logger.debug(f"✅ {code}现金流量表获取成功")
            except Exception as e:
                logger.debug(f"获取{code}现金流量表失败: {e}")

            if financial_data:
                logger.debug(f"✅ {code}财务数据获取完成: {len(financial_data)}个数据集")
            else:
                logger.warning(f"⚠️ {code}未获取到任何财务数据")

            return financial_data

        except Exception as e:
            logger.error(f"❌ 获取{code}财务数据失败: {e}")
            return {}

    async def get_market_status(self) -> Dict[str, Any]:
        """
        获取市场状态信息

        Returns:
            市场状态信息
        """
        try:
            # AKShare没有直接的市场状态API，返回基本信息
            now = now_utc()

            # 简单的交易时间判断
            is_trading_time = (
                now.weekday() < 5 and  # 工作日
                ((9 <= now.hour < 12) or (13 <= now.hour < 15))  # 交易时间
            )

            return {
                "market_status": "open" if is_trading_time else "closed",
                "current_time": now.isoformat(),
                "data_source": "akshare",
                "trading_day": now.weekday() < 5
            }

        except Exception as e:
            logger.error(f"❌ 获取市场状态失败: {e}")
            return {
                "market_status": "unknown",
                "current_time": format_iso(now_utc()),
                "data_source": "akshare",
                "error": str(e)
            }

    def get_stock_news_sync(self, symbol: str = None, limit: int = 10) -> Optional[pd.DataFrame]:
        """
        获取股票新闻（同步版本，返回原始 DataFrame）

        Args:
            symbol: 股票代码，为None时获取市场新闻
            limit: 返回数量限制

        Returns:
            新闻 DataFrame 或 None
        """
        if not self.is_available():
            return None

        try:
            import akshare as ak
            import json
            import time

            if symbol:
                # 获取个股新闻
                self.logger.debug(f"📰 获取AKShare个股新闻: {symbol}")

                # 标准化股票代码
                symbol_6 = symbol.zfill(6)

                # 获取东方财富个股新闻，添加重试机制
                max_retries = 3
                retry_delay = 1  # 秒
                news_df = None

                for attempt in range(max_retries):
                    try:
                        news_df = ak.stock_news_em(symbol=symbol_6)
                        break  # 成功则跳出重试循环
                    except json.JSONDecodeError as e:
                        if attempt < max_retries - 1:
                            self.logger.warning(f"⚠️ {symbol} 第{attempt+1}次获取新闻失败(JSON解析错误)，{retry_delay}秒后重试...")
                            time.sleep(retry_delay)
                            retry_delay *= 2  # 指数退避
                        else:
                            self.logger.error(f"❌ {symbol} 获取新闻失败(JSON解析错误): {e}")
                            return None
                    except Exception as e:
                        if attempt < max_retries - 1:
                            self.logger.warning(f"⚠️ {symbol} 第{attempt+1}次获取新闻失败: {e}，{retry_delay}秒后重试...")
                            time.sleep(retry_delay)
                            retry_delay *= 2
                        else:
                            raise

                if news_df is not None and not news_df.empty:
                    self.logger.info(f"✅ {symbol} AKShare新闻获取成功: {len(news_df)} 条")
                    return news_df.head(limit) if limit else news_df
                else:
                    self.logger.warning(f"⚠️ {symbol} 未获取到AKShare新闻数据")
                    return None
            else:
                # 获取市场新闻
                self.logger.debug("📰 获取AKShare市场新闻")
                news_df = ak.news_cctv()

                if news_df is not None and not news_df.empty:
                    self.logger.info(f"✅ AKShare市场新闻获取成功: {len(news_df)} 条")
                    return news_df.head(limit) if limit else news_df
                else:
                    self.logger.warning("⚠️ 未获取到AKShare市场新闻数据")
                    return None

        except Exception as e:
            self.logger.error(f"❌ AKShare新闻获取失败: {e}")
            return None

    async def get_stock_news(self, symbol: str = None, limit: int = 10) -> Optional[List[Dict[str, Any]]]:
        """
        获取股票新闻（异步版本，返回结构化列表）

        Args:
            symbol: 股票代码，为None时获取市场新闻
            limit: 返回数量限制

        Returns:
            新闻列表
        """
        if not self.is_available():
            return None

        try:
            import akshare as ak
            import json
            import os

            if symbol:
                # 获取个股新闻
                self.logger.debug(f"📰 获取AKShare个股新闻: {symbol}")

                # 标准化股票代码
                symbol_6 = symbol.zfill(6)

                # 检测是否在 Docker 环境中
                is_docker = os.path.exists('/.dockerenv') or os.environ.get('DOCKER_CONTAINER') == 'true'

                # 获取东方财富个股新闻，添加重试机制
                max_retries = 3
                retry_delay = 1  # 秒
                news_df = None

                # 如果在 Docker 环境中，尝试使用 curl_cffi 直接调用 API
                if is_docker:
                    try:
                        from curl_cffi import requests as curl_requests
                        self.logger.debug(f"🐳 检测到 Docker 环境，使用 curl_cffi 直接调用 API")
                        news_df = await asyncio.to_thread(
                            self._get_stock_news_direct,
                            symbol=symbol_6,
                            limit=limit
                        )
                        if news_df is not None and not news_df.empty:
                            self.logger.info(f"✅ {symbol} Docker 环境直接调用 API 成功")
                        else:
                            self.logger.warning(f"⚠️ {symbol} Docker 环境直接调用 API 失败，回退到 AKShare")
                            news_df = None  # 回退到 AKShare
                    except ImportError:
                        self.logger.warning(f"⚠️ curl_cffi 未安装，回退到 AKShare")
                        news_df = None
                    except Exception as e:
                        self.logger.warning(f"⚠️ {symbol} Docker 环境直接调用 API 异常: {e}，回退到 AKShare")
                        news_df = None

                # 如果直接调用失败或不在 Docker 环境，使用 AKShare
                if news_df is None:
                    for attempt in range(max_retries):
                        try:
                            news_df = await asyncio.to_thread(
                                ak.stock_news_em,
                                symbol=symbol_6
                            )
                            break  # 成功则跳出重试循环
                        except json.JSONDecodeError as e:
                            if attempt < max_retries - 1:
                                self.logger.warning(f"⚠️ {symbol} 第{attempt+1}次获取新闻失败(JSON解析错误)，{retry_delay}秒后重试...")
                                await asyncio.sleep(retry_delay)
                                retry_delay *= 2  # 指数退避
                            else:
                                self.logger.error(f"❌ {symbol} 获取新闻失败(JSON解析错误): {e}")
                                return []
                        except KeyError as e:
                            # 东方财富网接口变更或反爬虫拦截，返回的字段结构改变
                            if str(e) == "'cmsArticleWebOld'":
                                self.logger.error(f"❌ {symbol} AKShare新闻接口返回数据结构异常: 缺少 'cmsArticleWebOld' 字段")
                                self.logger.error(f"   这通常是因为：1) 反爬虫拦截 2) 接口变更 3) 网络问题")
                                self.logger.error(f"   建议：检查 AKShare 版本是否为最新 (当前要求 >=1.17.86)")
                                # 返回空列表，避免程序崩溃
                                return []
                            else:
                                if attempt < max_retries - 1:
                                    self.logger.warning(f"⚠️ {symbol} 第{attempt+1}次获取新闻失败(字段错误): {e}，{retry_delay}秒后重试...")
                                    await asyncio.sleep(retry_delay)
                                    retry_delay *= 2
                                else:
                                    self.logger.error(f"❌ {symbol} 获取新闻失败(字段错误): {e}")
                                    return []
                        except Exception as e:
                            if attempt < max_retries - 1:
                                self.logger.warning(f"⚠️ {symbol} 第{attempt+1}次获取新闻失败: {e}，{retry_delay}秒后重试...")
                                await asyncio.sleep(retry_delay)
                                retry_delay *= 2
                            else:
                                raise

                if news_df is not None and not news_df.empty:
                    news_list = []

                    for _, row in news_df.head(limit).iterrows():
                        title = str(row.get('新闻标题', '') or row.get('标题', ''))
                        content = str(row.get('新闻内容', '') or row.get('内容', ''))
                        summary = str(row.get('新闻摘要', '') or row.get('摘要', ''))

                        news_item = {
                            "symbol": symbol,
                            "title": title,
                            "content": content,
                            "summary": summary,
                            "url": str(row.get('新闻链接', '') or row.get('链接', '')),
                            "source": str(row.get('文章来源', '') or row.get('来源', '') or '东方财富'),
                            "author": str(row.get('作者', '') or ''),
                            "publish_time": self._parse_news_time(row.get('发布时间', '') or row.get('时间', '')),
                            "category": self._classify_news(content, title),
                            "sentiment": self._analyze_news_sentiment(content, title),
                            "sentiment_score": self._calculate_sentiment_score(content, title),
                            "keywords": self._extract_keywords(content, title),
                            "importance": self._assess_news_importance(content, title),
                            "data_source": "akshare"
                        }

                        # 过滤空标题的新闻
                        if news_item["title"]:
                            news_list.append(news_item)

                    self.logger.info(f"✅ {symbol} AKShare新闻获取成功: {len(news_list)} 条")
                    return news_list
                else:
                    self.logger.warning(f"⚠️ {symbol} 未获取到AKShare新闻数据")
                    return []
            else:
                # 获取市场新闻
                self.logger.debug("📰 获取AKShare市场新闻")

                try:
                    # 获取财经新闻
                    news_df = await asyncio.to_thread(
                        ak.news_cctv,
                        limit=limit
                    )

                    if news_df is not None and not news_df.empty:
                        news_list = []

                        for _, row in news_df.iterrows():
                            title = str(row.get('title', '') or row.get('标题', ''))
                            content = str(row.get('content', '') or row.get('内容', ''))
                            summary = str(row.get('brief', '') or row.get('摘要', ''))

                            news_item = {
                                "title": title,
                                "content": content,
                                "summary": summary,
                                "url": str(row.get('url', '') or row.get('链接', '')),
                                "source": str(row.get('source', '') or row.get('来源', '') or 'CCTV财经'),
                                "author": str(row.get('author', '') or ''),
                                "publish_time": self._parse_news_time(row.get('time', '') or row.get('时间', '')),
                                "category": self._classify_news(content, title),
                                "sentiment": self._analyze_news_sentiment(content, title),
                                "sentiment_score": self._calculate_sentiment_score(content, title),
                                "keywords": self._extract_keywords(content, title),
                                "importance": self._assess_news_importance(content, title),
                                "data_source": "akshare"
                            }

                            if news_item["title"]:
                                news_list.append(news_item)

                        self.logger.info(f"✅ AKShare市场新闻获取成功: {len(news_list)} 条")
                        return news_list

                except Exception as e:
                    self.logger.debug(f"CCTV新闻获取失败: {e}")

                return []

        except Exception as e:
            self.logger.error(f"❌ 获取AKShare新闻失败 symbol={symbol}: {e}")
            return None

    def _parse_news_time(self, time_str: str) -> Optional[datetime]:
        """解析新闻时间"""
        if not time_str:
            return now_utc()

        try:
            # 尝试多种时间格式
            formats = [
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%Y-%m-%d",
                "%Y/%m/%d %H:%M:%S",
                "%Y/%m/%d %H:%M",
                "%Y/%m/%d",
                "%m-%d %H:%M",
                "%m/%d %H:%M"
            ]

            for fmt in formats:
                try:
                    parsed_time = datetime.strptime(str(time_str), fmt)

                    # 如果只有月日，补充年份
                    if fmt in ["%m-%d %H:%M", "%m/%d %H:%M"]:
                        current_year = now_utc().year
                        parsed_time = parsed_time.replace(year=current_year)

                    return parsed_time
                except ValueError:
                    continue

            # 如果都失败了，返回当前时间
            self.logger.debug(f"⚠️ 无法解析新闻时间: {time_str}")
            return now_utc()

        except Exception as e:
            self.logger.debug(f"解析新闻时间异常: {e}")
            return now_utc()

    def _analyze_news_sentiment(self, content: str, title: str) -> str:
        """
        分析新闻情绪

        Args:
            content: 新闻内容
            title: 新闻标题

        Returns:
            情绪类型: positive/negative/neutral
        """
        text = f"{title} {content}".lower()

        # 积极关键词
        positive_keywords = [
            '利好', '上涨', '增长', '盈利', '突破', '创新高', '买入', '推荐',
            '看好', '乐观', '强势', '大涨', '飙升', '暴涨', '涨停', '涨幅',
            '业绩增长', '营收增长', '净利润增长', '扭亏为盈', '超预期',
            '获批', '中标', '签约', '合作', '并购', '重组', '分红', '回购'
        ]

        # 消极关键词
        negative_keywords = [
            '利空', '下跌', '亏损', '风险', '暴跌', '卖出', '警告', '下调',
            '看空', '悲观', '弱势', '大跌', '跳水', '暴跌', '跌停', '跌幅',
            '业绩下滑', '营收下降', '净利润下降', '亏损', '低于预期',
            '被查', '违规', '处罚', '诉讼', '退市', '停牌', '商誉减值'
        ]

        positive_count = sum(1 for keyword in positive_keywords if keyword in text)
        negative_count = sum(1 for keyword in negative_keywords if keyword in text)

        if positive_count > negative_count:
            return 'positive'
        elif negative_count > positive_count:
            return 'negative'
        else:
            return 'neutral'

    def _calculate_sentiment_score(self, content: str, title: str) -> float:
        """
        计算情绪分数

        Args:
            content: 新闻内容
            title: 新闻标题

        Returns:
            情绪分数: -1.0 到 1.0
        """
        text = f"{title} {content}".lower()

        # 积极关键词权重
        positive_keywords = {
            '涨停': 1.0, '暴涨': 0.9, '大涨': 0.8, '飙升': 0.8,
            '创新高': 0.7, '突破': 0.6, '上涨': 0.5, '增长': 0.4,
            '利好': 0.6, '看好': 0.5, '推荐': 0.5, '买入': 0.6
        }

        # 消极关键词权重
        negative_keywords = {
            '跌停': -1.0, '暴跌': -0.9, '大跌': -0.8, '跳水': -0.8,
            '创新低': -0.7, '破位': -0.6, '下跌': -0.5, '下滑': -0.4,
            '利空': -0.6, '看空': -0.5, '卖出': -0.6, '警告': -0.5
        }

        score = 0.0

        # 计算积极分数
        for keyword, weight in positive_keywords.items():
            if keyword in text:
                score += weight

        # 计算消极分数
        for keyword, weight in negative_keywords.items():
            if keyword in text:
                score += weight

        # 归一化到 [-1.0, 1.0]
        return max(-1.0, min(1.0, score / 3.0))

    def _extract_keywords(self, content: str, title: str) -> List[str]:
        """
        提取关键词

        Args:
            content: 新闻内容
            title: 新闻标题

        Returns:
            关键词列表
        """
        text = f"{title} {content}"

        # 常见财经关键词
        common_keywords = [
            '股票', '公司', '市场', '投资', '业绩', '财报', '政策', '行业',
            '分析', '预测', '涨停', '跌停', '上涨', '下跌', '盈利', '亏损',
            '并购', '重组', '分红', '回购', '增持', '减持', '融资', 'IPO',
            '监管', '央行', '利率', '汇率', 'GDP', '通胀', '经济', '贸易',
            '科技', '互联网', '新能源', '医药', '房地产', '金融', '制造业'
        ]

        keywords = []
        for keyword in common_keywords:
            if keyword in text:
                keywords.append(keyword)

        return keywords[:10]  # 最多返回10个关键词

    def _assess_news_importance(self, content: str, title: str) -> str:
        """
        评估新闻重要性

        Args:
            content: 新闻内容
            title: 新闻标题

        Returns:
            重要性级别: high/medium/low
        """
        text = f"{title} {content}".lower()

        # 高重要性关键词
        high_importance_keywords = [
            '业绩', '财报', '年报', '季报', '重大', '公告', '监管', '政策',
            '并购', '重组', '退市', '停牌', '涨停', '跌停', '暴涨', '暴跌',
            '央行', '证监会', '交易所', '违规', '处罚', '立案', '调查'
        ]

        # 中等重要性关键词
        medium_importance_keywords = [
            '分析', '预测', '观点', '建议', '行业', '市场', '趋势', '机会',
            '研报', '评级', '目标价', '增持', '减持', '买入', '卖出',
            '合作', '签约', '中标', '获批', '分红', '回购'
        ]

        # 检查高重要性
        if any(keyword in text for keyword in high_importance_keywords):
            return 'high'

        # 检查中等重要性
        if any(keyword in text for keyword in medium_importance_keywords):
            return 'medium'

        return 'low'

    def _classify_news(self, content: str, title: str) -> str:
        """
        分类新闻

        Args:
            content: 新闻内容
            title: 新闻标题

        Returns:
            新闻类别
        """
        text = f"{title} {content}".lower()

        # 公司公告
        if any(keyword in text for keyword in ['公告', '业绩', '财报', '年报', '季报']):
            return 'company_announcement'

        # 政策新闻
        if any(keyword in text for keyword in ['政策', '监管', '央行', '证监会', '国务院']):
            return 'policy_news'

        # 行业新闻
        if any(keyword in text for keyword in ['行业', '板块', '产业', '领域']):
            return 'industry_news'

        # 市场新闻
        if any(keyword in text for keyword in ['市场', '指数', '大盘', '沪指', '深成指']):
            return 'market_news'

        # 研究报告
        if any(keyword in text for keyword in ['研报', '分析', '评级', '目标价', '机构']):
            return 'research_report'

        return 'general'


# 全局提供器实例
_akshare_provider = None


def get_akshare_provider() -> AKShareProvider:
    """获取全局AKShare提供器实例"""
    global _akshare_provider
    if _akshare_provider is None:
        _akshare_provider = AKShareProvider()
    return _akshare_provider
