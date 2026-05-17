"""
A股 Worker 同步任务（定时全量同步模式）

按数据源拆分入口，所有实现委托给对应的 sync_service。
"""

from app.worker.cn.tushare_sync import (
    get_tushare_sync_service,
    run_tushare_basic_info_sync,
    run_tushare_quotes_sync,
    run_tushare_historical_sync,
    run_tushare_financial_sync,
    run_tushare_status_check,
    run_tushare_news_sync,
)
from app.worker.cn.akshare_sync import (
    get_akshare_sync_service,
    run_akshare_basic_info_sync,
    run_akshare_quotes_sync,
    run_akshare_historical_sync,
    run_akshare_financial_sync,
    run_akshare_status_check,
    run_akshare_news_sync,
)
from app.worker.cn.baostock_sync import (
    run_baostock_basic_info_sync,
    run_baostock_daily_quotes_sync,
    run_baostock_historical_sync,
    run_baostock_status_check,
)
