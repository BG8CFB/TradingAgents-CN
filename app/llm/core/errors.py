"""
统一异常体系（协议无关）

各协议 client 负责把 SDK 异常翻译为本模块的异常，
消费方只需捕获本模块的异常类型。
"""


class LLMError(Exception):
    """LLM 层基础异常"""

    def __init__(self, message: str, *, protocol: str = "", status_code: int | None = None):
        super().__init__(message)
        self.protocol = protocol
        self.status_code = status_code


class AuthError(LLMError):
    """认证失败（401/403 或 key 缺失）"""


class RateLimitError(LLMError):
    """限流（429）——消费方可按需退避重试"""


class ContextWindowExceededError(LLMError):
    """上下文超长——触发压缩后重试的信号"""


class TimeoutError_(LLMError):
    """请求超时"""


class ProtocolError(LLMError):
    """协议层错误：响应不符合预期结构、消息校验失败等"""
