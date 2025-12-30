"""
Data source manager that orchestrates multiple adapters with priority and optional consistency checks
"""
from typing import List, Optional, Tuple, Dict, Any
import os
import logging
from datetime import datetime, timedelta
import pandas as pd
from pymongo import UpdateOne

from app.services.data_sources.base import DataSourceAdapter
from .providers.tushare.adapter import TushareAdapter
# Temporarily import legacy adapters from app until migrated
from app.services.data_sources.akshare_adapter import AKShareAdapter
from app.services.data_sources.baostock_adapter import BaoStockAdapter

from tradingagents.utils.time_utils import now_utc, get_current_date_compact

logger = logging.getLogger(__name__)


class DataSourceManager:
    """
    数据源管理器
    - 管理多个适配器，基于优先级排序
    - 提供 fallback 获取能力
    - 可选：一致性检查（若依赖存在）
    - 强制数据落库 (Write-Through)
    """

    def __init__(self):
        self.adapters: List[DataSourceAdapter] = [
            TushareAdapter(),
            AKShareAdapter(),
            BaoStockAdapter(),
        ]

        # 从数据库加载优先级配置
        self._load_priority_from_database()

        # 按优先级排序（数字越大优先级越高，所以降序排列）
        self.adapters.sort(key=lambda x: x.priority, reverse=True)

        try:
            from app.services.data_sources.data_consistency_checker import DataConsistencyChecker
            self.consistency_checker = DataConsistencyChecker()
        except Exception:
            logger.warning("⚠️ 数据一致性检查器不可用")
            self.consistency_checker = None

    def _load_priority_from_database(self):
        """从数据库加载数据源优先级配置（从 datasource_groupings 集合读取 A股市场的优先级）"""
        try:
            from app.core.database import get_mongo_db_sync
            db = get_mongo_db_sync()
            groupings_collection = db.datasource_groupings

            # 查询 A股市场的数据源分组配置
            groupings = list(groupings_collection.find({
                "market_category_id": "a_shares",
                "enabled": True
            }))

            if groupings:
                # 创建名称到优先级的映射（数据源名称需要转换为小写）
                priority_map = {}
                for grouping in groupings:
                    data_source_name = grouping.get('data_source_name', '').lower()
                    priority = grouping.get('priority')
                    if data_source_name and priority is not None:
                        priority_map[data_source_name] = priority
                        logger.info(f"📊 从数据库读取 {data_source_name} 在 A股市场的优先级: {priority}")

                # 更新各个 Adapter 的优先级
                for adapter in self.adapters:
                    if adapter.name in priority_map:
                        # 动态设置优先级
                        adapter._priority = priority_map[adapter.name]
                        logger.info(f"✅ 设置 {adapter.name} 优先级: {adapter._priority}")
                    else:
                        # 使用默认优先级
                        adapter._priority = adapter._get_default_priority()
                        logger.info(f"⚠️ 数据库中未找到 {adapter.name} 配置，使用默认优先级: {adapter._priority}")
            else:
                logger.info("⚠️ 数据库中未找到 A股市场的数据源配置，尝试使用环境变量或默认优先级")
                self._apply_env_or_default_priority()
        except Exception as e:
            logger.warning(f"⚠️ 从数据库加载优先级失败: {e}，尝试使用环境变量或默认优先级")
            # import traceback
            # logger.warning(f"堆栈跟踪:\n{traceback.format_exc()}")
            self._apply_env_or_default_priority()

    def _apply_env_or_default_priority(self):
        """应用环境变量或默认优先级"""
        # 1. 重置为默认优先级
        for adapter in self.adapters:
            adapter._priority = adapter._get_default_priority()

        # 2. 检查环境变量
        default_source = os.getenv("DEFAULT_CHINA_DATA_SOURCE", "").lower()
        if default_source:
            logger.info(f"🔧 检测到环境变量 DEFAULT_CHINA_DATA_SOURCE={default_source}")
            target_adapter = next((a for a in self.adapters if a.name == default_source), None)
            if target_adapter:
                # 提升优先级，使其高于默认值 (Tushare=3)
                target_adapter._priority = 10
                logger.info(f"✅ 将 {target_adapter.name} 优先级提升至 10 (基于环境变量)")

    def get_available_adapters(self) -> List[DataSourceAdapter]:
        available: List[DataSourceAdapter] = []
        for adapter in self.adapters:
            if adapter.is_available():
                available.append(adapter)
                logger.info(
                    f"Data source {adapter.name} is available (priority: {adapter.priority})"
                )
            else:
                logger.warning(f"Data source {adapter.name} is not available")
        return available

    def _save_kline_to_db(self, code: str, items: List[Dict], source: str, period: str):
        """
        同步将 K 线数据写入 MongoDB (Write-Through)
        基于 stock_daily_quotes 集合结构
        """
        try:
            from app.core.database import get_mongo_db_sync
            db = get_mongo_db_sync()
            collection = db.stock_daily_quotes

            # 准备批量写入操作
            operations = []

            # 标准化处理
            # 假设 items 是 [{time, open, high, low, close, volume, amount}, ...]
            # 需要转换为 stock_daily_quotes 的字段: symbol, trade_date, data_source, period, open, high, low, close, volume, amount

            # 移除 .SZ/.SH 后缀获取纯数字代码
            symbol = code.split('.')[0]

            for item in items:
                trade_date = str(item.get('time', '')).replace('-', '').replace('/', '')
                if not trade_date:
                    continue

                doc = {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "data_source": source,
                    "period": period,
                    "market": "CN", # 默认为 CN，后续可扩展
                    "open": item.get('open'),
                    "high": item.get('high'),
                    "low": item.get('low'),
                    "close": item.get('close'),
                    "volume": item.get('volume'),
                    "amount": item.get('amount'),
                    "updated_at": now_utc()
                }

                # 构建唯一索引查询条件
                filter_query = {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "data_source": source,
                    "period": period
                }

                operations.append(
                    UpdateOne(filter_query, {"$set": doc}, upsert=True)
                )

            if operations:
                result = collection.bulk_write(operations, ordered=False)
                logger.info(f"💾 [Write-Through] Saved {len(operations)} records for {code} to DB (Upserted: {result.upserted_count}, Modified: {result.modified_count})")

        except Exception as e:
            logger.error(f"❌ Failed to save kline to DB for {code}: {e}")

    def sync_stock_data(self, codes: List[str], period: str = "day"):
        """
        批量同步股票数据 (Pre-Inference Sync)
        强制从接口拉取并入库
        """
        logger.info(f"🔄 Starting batch sync for {len(codes)} stocks...")
        success_count = 0
        for code in codes:
            try:
                # 调用 get_kline_with_fallback 会自动触发 Write-Through
                items, source = self.get_kline_with_fallback(code, period=period)
                if items:
                    success_count += 1
            except Exception as e:
                logger.error(f"Failed to sync {code}: {e}")
        logger.info(f"✅ Batch sync completed. Success: {success_count}/{len(codes)}")

    def get_stock_list_with_fallback(self, preferred_sources: Optional[List[str]] = None) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
        """
        获取股票列表，支持指定优先数据源
        """
        available_adapters = self.get_available_adapters()

        if preferred_sources:
            logger.info(f"Using preferred data sources: {preferred_sources}")
            priority_map = {name: idx for idx, name in enumerate(preferred_sources)}
            preferred = [a for a in available_adapters if a.name in priority_map]
            others = [a for a in available_adapters if a.name not in priority_map]
            preferred.sort(key=lambda a: priority_map.get(a.name, 999))
            available_adapters = preferred + others
            logger.info(f"Reordered adapters: {[a.name for a in available_adapters]}")

        for adapter in available_adapters:
            try:
                logger.info(f"Trying to fetch stock list from {adapter.name}")
                df = adapter.get_stock_list()
                if df is not None and not df.empty:
                    return df, adapter.name
            except Exception as e:
                logger.error(f"Failed to fetch stock list from {adapter.name}: {e}")
                continue
        return None, None

    def get_daily_basic_with_fallback(self, trade_date: str, preferred_sources: Optional[List[str]] = None) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
        """
        获取每日基础数据，支持指定优先数据源
        """
        available_adapters = self.get_available_adapters()

        if preferred_sources:
            priority_map = {name: idx for idx, name in enumerate(preferred_sources)}
            preferred = [a for a in available_adapters if a.name in priority_map]
            others = [a for a in available_adapters if a.name not in priority_map]
            preferred.sort(key=lambda a: priority_map.get(a.name, 999))
            available_adapters = preferred + others

        for adapter in available_adapters:
            try:
                logger.info(f"Trying to fetch daily basic data from {adapter.name}")
                df = adapter.get_daily_basic(trade_date)
                if df is not None and not df.empty:
                    return df, adapter.name
            except Exception as e:
                logger.error(f"Failed to fetch daily basic data from {adapter.name}: {e}")
                continue
        return None, None

    def find_latest_trade_date_with_fallback(self, preferred_sources: Optional[List[str]] = None) -> Optional[str]:
        """
        查找最新交易日期，支持指定优先数据源
        """
        available_adapters = self.get_available_adapters()

        if preferred_sources:
            priority_map = {name: idx for idx, name in enumerate(preferred_sources)}
            preferred = [a for a in available_adapters if a.name in priority_map]
            others = [a for a in available_adapters if a.name not in priority_map]
            preferred.sort(key=lambda a: priority_map.get(a.name, 999))
            available_adapters = preferred + others

        for adapter in available_adapters:
            try:
                trade_date = adapter.find_latest_trade_date()
                if trade_date:
                    return trade_date
            except Exception as e:
                logger.error(f"Failed to find trade date from {adapter.name}: {e}")
                continue
        return (now_utc() - timedelta(days=1)).strftime("%Y%m%d")

    def get_realtime_quotes_with_fallback(self) -> Tuple[Optional[Dict], Optional[str]]:
        """
        获取全市场实时快照，按适配器优先级依次尝试，返回首个成功结果
        Returns: (quotes_dict, source_name)
        quotes_dict 形如 { '000001': {'close': 10.0, 'pct_chg': 1.2, 'amount': 1.2e8}, ... }
        """
        available_adapters = self.get_available_adapters()
        for adapter in available_adapters:
            try:
                logger.info(f"Trying to fetch realtime quotes from {adapter.name}")
                data = adapter.get_realtime_quotes()
                if data:
                    return data, adapter.name
            except Exception as e:
                logger.error(f"Failed to fetch realtime quotes from {adapter.name}: {e}")
                continue
        return None, None


    def get_daily_basic_with_consistency_check(
        self, trade_date: str
    ) -> Tuple[Optional[pd.DataFrame], Optional[str], Optional[Dict]]:
        """
        使用一致性检查获取每日基础数据
        """
        available_adapters = self.get_available_adapters()
        if len(available_adapters) < 2:
            df, source = self.get_daily_basic_with_fallback(trade_date)
            return df, source, None
        primary_adapter = available_adapters[0]
        secondary_adapter = available_adapters[1]
        try:
            logger.info(
                f"🔍 获取数据进行一致性检查: {primary_adapter.name} vs {secondary_adapter.name}"
            )
            primary_data = primary_adapter.get_daily_basic(trade_date)
            secondary_data = secondary_adapter.get_daily_basic(trade_date)
            if primary_data is None or primary_data.empty:
                logger.warning(f"⚠️ 主数据源{primary_adapter.name}失败，使用fallback")
                df, source = self.get_daily_basic_with_fallback(trade_date)
                return df, source, None
            if secondary_data is None or secondary_data.empty:
                logger.warning(f"⚠️ 次数据源{secondary_adapter.name}失败，使用主数据源")
                return primary_data, primary_adapter.name, None
            if self.consistency_checker:
                consistency_result = self.consistency_checker.check_daily_basic_consistency(
                    primary_data,
                    secondary_data,
                    primary_adapter.name,
                    secondary_adapter.name,
                )
                final_data, resolution_strategy = self.consistency_checker.resolve_data_conflicts(
                    primary_data, secondary_data, consistency_result
                )
                consistency_report = {
                    'is_consistent': consistency_result.is_consistent,
                    'confidence_score': consistency_result.confidence_score,
                    'recommended_action': consistency_result.recommended_action,
                    'resolution_strategy': resolution_strategy,
                    'differences': consistency_result.differences,
                    'primary_source': primary_adapter.name,
                    'secondary_source': secondary_adapter.name,
                }
                logger.info(
                    f"📊 数据一致性检查完成: 置信度={consistency_result.confidence_score:.2f}, 策略={consistency_result.recommended_action}"
                )
                return final_data, primary_adapter.name, consistency_report
            else:
                logger.warning("⚠️ 一致性检查器不可用，使用主数据源")
                return primary_data, primary_adapter.name, None
        except Exception as e:
            logger.error(f"❌ 一致性检查失败: {e}")
            df, source = self.get_daily_basic_with_fallback(trade_date)
            return df, source, None


    def get_kline_with_fallback(self, code: str, period: str = "day", limit: int = 120, adj: Optional[str] = None) -> Tuple[Optional[List[Dict]], Optional[str]]:
        """按优先级尝试获取K线，返回(items, source)"""
        available_adapters = self.get_available_adapters()
        for adapter in available_adapters:
            try:
                logger.info(f"Trying to fetch kline from {adapter.name}")
                items = adapter.get_kline(code=code, period=period, limit=limit, adj=adj)
                if items:
                    # 🔥 Write-Through: 立即写入数据库
                    self._save_kline_to_db(code, items, adapter.name, period)
                    return items, adapter.name
            except Exception as e:
                logger.error(f"Failed to fetch kline from {adapter.name}: {e}")
                continue
        return None, None

    def get_kline_all_sources(self, code: str, period: str = "day", limit: int = 120, adj: Optional[str] = None) -> Dict[str, List[Dict]]:
        """获取所有可用数据源的K线数据"""
        available_adapters = self.get_available_adapters()
        results = {}
        for adapter in available_adapters:
            try:
                logger.info(f"Trying to fetch kline from {adapter.name}")
                items = adapter.get_kline(code=code, period=period, limit=limit, adj=adj)
                if items:
                    results[adapter.name] = items
                    # 🔥 Write-Through: 立即写入数据库
                    self._save_kline_to_db(code, items, adapter.name, period)
            except Exception as e:
                logger.error(f"Failed to fetch kline from {adapter.name}: {e}")
                continue
        return results

    def get_news_with_fallback(self, code: str, days: int = 2, limit: int = 50, include_announcements: bool = True) -> Tuple[Optional[List[Dict]], Optional[str]]:
        """按优先级尝试获取新闻与公告，返回(items, source)"""
        available_adapters = self.get_available_adapters()
        for adapter in available_adapters:
            try:
                logger.info(f"Trying to fetch news from {adapter.name}")
                items = adapter.get_news(code=code, days=days, limit=limit, include_announcements=include_announcements)
                if items:
                    return items, adapter.name
            except Exception as e:
                logger.error(f"Failed to fetch news from {adapter.name}: {e}")
                continue
        return None, None

    def _query_with_fallback(self, api_name: str, **kwargs) -> Optional[Any]:
        """Generic query with fallback"""
        available_adapters = self.get_available_adapters()
        for adapter in available_adapters:
            try:
                # logger.info(f"Trying to query {api_name} from {adapter.name}")
                if hasattr(adapter, "query"):
                    df = adapter.query(api_name, **kwargs)
                    if df is not None and not df.empty:
                        return df.to_dict(orient="records")
            except Exception as e:
                logger.error(f"Query {api_name} from {adapter.name} failed: {e}")
                continue
        return None

    # --- Extended Finance Tools Implementation ---

    def get_stock_data(self, code: str, market_type: str, start_date: str, end_date: str, indicators: str = None):
        # Implementation for stock data (similar to get_kline but with market type and formatting)
        # For now, reuse get_kline_with_fallback if market is CN
        if market_type == "cn":
            items, _ = self.get_kline_with_fallback(code, period="day", limit=300) # approximate limit
            # Note: start/end date filtering needs to be applied if adapter doesn't support it directly
            # Tushare adapter pro_bar supports start_date/end_date but get_kline interface uses limit.
            # I should update get_kline interface or use query.
            # Using query is more flexible.
            return self._query_with_fallback("daily", ts_code=code, start_date=start_date, end_date=end_date)
        elif market_type == "hk":
            return self._query_with_fallback("hk_daily", ts_code=code, start_date=start_date, end_date=end_date)
        elif market_type == "us":
            return self._query_with_fallback("us_daily", ts_code=code, start_date=start_date, end_date=end_date)
        return None

    def get_stock_data_minutes(self, market_type: str, code: str, start_datetime: str, end_datetime: str, freq: str):
        # freq mapping: 1min, 5min...
        return self._query_with_fallback("stk_mins", ts_code=code, start_date=start_datetime, end_date=end_datetime, freq=freq)

    def get_company_performance(self, ts_code: str, data_type: str, start_date: str, end_date: str, period: str = None, ind_name: str = None, market: str = "cn"):
        api_map = {
            "cn": {
                "forecast": "forecast", "express": "express", "indicators": "fina_indicator",
                "dividend": "dividend", "mainbz": "fina_mainbz", "holder_number": "stk_holdernumber",
                "holder_trade": "stk_holdertrade", "managers": "stk_managers", "audit": "fina_audit",
                "company_basic": "stock_company", "balance_basic": "balancesheet", "balance_all": "balancesheet",
                "cashflow_basic": "cashflow", "cashflow_all": "cashflow", "income_basic": "income", "income_all": "income",
                "share_float": "share_float", "repurchase": "repurchase", "top10_holders": "top10_holders",
                "top10_floatholders": "top10_floatholders", "pledge_stat": "pledge_stat", "pledge_detail": "pledge_detail"
            },
            "hk": {
                "income": "hk_income", "balance": "hk_balancesheet", "cashflow": "hk_cashflow"
            },
            "us": {
                "income": "us_income", "balance": "us_balancesheet", "cashflow": "us_cashflow", "indicator": "us_fina_indicator"
            }
        }
        api_name = api_map.get(market, {}).get(data_type)
        if not api_name:
            return None

        params = {"ts_code": ts_code, "start_date": start_date, "end_date": end_date}
        if period: params["period"] = period
        if ind_name: params["ind_name"] = ind_name

        return self._query_with_fallback(api_name, **params)

    def get_macro_econ(self, indicator: str, start_date: str, end_date: str):
        api_map = {
            "shibor": "shibor", "lpr": "lpr_data", "gdp": "cn_gdp", "cpi": "cn_cpi",
            "ppi": "cn_ppi", "cn_m": "cn_m", "cn_pmi": "cn_pmi", "cn_sf": "cn_sf",
            "shibor_quote": "shibor_quote", "libor": "libor", "hibor": "hibor"
        }
        api_name = api_map.get(indicator)
        if not api_name: return None
        return self._query_with_fallback(api_name, start_date=start_date, end_date=end_date)

    def get_money_flow(self, start_date: str, end_date: str, query_type: str = None, ts_code: str = None, content_type: str = None, trade_date: str = None):
        if not query_type:
            # Auto detect
            if ts_code and ts_code[0].isdigit(): query_type = "stock"
            else: query_type = "market"

        api_map = {"stock": "moneyflow_dc", "market": "moneyflow_mkt_dc", "sector": "moneyflow_ind_dc"}
        api_name = api_map.get(query_type, "moneyflow_dc")

        params = {"start_date": start_date, "end_date": end_date}
        if ts_code: params["ts_code"] = ts_code
        if trade_date: params["trade_date"] = trade_date

        return self._query_with_fallback(api_name, **params)

    def get_margin_trade(self, data_type: str, start_date: str, end_date: str = None, ts_code: str = None, exchange: str = None):
        # margin_secs, margin, margin_detail, slb_len_mm
        return self._query_with_fallback(data_type, start_date=start_date, end_date=end_date, ts_code=ts_code, exchange_id=exchange)

    def get_fund_data(self, ts_code: str, data_type: str, start_date: str = None, end_date: str = None, period: str = None):
        api_map = {
            "basic": "fund_basic", "manager": "fund_manager", "nav": "fund_nav",
            "dividend": "fund_div", "portfolio": "fund_portfolio"
        }
        api_name = api_map.get(data_type)
        if not api_name: return None

        params = {"ts_code": ts_code}
        if start_date: params["start_date"] = start_date
        if end_date: params["end_date"] = end_date
        if period: params["period"] = period

        return self._query_with_fallback(api_name, **params)

    def get_fund_manager_by_name(self, name: str, ann_date: str = None):
        params = {"name": name}
        if ann_date: params["ann_date"] = ann_date
        return self._query_with_fallback("fund_manager", **params)

    def get_index_data(self, code: str, start_date: str, end_date: str):
        return self._query_with_fallback("index_daily", ts_code=code, start_date=start_date, end_date=end_date)

    def get_csi_index_constituents(self, index_code: str, start_date: str, end_date: str):
        # This requires multiple calls (weight, daily, basic), simplifying to weight for now or index_weight
        return self._query_with_fallback("index_weight", index_code=index_code, start_date=start_date, end_date=end_date)

    def get_convertible_bond(self, data_type: str, ts_code: str = None, start_date: str = None, end_date: str = None):
        api_map = {"info": "cb_basic", "issue": "cb_issue"}
        api_name = api_map.get(data_type, "cb_basic")
        params = {}
        if ts_code: params["ts_code"] = ts_code
        if start_date: params["start_date"] = start_date
        if end_date: params["end_date"] = end_date
        return self._query_with_fallback(api_name, **params)

    def get_block_trade(self, start_date: str, end_date: str, code: str = None):
        params = {"start_date": start_date, "end_date": end_date}
        if code: params["ts_code"] = code
        return self._query_with_fallback("block_trade", **params)

    def get_dragon_tiger_inst(self, trade_date: str, ts_code: str = None):
        params = {"trade_date": trade_date}
        if ts_code: params["ts_code"] = ts_code
        return self._query_with_fallback("top_inst", **params)

    def get_finance_news(self, query: str):
        # Tushare doesn't have a search news by query API easily (news is stream).
        # We can try 'news' with src='sina' etc.
        # But 'finance_news' tool description says "Baidu News Crawler (Non-Tushare)".
        # Since I am in DataSourceManager, I should stick to adapters.
        # Tushare has `news` (major news) and `major_news` (CCTV).
        # I will use `news` for now.
        return self._query_with_fallback("news", src="sina", query=query) # Defaulting to Sina news stream

    def get_hot_news_7x24(self, limit: int = 100):
        # Tushare 'news' interface needs src, start_date, end_date.
        # But 'major_news' or 'cctv_news' might be better for 7x24.
        # Actually 'news' with src='sina' is often used for 7x24 rolling news.
        now = now_utc()
        start = (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        end = now.strftime("%Y-%m-%d %H:%M:%S")
        return self._query_with_fallback("news", src="sina", start_date=start, end_date=end, limit=limit)
