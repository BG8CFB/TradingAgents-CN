"""A 股调度任务注册。"""

from app.data.scheduler.jobs.base.sync_job import BaseSyncJob


class CNTradeCalendarJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "trade_calendar")
    def get_cron(self) -> str:
        return "0 0 * * *"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNBasicInfoJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "basic_info")
    def get_cron(self) -> str:
        return "0 9 * * *"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNDailyQuotesJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "daily_quotes")
    def get_cron(self) -> str:
        return "15 16 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNDailyIndicatorsJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "daily_indicators")
    def get_cron(self) -> str:
        return "45 16 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNAdjFactorsJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "adj_factors")
    def get_cron(self) -> str:
        return "0 17 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNFinancialDataJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "financial_data")
    def get_cron(self) -> str:
        return "0 20 * * *"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNMarketQuotesJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "market_quotes")
    def get_cron(self) -> str:
        return "5 15 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNNewsJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "news")
    def get_cron(self) -> str:
        return "0 */2 * * *"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNIntradayQuotesJob(BaseSyncJob):
    """分钟级行情同步 — 仅同步热门标的或按需触发。"""
    def __init__(self):
        super().__init__("CN", "intraday_quotes")
        self.force_sync = True
    def get_cron(self) -> str:
        return "*/30 9-14 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNMoneyFlowJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "money_flow")
    def get_cron(self) -> str:
        return "30 16 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNMarginTradingJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "margin_trading")
    def get_cron(self) -> str:
        return "0 17 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNDragonTigerJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "dragon_tiger")
    def get_cron(self) -> str:
        return "0 18 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNBlockTradeJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "block_trade")
    def get_cron(self) -> str:
        return "30 18 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


_CN_JOBS = [
    CNTradeCalendarJob,
    CNBasicInfoJob,
    CNDailyQuotesJob,
    CNDailyIndicatorsJob,
    CNAdjFactorsJob,
    CNFinancialDataJob,
    CNMarketQuotesJob,
    CNNewsJob,
    CNIntradayQuotesJob,
    CNMoneyFlowJob,
    CNMarginTradingJob,
    CNDragonTigerJob,
    CNBlockTradeJob,
]


def register_cn_jobs(registry) -> None:
    for job_cls in _CN_JOBS:
        job = job_cls()
        registry.register(job.domain, "CN", job_cls)
