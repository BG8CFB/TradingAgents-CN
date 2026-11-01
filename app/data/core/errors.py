"""数据层公开异常类型（契约的一部分：消费方可捕获做降级）。"""


class DataUnavailableError(RuntimeError):
    """存储/上游故障导致数据无法读取（区别于「无数据」——那是正常空结果）。

    携带 market/domain 便于工具层生成定向的修复提示文案。
    """

    def __init__(self, market: str, domain: str, cause=None):
        self.market = market
        self.domain = domain
        self.cause = cause
        super().__init__(
            f"数据不可用: {market}/{domain}"
            + (f"（原因: {cause}）" if cause else "")
        )
