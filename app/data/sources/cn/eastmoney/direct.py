"""
反爬虫工具模块

提供统一的反爬虫策略：
- TLS 指纹模拟（curl_cffi）
- User-Agent 轮换
- 线程安全限流器
- 请求会话复用
- 直接 API 调用（绕过 AKShare）
"""
import logging
import random
import threading
import time
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

# 现代 User-Agent 池（Chrome 130+ 系列浏览器）
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
]

# curl_cffi 支持的最新 Chrome 指纹版本（按优先级排列）
CURL_IMPERSONATE_TARGETS = ["chrome146", "chrome145", "chrome142", "chrome136", "chrome133a"]

# 东方财富 API 公共请求头
EASTMONEY_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "Sec-Ch-Ua": '"Chromium";v="136", "Google Chrome";v="136", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
}


def get_random_ua() -> str:
    return random.choice(USER_AGENTS)


class ThreadSafeRateLimiter:
    """令牌桶限流器，线程安全"""

    def __init__(self, min_interval: float = 0.3, burst: int = 3):
        self._min_interval = min_interval
        self._burst = burst
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self):
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._burst, self._tokens + elapsed / self._min_interval)
            self._last_refill = now

            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return

            wait = self._min_interval * (1.0 - self._tokens)
            self._tokens = 0.0

        time.sleep(wait + random.uniform(0, 0.15))


# 全局限流器实例（针对东方财富 API）
_em_rate_limiter = ThreadSafeRateLimiter(min_interval=0.3, burst=3)


def get_em_rate_limiter() -> ThreadSafeRateLimiter:
    return _em_rate_limiter


class AntiScrapingSession:
    """
    统一的 HTTP 会话管理器，优先使用 curl_cffi 模拟真实浏览器指纹。
    自动降级到标准 requests。
    """

    def __init__(self):
        self._curl_session = None
        self._curl_available = False
        self._impersonate_target = None
        self._init_curl_cffi()

    def _init_curl_cffi(self):
        try:
            from curl_cffi import requests as curl_requests

            # 找到可用的最新指纹版本
            available = [x for x in dir(curl_requests.Session) if not x.startswith("_")]
            for target in CURL_IMPERSONATE_TARGETS:
                if target in available:  # curl_cffi 用字符串匹配
                    try:
                        session = curl_requests.Session(impersonate=target)
                        self._curl_session = session
                        self._curl_available = True
                        self._impersonate_target = target
                        logger.info(f"curl_cffi 会话初始化成功，指纹: {target}")
                        return
                    except Exception as e:
                        logger.debug(f"curl_cffi指纹 {target} 初始化失败: {e}")
                        continue

            logger.warning("curl_cffi 初始化失败，回退到标准 requests")
        except ImportError:
            logger.warning(
                "curl_cffi 未安装，将使用标准 requests（反爬能力受限）\n"
                "  建议: pip install curl-cffi>=0.6.0"
            )

    @property
    def is_curl_available(self) -> bool:
        return self._curl_available

    @property
    def impersonate_target(self) -> Optional[str]:
        return self._impersonate_target

    def get(self, url: str, **kwargs) -> Any:
        """发送 GET 请求，优先使用 curl_cffi"""
        headers = kwargs.pop("headers", {}) or {}
        headers.setdefault("User-Agent", get_random_ua())
        kwargs["headers"] = headers

        if "timeout" not in kwargs:
            kwargs["timeout"] = 30

        if self._curl_available:
            try:
                return self._curl_session.get(url, **kwargs)
            except Exception as e:
                logger.debug(f"curl_cffi 请求失败，回退到 requests: {e}")

        import requests

        return requests.get(url, **kwargs)


# 全局会话实例
_session: Optional[AntiScrapingSession] = None
_session_lock = threading.Lock()


def get_anti_scraping_session() -> AntiScrapingSession:
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                _session = AntiScrapingSession()
    return _session


# ============================================================
# 东方财富直接 API 调用（绕过 AKShare，最有效的反爬手段）
# ============================================================

def _build_em_params(fields: str, extra: Optional[Dict] = None) -> Dict[str, Any]:
    """构建东方财富 API 的公共参数"""
    params = {
        "pn": "1",
        "pz": "5000",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "wbp2u": "|0|0|0|web",
        "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
        "fields": fields,
    }
    if extra:
        params.update(extra)
    return params


