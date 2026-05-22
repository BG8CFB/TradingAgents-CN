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
    def __init__(self, source: str, domain: str, message: str = ""):
        super().__init__(DataErrorCode.CONNECTION_ERROR, source, domain, message or f"{source} 不可用")


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
