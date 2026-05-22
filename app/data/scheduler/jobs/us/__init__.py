"""美股调度任务注册。"""

from app.data.scheduler.jobs.base.sync_job import BaseSyncJob


class USTradeCalendarJob(BaseSyncJob):
    def __init__(self):
        super().__init__("US", "trade_calendar")
    def get_cron(self) -> str:
        return "0 0 * * *"
    def get_timezone(self) -> str:
        return "America/New_York"


class USBasicInfoJob(BaseSyncJob):
    def __init__(self):
        super().__init__("US", "basic_info")
    def get_cron(self) -> str:
        return "0 6 * * *"
    def get_timezone(self) -> str:
        return "America/New_York"


class USTushareUniverseJob(BaseSyncJob):
    def __init__(self):
        super().__init__("US", "tushare_universe")
    def get_cron(self) -> str:
        return "30 6 * * 1"
    def get_timezone(self) -> str:
        return "America/New_York"


class USCorporateActionsJob(BaseSyncJob):
    def __init__(self):
        super().__init__("US", "corporate_actions")
    def get_cron(self) -> str:
        return "0 18 * * *"
    def get_timezone(self) -> str:
        return "America/New_York"


class USDailyQuotesJob(BaseSyncJob):
    def __init__(self):
        super().__init__("US", "daily_quotes")
    def get_cron(self) -> str:
        return "30 16 * * 1-5"
    def get_timezone(self) -> str:
        return "America/New_York"


class USDailyIndicatorsJob(BaseSyncJob):
    def __init__(self):
        super().__init__("US", "daily_indicators")
    def get_cron(self) -> str:
        return "30 17 * * 1-5"
    def get_timezone(self) -> str:
        return "America/New_York"


class USAdjFactorsJob(BaseSyncJob):
    def __init__(self):
        super().__init__("US", "adj_factors")
    def get_cron(self) -> str:
        return "30 18 * * 1-5"
    def get_timezone(self) -> str:
        return "America/New_York"


class USFinancialDataJob(BaseSyncJob):
    def __init__(self):
        super().__init__("US", "financial_data")
    def get_cron(self) -> str:
        return "0 21 * * *"
    def get_timezone(self) -> str:
        return "America/New_York"


class USMarketQuotesJob(BaseSyncJob):
    def __init__(self):
        super().__init__("US", "market_quotes")
    def get_cron(self) -> str:
        return "1 16 * * 1-5"
    def get_timezone(self) -> str:
        return "America/New_York"


class USPrePostMarketJob(BaseSyncJob):
    def __init__(self):
        super().__init__("US", "pre_post_market")
    def get_cron(self) -> str:
        return "*/5 4-20 * * 1-5"
    def get_timezone(self) -> str:
        return "America/New_York"


class USNewsJob(BaseSyncJob):
    def __init__(self):
        super().__init__("US", "news")
    def get_cron(self) -> str:
        return "0 */1 * * *"
    def get_timezone(self) -> str:
        return "America/New_York"


_US_JOBS = [
    USTradeCalendarJob,
    USBasicInfoJob,
    USTushareUniverseJob,
    USCorporateActionsJob,
    USDailyQuotesJob,
    USDailyIndicatorsJob,
    USAdjFactorsJob,
    USFinancialDataJob,
    USMarketQuotesJob,
    USPrePostMarketJob,
    USNewsJob,
]


def register_us_jobs(registry) -> None:
    for job_cls in _US_JOBS:
        job = job_cls()
        registry.register(job.domain, "US", job_cls)