def fetch_em_spot_direct() -> Optional[Any]:
    """
    直接调用东方财富全市场快照 API，绕过 AKShare。
    使用 HTTP 协议绕过 TLS 指纹检测。
    返回解析后的 JSON 数据列表。
    """
    import json

    session = get_anti_scraping_session()
    limiter = get_em_rate_limiter()

    # push2 已被 CDN 封锁，使用 push2delay 替代
    url = "https://push2delay.eastmoney.com/api/qt/clist/get"
    fields = "f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f26,f22,f11,f62,f128,f136,f115,f152"
    params = _build_em_params(fields)

    headers = {
        "User-Agent": get_random_ua(),
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://quote.eastmoney.com/",
    }

    for attempt in range(3):
        try:
            limiter.acquire()
            resp = session.get(url, params=params, headers=headers, timeout=15)

            if resp.status_code != 200:
                logger.warning(f"东方财富快照 API 返回 {resp.status_code}（尝试 {attempt + 1}/3）")
                continue

            data = resp.json() if hasattr(resp, "json") else json.loads(resp.text)

            if data.get("data") and data["data"].get("diff"):
                total = data["data"].get("total", 0)
                diff = data["data"]["diff"]
                logger.info(f"东方财富快照直接 API 成功: {len(diff)} 条（总数 {total}）")
                return diff

            logger.warning(f"东方财富快照 API 返回数据异常（尝试 {attempt + 1}/3）")
        except Exception as e:
            logger.warning(f"东方财富快照直接 API 失败（尝试 {attempt + 1}/3）: {e}")

    return None


def fetch_tencent_spot_batch(codes: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    通过腾讯行情 API 批量获取实时行情。
    每次请求最多约 800 只股票（URL 长度限制），自动分批。
    速度极快（<1s），适合替代被封锁的东方财富 push2 接口。

    Args:
        codes: 6 位纯数字股票代码列表

    Returns:
        {code: {name, price, change_pct, volume, amount, open, high, low, pre_close}}
    """
    if not codes:
        return {}


    def _code_to_tencent(code: str) -> str:
        code = code.strip().zfill(6)
        if code.startswith(("6", "9")):
            return f"sh{code}"
        elif code.startswith("8") or code.startswith("4"):
            return f"bj{code}"
        else:
            return f"sz{code}"

    result: Dict[str, Dict[str, Any]] = {}

    # 分批处理（每批约 50 个代码，避免 URL 过长）
    batch_size = 50
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        tencent_codes = [_code_to_tencent(c) for c in batch]
        url = f"http://qt.gtimg.cn/q={','.join(tencent_codes)}"

        try:
            import requests as req
            resp = req.get(url, timeout=10)
            if resp.status_code != 200:
                continue

            lines = resp.text.strip().split(';')
            for line in lines:
                line = line.strip()
                if not line or '~' not in line:
                    continue
                parts = line.split('~')
                if len(parts) < 38:
                    continue

                raw_code = parts[2]
                if not raw_code:
                    continue
                code = raw_code.zfill(6)
                pre_close = _safe_float(parts[4])
                price = _safe_float(parts[3])
                change_pct = _safe_float(parts[32])
                if pre_close and price:
                    change = round(price - pre_close, 2)
                else:
                    change = 0.0

                result[code] = {
                    "name": parts[1] or f"股票{code}",
                    "price": price,
                    "pre_close": pre_close,
                    "change": change,
                    "change_pct": change_pct,
                    "volume": _safe_int(parts[6]),
                    "amount": _safe_float(parts[37]),
                    "open": _safe_float(parts[5]),
                    "high": _safe_float(parts[33]) or _safe_float(parts[3]),
                    "low": _safe_float(parts[34]) or _safe_float(parts[3]),
                    "turnover_rate": _safe_float(parts[38]) if len(parts) > 38 else None,
                    "pe": _safe_float(parts[39]) if len(parts) > 39 else None,
                }
        except Exception as e:
            logger.warning(f"腾讯行情 API 批次 {i // batch_size + 1} 失败: {e}")

    if result:
        logger.info(f"腾讯行情 API 成功: {len(result)}/{len(codes)} 只")
    return result


def _safe_float(v) -> Optional[float]:
    try:
        if v is None or v == '' or v == '-':
            return None
        return float(v)
    except (ValueError, TypeError):
        return None


def _safe_int(v) -> Optional[int]:
    try:
        if v is None or v == '' or v == '-':
            return None
        return int(float(v))
    except (ValueError, TypeError):
        return None
def fetch_em_board_direct() -> Optional[Any]:
    """
    直接调用东方财富板块行情 API。
    使用 HTTP 协议绕过 TLS 指纹检测。
    返回板块列表数据。
    """
    import json

    session = get_anti_scraping_session()
    limiter = get_em_rate_limiter()

    url = "https://push2delay.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1",
        "pz": "200",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "m:90+t:2+f:!50",
        "fields": "f2,f3,f4,f8,f12,f14",
    }

    headers = {
        "User-Agent": get_random_ua(),
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://data.eastmoney.com/",
    }

    for attempt in range(2):
        try:
            limiter.acquire()
            resp = session.get(url, params=params, headers=headers)

            if resp.status_code != 200:
                continue

            data = resp.json() if hasattr(resp, "json") else json.loads(resp.text)

            if data.get("data") and data["data"].get("diff"):
                diff = data["data"]["diff"]
                logger.info(f"东方财富板块直接 API 成功: {len(diff)} 条")
                return diff

        except Exception as e:
            logger.warning(f"东方财富板块直接 API 失败（尝试 {attempt + 1}/2）: {e}")

    return None


