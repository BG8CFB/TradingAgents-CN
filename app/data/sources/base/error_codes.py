"""数据源错误码定义。"""

from enum import Enum


class DataErrorCode(str, Enum):
    RATE_LIMITED = "rate_limited"            # 429 限流
    AUTH_FAILED = "auth_failed"              # 401/403 权限不足
    TOKEN_INVALID = "token_invalid"          # Token 失效
    INSUFFICIENT_CREDITS = "insufficient_credits"  # 积分不足
    NETWORK_TIMEOUT = "network_timeout"      # 网络超时
    CONNECTION_ERROR = "connection_error"     # 连接断开
    SERVER_ERROR = "server_error"            # 500 服务器错误
    DATA_INVALID = "data_invalid"            # 数据格式异常
    EMPTY_RESULT = "empty_result"            # 空结果（应有数据）
    SYMBOL_NOT_FOUND = "symbol_not_found"    # 股票代码不存在
    NOT_SUPPORTED = "not_supported"          # 数据源不支持该域
    UNKNOWN = "unknown"
