"""数据源异常类。"""

from app.data.sources.base.error_codes import DataErrorCode


class DataSourceError(Exception):
    """数据源错误基类。"""

    def __init__(self, code: DataErrorCode, source: str, domain: str, message: str = ""):
        self.code = code
        self.source = source
        self.domain = domain
        self.message = message or f"[{source}/{domain}] {code.value}"
        super().__init__(self.message)


class DataSourceUnavailableError(DataSourceError):
    """数据源暂时不可用（HTTP 5xx / 上游故障 / 未知异常）。

    与 NETWORK_TIMEOUT / CONNECTION_ERROR 区分：
    - 前两者是网络层（超时/TCP 断连），通常是瞬态的
    - SERVICE_UNAVAILABLE 通常指上游服务故障，需要稍长退避重试
    """

    def __init__(self, source: str, domain: str, message: str = ""):
        super().__init__(
            DataErrorCode.SERVICE_UNAVAILABLE,
            source,
            domain,
            message or f"{source} 暂时不可用",
        )


class RateLimitedError(DataSourceError):
    def __init__(self, source: str, domain: str, message: str = "", retry_after: int = 0):
        self.retry_after = retry_after
        super().__init__(DataErrorCode.RATE_LIMITED, source, domain, message or f"{source} 被限流")


class TokenInvalidError(DataSourceError):
    def __init__(self, source: str, domain: str, message: str = ""):
        super().__init__(DataErrorCode.TOKEN_INVALID, source, domain, message or f"{source} Token 失效")


class InsufficientCreditsError(DataSourceError):
    def __init__(self, source: str, domain: str, message: str = "", required: int = 0):
        self.required = required
        super().__init__(DataErrorCode.INSUFFICIENT_CREDITS, source, domain, message or f"{source} 积分不足")


class SymbolNotFoundError(DataSourceError):
    def __init__(self, source: str, symbol: str, message: str = ""):
        self.symbol = symbol
        super().__init__(DataErrorCode.SYMBOL_NOT_FOUND, source, "", message or f"{symbol} 不存在于 {source}")


class DataFormatError(DataSourceError):
    def __init__(self, source: str, domain: str, message: str = ""):
        super().__init__(DataErrorCode.DATA_INVALID, source, domain, message or f"{source}/{domain} 数据格式异常")


class NetworkError(DataSourceError):
    """网络层异常：超时、连接断开等。

    可重试（与 token 失效、限流等业务异常区分开）。
    """

    def __init__(self, source: str, domain: str, message: str = ""):
        super().__init__(DataErrorCode.NETWORK_TIMEOUT, source, domain, message or f"{source}/{domain} 网络异常")


class DataNotFoundError(DataSourceError):
    """数据为空异常：源返回空结果但未报错。

    不可重试（业务正确但无数据）。
    """

    def __init__(self, source: str, domain: str, message: str = ""):
        super().__init__(DataErrorCode.EMPTY_RESULT, source, domain, message or f"{source}/{domain} 无数据")
