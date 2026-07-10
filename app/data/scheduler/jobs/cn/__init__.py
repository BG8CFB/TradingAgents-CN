"""A 股调度任务注册。

按 A 股交易时间线优化，确保分析师在每个关键时点都有最新数据。

交易时间线：
  06:00  新闻开始（每30分钟至22:00）
  08:30  盘前准备（基础信息）
  09:30  开盘（市场概览）
  10:30  盘中快照
  11:00  上午资金流向
  11:15  半日K线+指标
  12:00  北向资金午间+指数
  14:00  午后快照
  15:00  收盘（市场概览+指数+北向）
  15:15  收盘K线+指标
  16:00  停复牌+涨跌停+资金+指数
  17:00  复权因子+融资融券
  17:30  龙虎榜
  18:30  大宗交易
  19:00  北向资金（港股收盘后）
  20:00  财务数据+筹码分布
  21:00  限售解禁
  22:00  股权质押
"""

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
        return "30 8 * * *"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNDailyQuotesJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "daily_quotes")
    def get_cron(self) -> str:
        return "15 11,15 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNDailyIndicatorsJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "daily_indicators")
    def get_cron(self) -> str:
        return "20 11,15 * * 1-5"
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
        self.concurrency_override = 1
    def get_cron(self) -> str:
        return "0 20 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNMarketQuotesJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "market_quotes")
    def get_cron(self) -> str:
        return "30 9,10,14,15 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNNewsJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "news")
    def get_cron(self) -> str:
        return "*/30 6-22 * * *"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNIntradayQuotesJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "intraday_quotes")
        self.force_sync = True
    def get_cron(self) -> str:
        return "*/15 9-15 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNMoneyFlowJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "money_flow")
    def get_cron(self) -> str:
        return "0 11,14,16 * * 1-5"
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
        return "30 17,20 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNBlockTradeJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "block_trade")
    def get_cron(self) -> str:
        return "30 18 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNNorthboundFlowJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "northbound_flow")
    def get_cron(self) -> str:
        return "0 12,15,19 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNNorthboundHoldingJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "northbound_holding")
    def get_cron(self) -> str:
        return "0 19 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNShareUnlockJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "share_unlock")
    def get_cron(self) -> str:
        return "0 21 * * *"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNPledgeJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "pledge")
    def get_cron(self) -> str:
        return "0 22 * * *"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNTradingStatusJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "trading_status")
    def get_cron(self) -> str:
        return "0 16 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNPriceLimitJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "price_limit")
    def get_cron(self) -> str:
        return "10 16 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNIndexDataJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "index_data")
    def get_cron(self) -> str:
        return "0 12,15,16 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNIndexBasicJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "index_basic")
    def get_cron(self) -> str:
        return "0 2 * * *"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNIndexDailyBasicJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "index_dailybasic")
    def get_cron(self) -> str:
        return "0 12,15,16 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNIndexWeightJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "index_weight")
    def get_cron(self) -> str:
        return "0 1 * * 1"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNAnnouncementJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "announcement")
    def get_cron(self) -> str:
        return "30 2 * * *"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNIndexGlobalJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "index_global")
    def get_cron(self) -> str:
        return "0 2 * * *"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNChipDistributionJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "chip_distribution")
    def get_cron(self) -> str:
        return "0 20 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNSwDailyJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "sw_daily")
    def get_cron(self) -> str:
        return "5 16 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNThsDailyJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "ths_daily")
    def get_cron(self) -> str:
        return "10 16 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNForecastJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "forecast")
    def get_cron(self) -> str:
        return "0 18 * * *"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNExpressJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "express")
    def get_cron(self) -> str:
        return "30 18 * * *"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNLimitStepJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "limit_step")
    def get_cron(self) -> str:
        return "0 16 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNMoneyflowIndDcJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "moneyflow_ind_dc")
    def get_cron(self) -> str:
        return "0 17 * * 1-5"
    def get_timezone(self) -> str:
        return "Asia/Shanghai"


class CNDividendJob(BaseSyncJob):
    def __init__(self):
        super().__init__("CN", "dividend")
    def get_cron(self) -> str:
        return "0 19 * * *"
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
    CNNorthboundFlowJob,
    CNNorthboundHoldingJob,
    CNShareUnlockJob,
    CNPledgeJob,
    CNTradingStatusJob,
    CNPriceLimitJob,
    CNIndexDataJob,
    CNIndexBasicJob,
    CNIndexDailyBasicJob,
    CNIndexWeightJob,
    CNAnnouncementJob,
    CNIndexGlobalJob,
    CNChipDistributionJob,
    CNSwDailyJob,
    CNThsDailyJob,
    CNLimitStepJob,
    CNMoneyflowIndDcJob,
    # forecast/express/dividend: 个股级 API，大量股票无数据会触发熔断器，
    # 改为按需获取（分析时自动拉取），不走定时全量同步。
]


def register_cn_jobs(registry) -> None:
    for job_cls in _CN_JOBS:
        job = job_cls()
        registry.register(job.domain, "CN", job_cls)
