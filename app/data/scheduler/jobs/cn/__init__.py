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


_CN_JOBS = [
    CNTradeCalendarJob,
    CNBasicInfoJob,
    CNDailyQuotesJob,
    CNDailyIndicatorsJob,
    CNAdjFactorsJob,
    CNFinancialDataJob,
    CNMarketQuotesJob,
    CNNewsJob,
]


def register_cn_jobs(registry) -> None:
    for job_cls in _CN_JOBS:
        job = job_cls()
        registry.register(job.domain, "CN", job_cls)
