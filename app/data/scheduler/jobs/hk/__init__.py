"""港股调度任务注册。"""

from app.data.scheduler.jobs.base.sync_job import BaseSyncJob


class HKTradeCalendarJob(BaseSyncJob):
    def __init__(self):
        super().__init__("HK", "trade_calendar")
    def get_cron(self) -> str:
        return "0 0 * * *"
    def get_timezone(self) -> str:
        return "Asia/Hong_Kong"


class HKBasicInfoJob(BaseSyncJob):
    def __init__(self):
        super().__init__("HK", "basic_info")
    def get_cron(self) -> str:
        return "0 8 * * *"
    def get_timezone(self) -> str:
        return "Asia/Hong_Kong"


class HKConnectStatusJob(BaseSyncJob):
    def __init__(self):
        super().__init__("HK", "connect_status")
    def get_cron(self) -> str:
        return "0 9 * * 1"
    def get_timezone(self) -> str:
        return "Asia/Hong_Kong"


class HKDailyQuotesJob(BaseSyncJob):
    def __init__(self):
        super().__init__("HK", "daily_quotes")
    def get_cron(self) -> str:
        return "30 18 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Hong_Kong"


class HKDailyIndicatorsJob(BaseSyncJob):
    def __init__(self):
        super().__init__("HK", "daily_indicators")
    def get_cron(self) -> str:
        return "0 19 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Hong_Kong"


class HKSouthboundHoldingJob(BaseSyncJob):
    def __init__(self):
        super().__init__("HK", "southbound_holding")
    def get_cron(self) -> str:
        return "30 19 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Hong_Kong"


class HKCorporateActionsJob(BaseSyncJob):
    def __init__(self):
        super().__init__("HK", "corporate_actions")
    def get_cron(self) -> str:
        return "0 20 * * *"
    def get_timezone(self) -> str:
        return "Asia/Hong_Kong"


class HKAdjFactorsJob(BaseSyncJob):
    def __init__(self):
        super().__init__("HK", "adj_factors")
    def get_cron(self) -> str:
        return "30 19 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Hong_Kong"


class HKFinancialDataJob(BaseSyncJob):
    def __init__(self):
        super().__init__("HK", "financial_data")
    def get_cron(self) -> str:
        return "0 21 * * *"
    def get_timezone(self) -> str:
        return "Asia/Hong_Kong"


class HKMarketQuotesJob(BaseSyncJob):
    def __init__(self):
        super().__init__("HK", "market_quotes")
    def get_cron(self) -> str:
        return "1 16 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Hong_Kong"


class HKNewsJob(BaseSyncJob):
    def __init__(self):
        super().__init__("HK", "news")
    def get_cron(self) -> str:
        return "0 */1 * * *"
    def get_timezone(self) -> str:
        return "Asia/Hong_Kong"


_HK_JOBS = [
    HKTradeCalendarJob,
    HKBasicInfoJob,
    HKConnectStatusJob,
    HKDailyQuotesJob,
    HKDailyIndicatorsJob,
    HKSouthboundHoldingJob,
    HKCorporateActionsJob,
    HKAdjFactorsJob,
    HKFinancialDataJob,
    HKMarketQuotesJob,
    HKNewsJob,
]


def register_hk_jobs(registry) -> None:
    for job_cls in _HK_JOBS:
        job = job_cls()
        registry.register(job.domain, "HK", job_cls)
