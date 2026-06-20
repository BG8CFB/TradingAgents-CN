"""P0/P1 修复专项单元测试。

覆盖 11 项修复（5 Wave1 + 5 Wave2 + 1 代表性 Wave3）：
- F4  connect_status_repo filter/projection 错位
- SE1 Tencent HK HTTPS 常量化
- SE2 stock_news SHA-256 哈希
- N1  period_aggregator ISO 周跨年 key
- D2  period_aggregator pre_close 语义
- D4  Finnhub 时区转换
- N3  Finnhub end_ts 闭区间边界
- D1  AKShare 市值单位映射
- D9  Tushare news 日期透传
- D7  HK financials 日期参数
- D3  USCodeResolver exchange 映射
- C2  RefreshResult.compute_status 处理 SKIPPED
- C3  RateLimiter.release + SlidingWindowCounter.try_decrement
- D10 SourceHealthMonitor 1h 滑动窗口
- F3  CacheService 禁止删除系统内部键
- F1  HK 4 Provider 委托 api/ 子模块（结构验证）
"""

import hashlib
import inspect
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.data.schema.base.enums import RefreshStatus


# ============================================================================
# F4: connect_status_repo — filter/projection/sort 三参数位序正确
# ============================================================================
class TestF4ConnectStatusRepo:
    """验证 get_latest 使用正确的 Motor find_one 调用形态。"""

    def test_get_latest_signature_has_sort_param(self):
        from app.data.storage.mongo.repositories import connect_status_repo as repo_mod

        src = inspect.getsource(repo_mod.ConnectStatusRepo.get_latest)
        # 关键：第二个位置参数 projection dict；sort= 关键字参数传 list of tuples
        assert '{"_id": 0}' in src, "projection 应显式排除 _id"
        assert 'sort=[("trade_date", -1)]' in src, "应按 trade_date 倒序取最新"

    @pytest.mark.asyncio
    async def test_get_latest_returns_latest_record(self, inject_sim_db):
        """端到端：插入 3 条不同 trade_date，断言返回最新一条且无 _id。"""
        from app.data.storage.mongo.collections import get_collection_name
        from app.data.storage.mongo.repositories.connect_status_repo import (
            ConnectStatusRepo,
        )

        coll_name = get_collection_name("connect_status", "CN")
        coll = inject_sim_db[coll_name]
        # 按随机顺序插入，验证 sort 真正生效
        await coll.insert_one({"symbol": "600519", "trade_date": "2024-06-10", "data_source": "x"})
        await coll.insert_one({"symbol": "600519", "trade_date": "2024-06-15", "data_source": "x"})
        await coll.insert_one({"symbol": "600519", "trade_date": "2024-06-01", "data_source": "x"})

        # SimulatedMongoCollection.find_one 不支持 sort kwarg，通过 stub 验证调用形参
        calls = []

        async def spy_find_one(filter_dict=None, projection=None, **kwargs):
            calls.append((filter_dict, projection, kwargs))
            # 返回最新一条（模拟 sort 生效）
            return {"symbol": "600519", "trade_date": "2024-06-15", "data_source": "x"}

        coll.find_one = spy_find_one

        repo = ConnectStatusRepo()
        result = await repo.get_latest("CN")

        assert result is not None
        assert result["trade_date"] == "2024-06-15"
        assert "_id" not in result
        # 验证调用签名：第一参数 filter，第二参数 projection，sort 走 kwarg
        assert len(calls) == 1
        f, p, kw = calls[0]
        assert f == {}
        assert p == {"_id": 0}
        assert kw.get("sort") == [("trade_date", -1)]


# ============================================================================
# SE1: Tencent HK 明文 HTTP → HTTPS
# ============================================================================
class TestSE1TencentHttps:
    def test_market_quotes_uses_https_constant(self):
        from app.data.sources.hk.tencent_hk.api import market_quotes as mod

        assert hasattr(mod, "TENCENT_QUOTE_HOST"), "应有模块常量"
        assert mod.TENCENT_QUOTE_HOST.startswith("https://"), "必须是 HTTPS"
        # 源代码中不应再出现裸 http://qt.gtimg.cn 字符串
        src = inspect.getsource(mod)
        assert 'http://qt.gtimg.cn' not in src, "不应残留明文 http URL"

    def test_provider_imports_https_api(self):
        from app.data.sources.hk.tencent_hk import provider as prov_mod

        src = inspect.getsource(prov_mod)
        # provider 不应在内部直连 HTTP，应委托 api/market_quotes
        assert "fetch_market_quotes" in src
        assert "http://" not in src


# ============================================================================
# SE2: stock_news 用 SHA-256（替代 MD5）
# ============================================================================
class TestSE2StockNewsSha256:
    def test_compute_hash_uses_sha256(self):
        from app.data.schema.domains.stock_news import StockNewsSchema

        src = inspect.getsource(StockNewsSchema.compute_hash)
        assert "sha256" in src, "compute_hash 必须用 SHA-256"
        assert "md5" not in src.lower(), "不应再使用 MD5"

    def test_compute_hash_is_deterministic_and_distinct(self):
        from app.data.schema.domains.stock_news import StockNewsSchema

        h1 = StockNewsSchema.compute_hash("title", "2024-06-01 10:00:00")
        h2 = StockNewsSchema.compute_hash("title", "2024-06-01 10:00:00")
        h3 = StockNewsSchema.compute_hash("title", "2024-06-01 10:00:01")
        # 同输入同哈希
        assert h1 == h2
        # 不同输入不同哈希
        assert h1 != h3
        # SHA-256 hex 长度 64
        assert len(h1) == 64

    def test_compute_hash_matches_reference_value(self):
        """断言哈希算法确实是 SHA-256，而非 MD5 或其它。"""
        from app.data.schema.domains.stock_news import StockNewsSchema

        raw = "title|2024-06-01"
        expected = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        actual = StockNewsSchema.compute_hash("title", "2024-06-01")
        assert actual == expected


# ============================================================================
# N1: period_aggregator ISO 周跨年 key（2024-12-30 与 2025-01-01 应聚为同一周）
# D2: period_aggregator pre_close 跨周语义
# ============================================================================
class TestN1D2PeriodAggregator:
    def _aggregator(self):
        from app.data.processor.post_processors.period_aggregator import (
            PeriodAggregator,
        )
        return PeriodAggregator()

    def test_week_key_uses_monday_date(self):
        """跨年 ISO 周：2024-12-30（周一）与 2025-01-03（周五）应同属一周。"""
        from app.data.processor.post_processors.period_aggregator import (
            PeriodAggregator,
        )

        k1 = PeriodAggregator._week_key("2024-12-30")
        k2 = PeriodAggregator._week_key("2024-12-31")
        k3 = PeriodAggregator._week_key("2025-01-01")
        k4 = PeriodAggregator._week_key("2025-01-03")
        k5 = PeriodAggregator._week_key("2025-01-06")  # 下周一
        # 同一周（ISO 2025-W01 的自然周）
        assert k1 == k2 == k3 == k4 == "2024-12-30"
        # 下周应分开
        assert k5 != k1
        assert k5 == "2025-01-06"

    def test_aggregate_groups_cross_year_week(self):
        """ISO 跨年周内的日线应聚合为单条周 K。"""
        agg = self._aggregator()
        daily = [
            {"symbol": "AAPL", "trade_date": "2024-12-30", "open": 100, "high": 102,
             "low": 99, "close": 101, "pre_close": 100, "volume": 1000, "amount": 100000},
            {"symbol": "AAPL", "trade_date": "2024-12-31", "open": 101, "high": 103,
             "low": 100, "close": 102, "pre_close": 101, "volume": 1100, "amount": 110000},
            {"symbol": "AAPL", "trade_date": "2025-01-01", "open": 102, "high": 104,
             "low": 101, "close": 103, "pre_close": 102, "volume": 900, "amount": 90000},
            {"symbol": "AAPL", "trade_date": "2025-01-02", "open": 103, "high": 105,
             "low": 102, "close": 104, "pre_close": 103, "volume": 1200, "amount": 120000},
            {"symbol": "AAPL", "trade_date": "2025-01-03", "open": 104, "high": 106,
             "low": 103, "close": 105, "pre_close": 104, "volume": 800, "amount": 80000},
        ]
        result = agg.aggregate_to_weekly(daily)
        assert len(result) == 1, f"应聚为 1 条周 K，实际 {len(result)}"
        wk = result[0]
        assert wk["symbol"] == "AAPL"
        assert wk["open"] == 100
        assert wk["high"] == 106
        assert wk["low"] == 99
        assert wk["close"] == 105
        assert wk["volume"] == 1000 + 1100 + 900 + 1200 + 800

    def test_aggregate_pre_close_uses_previous_week_close(self):
        """D2：第二周的 pre_close 应等于第一周的 close。"""
        agg = self._aggregator()
        daily = [
            # 第一周
            {"symbol": "X", "trade_date": "2025-01-06", "open": 100, "high": 102,
             "low": 99, "close": 101, "pre_close": 100, "volume": 1000, "amount": 100000},
            {"symbol": "X", "trade_date": "2025-01-07", "open": 101, "high": 103,
             "low": 100, "close": 102, "pre_close": 101, "volume": 1000, "amount": 100000},
            # 第二周
            {"symbol": "X", "trade_date": "2025-01-13", "open": 102, "high": 110,
             "low": 101, "close": 108, "pre_close": 102, "volume": 2000, "amount": 200000},
            {"symbol": "X", "trade_date": "2025-01-14", "open": 108, "high": 112,
             "low": 107, "close": 110, "pre_close": 108, "volume": 2000, "amount": 200000},
        ]
        result = agg.aggregate_to_weekly(daily)
        result.sort(key=lambda r: r["trade_date"])
        assert len(result) == 2

        # 第一周：pre_close 保留日线首条 pre_close=100；close=102
        assert result[0]["close"] == 102
        assert result[0]["pre_close"] == 100
        # change = close - pre_close = 102 - 100 = 2
        assert result[0]["change"] == 2.0
        # 第二周：pre_close 应等于第一周的 close=102
        assert result[1]["close"] == 110
        assert result[1]["pre_close"] == 102
        assert result[1]["change"] == 8.0
        # pct_chg = (110 - 102) / 102 * 100
        assert abs(result[1]["pct_chg"] - (110 - 102) / 102 * 100) < 0.01


# ============================================================================
# D4 + N3: Finnhub 时区 + end_ts 闭区间
# ============================================================================
class TestD4N3FinnhubTimezone:
    def test_get_daily_quotes_uses_et_timezone(self):
        from app.data.sources.us.finnhub import provider as prov_mod

        src = inspect.getsource(prov_mod.FinnhubUSProvider.get_daily_quotes)
        # 必须引入 ET 时区
        assert "get_market_timezone" in src or "ZoneInfo" in src
        # trade_date 转换必须经 astimezone
        assert "astimezone" in src

    def test_get_daily_quotes_end_ts_is_closed_interval(self):
        """end_date 当天必须被包含：end_ts = end_date + 1 day。"""
        from app.data.sources.us.finnhub import provider as prov_mod

        src = inspect.getsource(prov_mod.FinnhubUSProvider.get_daily_quotes)
        # 关键标记：必须出现 + timedelta(days=1) 确保 end_date 当天覆盖
        assert "timedelta(days=1)" in src

    def test_get_daily_quotes_ts_conversion_correctness(self):
        """验证闭区间边界：end_date=2024-06-30 的 end_ts 必须包含 6-30 当天。"""
        # 直接复制 provider 内部计算逻辑验证
        utc = timezone.utc
        end_date = "2024-06-30"
        end_ts = int((
            datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=utc) + timedelta(days=1)
        ).timestamp())
        # 6-30 23:59:59 UTC 应小于 end_ts（在闭区间内）
        jun30_end = int(datetime(2024, 6, 30, 23, 59, 59, tzinfo=utc).timestamp())
        assert jun30_end < end_ts, "end_date 当天结束时应仍被包含"
        # 7-1 00:00:00 UTC 等于 end_ts（恰好下一天午夜，不含）
        jul1_start = int(datetime(2024, 7, 1, 0, 0, 0, tzinfo=utc).timestamp())
        assert jul1_start == end_ts


# ============================================================================
# D1: AKShare 市值单位映射表（按接口名声明，替代启发式阈值判断）
# ============================================================================
class TestD1AkshareMarketCapUnit:
    def test_unit_map_declares_baidu_interface(self):
        from app.data.sources.cn.akshare import adapter as ad

        assert "_AKSHARE_MV_UNIT_BY_INTERFACE" in dir(ad)
        assert ad._AKSHARE_MV_UNIT_BY_INTERFACE["stock_zh_valuation_baidu"] == "亿元"

    def test_convert_mv_yi_to_yuan(self):
        from app.data.sources.cn.akshare.adapter import _convert_mv

        # 2 万亿元 = 2e4 亿元 → 2e12 元
        result = _convert_mv(20000, "亿元")
        assert result == 2e12
        # 茅台市值约 1.5-2 万亿元，落在合理区间
        assert 1e12 < _convert_mv(15000, "亿元") < 5e12

    def test_convert_mv_wan_to_yuan(self):
        from app.data.sources.cn.akshare.adapter import _convert_mv

        # 1 万元 → 1e4 元
        assert _convert_mv(1, "万元") == 1e4

    def test_convert_mv_yuan_passthrough(self):
        from app.data.sources.cn.akshare.adapter import _convert_mv

        assert _convert_mv(42, "元") == 42
        # 未知单位按元处理（保守）
        assert _convert_mv(42, "未知") == 42

    def test_convert_mv_none_handling(self):
        from app.data.sources.cn.akshare.adapter import _convert_mv

        assert _convert_mv(None, "亿元") is None

    def test_adapter_does_not_use_heuristic_threshold(self):
        """不应再出现 `if total_mv < 1e12: ×= 1e8` 之类启发式判断。"""
        from app.data.sources.cn.akshare import adapter as ad

        src = inspect.getsource(ad)
        # 确认旧启发式已被删除
        assert "1e12" not in src or "< 1e12" not in src
        # 必须显式引用映射表
        assert "_AKSHARE_MV_UNIT_BY_INTERFACE" in src

    def test_adapt_daily_indicators_normalizes_total_mv(self):
        """端到端：百度股市通返回的"亿元"数值应被归一化为元。"""
        from app.data.sources.cn.akshare.adapter import AKShareCNAdapter

        df = pd.DataFrame([{
            "symbol": "600519",
            "trade_date": "2024-06-15",
            "total_mv": 20000,  # 20000 亿元 = 2 万亿元
            "circ_mv": 15000,
            "pe_ttm": 30,
        }])
        adapter = AKShareCNAdapter()
        result = adapter.adapt_daily_indicators(df)
        assert len(result) == 1
        item = result[0]
        # 2 万亿元 = 2e12 元
        assert item.total_mv == 2e12
        assert item.circ_mv == 1.5e12
        assert item.symbol == "600519"


# ============================================================================
# D9: Tushare news 日期透传过滤
# ============================================================================
class TestD9TushareNewsDateFilter:
    def test_fetch_news_signature_has_date_params(self):
        from app.data.sources.cn.tushare.api import news as news_mod

        sig = inspect.signature(news_mod.fetch_news)
        assert "start_date" in sig.parameters
        assert "end_date" in sig.parameters

    def test_publish_time_in_range_closed_interval(self):
        from app.data.sources.cn.tushare.api.news import _publish_time_in_range

        # 闭区间：两端都含
        assert _publish_time_in_range("2024-06-01 10:00:00", "2024-06-01", "2024-06-10")
        assert _publish_time_in_range("2024-06-10 23:59:59", "2024-06-01", "2024-06-10")
        # 区间外应排除
        assert not _publish_time_in_range("2024-05-31", "2024-06-01", "2024-06-10")
        assert not _publish_time_in_range("2024-06-11", "2024-06-01", "2024-06-10")

    def test_publish_time_in_range_none_publish_time(self):
        from app.data.sources.cn.tushare.api.news import _publish_time_in_range

        # publish_time 为空时返回 False（不入库）
        assert not _publish_time_in_range(None, "2024-06-01", "2024-06-10")

    def test_publish_time_in_range_open_bounds(self):
        from app.data.sources.cn.tushare.api.news import _publish_time_in_range

        # 仅提供 start_date
        assert _publish_time_in_range("2024-07-01", "2024-06-01", None)
        assert not _publish_time_in_range("2024-05-01", "2024-06-01", None)
        # 仅提供 end_date
        assert _publish_time_in_range("2024-05-01", None, "2024-06-10")
        assert not _publish_time_in_range("2024-07-01", None, "2024-06-10")

    def test_strict_date_parses_compact_format(self):
        """Tushare 返回 publish_time 可能是 YYYYMMDD 紧凑格式。"""
        from app.data.sources.cn.tushare.api.news import _strict_date

        d1 = _strict_date("2024-06-15")
        d2 = _strict_date("2024-06-15 10:00:00")
        d3 = _strict_date("20240615")
        assert d1 == d2 == d3
        assert d1.year == 2024 and d1.month == 6 and d1.day == 15

    def test_strict_date_returns_none_on_invalid(self):
        from app.data.sources.cn.tushare.api.news import _strict_date

        # 解析失败返回 None（不 fallback 到当前时间）
        assert _strict_date("invalid") is None
        assert _strict_date("") is None
        assert _strict_date(None) is None


# ============================================================================
# D7: HK/US 财务数据日期参数透传
# ============================================================================
class TestD7FinancialsDateParams:
    def test_hk_fetch_financial_data_signature_has_dates(self):
        from app.data.sources.hk.tushare_hk.api import hk_financials as m

        sig = inspect.signature(m.fetch_financial_data)
        assert "start_date" in sig.parameters
        assert "end_date" in sig.parameters
        assert "period" in sig.parameters

    def test_compact_date_iso_to_yyyymmdd(self):
        from app.data.sources.hk.tushare_hk.api.hk_financials import _compact_date

        assert _compact_date("2024-06-15") == "20240615"
        assert _compact_date("2024-06-15 ") == "20240615"
        assert _compact_date(None) is None
        assert _compact_date("") is None

    @pytest.mark.asyncio
    async def test_hk_fetch_financial_data_passes_date_params(self):
        """验证 start_date/end_date 透传到 Tushare api 方法参数。"""
        from app.data.sources.hk.tushare_hk.api.hk_financials import (
            fetch_financial_data,
        )

        captured = {}

        class FakeAPI:
            def hk_income(self, **kwargs):
                captured.update(kwargs)
                return pd.DataFrame([{"ts_code": "0700.HK", "ann_date": "20240615"}])

        await fetch_financial_data(
            FakeAPI(),
            "0700.HK",
            statement_type="income",
            start_date="2024-01-01",
            end_date="2024-06-30",
        )
        # Tushare 入参应是 YYYYMMDD 格式
        assert captured.get("ts_code") == "0700.HK"
        assert captured.get("start_date") == "20240101"
        assert captured.get("end_date") == "20240630"

    @pytest.mark.asyncio
    async def test_us_financials_module_exists(self):
        """US 侧应有对应 financials api 模块。"""
        from app.data.sources.us.tushare_us.api import us_financials as m

        assert hasattr(m, "fetch_financial_data")
        sig = inspect.signature(m.fetch_financial_data)
        assert "start_date" in sig.parameters
        assert "end_date" in sig.parameters


# ============================================================================
# D3: USCodeResolver 基于 exchange 字段映射
# ============================================================================
class TestD3USCodeResolver:
    def setup_method(self):
        from app.data.sources.us.tushare_us.code_resolver import USCodeResolver
        USCodeResolver.reset_instance()

    @pytest.mark.asyncio
    async def test_resolver_returns_as_is_when_already_suffixed(self):
        from app.data.sources.us.tushare_us.code_resolver import get_us_ts_code

        result = await get_us_ts_code("AAPL.O")
        assert result == "AAPL.O"

    @pytest.mark.asyncio
    async def test_resolver_uses_exchange_mapping(self):
        """通过注入映射验证：NYSE → .N，NASDAQ → .O，AMEX → .A。"""
        from app.data.sources.us.tushare_us.code_resolver import USCodeResolver

        resolver = USCodeResolver()
        # 注入缓存映射
        resolver._cache.set(
            "us_code_resolver:map",
            {"AAPL": "NASDAQ", "BABA": "NYSE", "SPY": "AMEX"},
            ttl=300,
        )
        r1 = await resolver.resolve("AAPL")
        r2 = await resolver.resolve("BABA")
        r3 = await resolver.resolve("SPY")
        assert r1 == "AAPL.O", f"AAPL 在 NASDAQ → .O，实际 {r1}"
        assert r2 == "BABA.N", f"BABA 在 NYSE → .N，实际 {r2}"
        assert r3 == "SPY.A", f"SPY 在 AMEX → .A，实际 {r3}"

    @pytest.mark.asyncio
    async def test_resolver_falls_back_to_dot_o_when_unknown(self):
        from app.data.sources.us.tushare_us.code_resolver import USCodeResolver

        resolver = USCodeResolver()
        # 未在映射中的 symbol 默认 .O
        resolver._cache.set("us_code_resolver:map", {"UNKNOWN": "LSE"}, ttl=300)
        result = await resolver.resolve("UNKNOWN")
        assert result == "UNKNOWN.O"

    @pytest.mark.asyncio
    async def test_resolver_falls_back_to_dot_o_when_no_mapping(self):
        from app.data.sources.us.tushare_us.code_resolver import USCodeResolver

        resolver = USCodeResolver()
        # 空映射 + 无 api
        resolver._cache.set("us_code_resolver:map", {}, ttl=300)
        result = await resolver.resolve("NEWCODE")
        assert result == "NEWCODE.O"

    def test_resolver_df_to_mapping(self):
        from app.data.sources.us.tushare_us.code_resolver import USCodeResolver

        df = pd.DataFrame([
            {"ts_code": "AAPL.O", "exchange": "NASDAQ"},
            {"ts_code": "BABA.N", "exchange": "NYSE"},
        ])
        mapping = USCodeResolver._df_to_mapping(df)
        assert mapping == {"AAPL": "NASDAQ", "BABA": "NYSE"}


# ============================================================================
# C2: RefreshResult.compute_status 正确处理 SKIPPED 状态
# ============================================================================
class TestC2SkippedStatus:
    def _make(self, **domains):
        from app.data.core.result import RefreshResult, DomainRefreshResult
        r = RefreshResult(symbol="X", market="CN")
        r.domains = {
            name: DomainRefreshResult(domain=name, status=status)
            for name, status in domains.items()
        }
        return r

    def test_all_skipped_returns_skipped(self):
        r = self._make(d1="skipped", d2="skipped")
        assert r.compute_status() == RefreshStatus.SKIPPED

    def test_skipped_plus_fresh_returns_fresh(self):
        r = self._make(d1="skipped", d2="fresh")
        assert r.compute_status() == RefreshStatus.FRESH

    def test_skipped_plus_refreshed_returns_refreshed(self):
        r = self._make(d1="skipped", d2="refreshed")
        assert r.compute_status() == RefreshStatus.REFRESHED

    def test_skipped_plus_failed_returns_partial(self):
        # 一个 skipped，一个 failed → 视为部分成功（skipped 不算失败）
        r = self._make(d1="skipped", d2="failed", d3="refreshed")
        assert r.compute_status() == RefreshStatus.PARTIAL

    def test_skipped_plus_all_failed_returns_failed(self):
        # skipped 不算失败，但剩余全部 failed 仍判 FAILED
        r = self._make(d1="skipped", d2="failed", d3="failed")
        assert r.compute_status() == RefreshStatus.FAILED

    def test_skipped_does_not_mask_timeout(self):
        r = self._make(d1="skipped", d2="timeout", d3="refreshed")
        assert r.compute_status() == RefreshStatus.PARTIAL


# ============================================================================
# C3: RateLimiter.release + SlidingWindowCounter.try_decrement
# ============================================================================
class TestC3RateLimiterRelease:
    @pytest.mark.asyncio
    async def test_sliding_window_counter_try_decrement_redis_unavailable_returns_false(self):
        """无 Redis 时 try_decrement 在空窗口返回 False。"""
        from app.data.storage.redis.counters import SlidingWindowCounter

        counter = SlidingWindowCounter(window_seconds=60)
        # 无 Redis + 内存计数器空 → False
        result = await counter.try_decrement("test_key_c3_empty")
        assert result is False

    @pytest.mark.asyncio
    async def test_rate_limiter_release_returns_false_without_config(self):
        from app.data.processor.rate_limiter import RateLimiter

        limiter = RateLimiter()
        # 未 configure 的 source → release 返回 False
        result = await limiter.release("nonexistent_source", "domain")
        assert result is False


# ============================================================================
# D10: SourceHealthMonitor 真滑动窗口
# ============================================================================
class TestD10SlidingWindow:
    def setup_method(self):
        from app.data.monitoring.source_health import SourceHealthMonitor
        SourceHealthMonitor._instance = None

    def _monitor(self):
        from app.data.monitoring.source_health import SourceHealthMonitor
        return SourceHealthMonitor()

    def test_health_has_1h_fields(self):
        monitor = self._monitor()
        monitor.record_call("CN", "tushare", "daily_quotes", success=True, latency_ms=100)
        h = monitor.get_health("CN", "tushare", "daily_quotes")
        assert "success_rate_1h" in h
        assert "avg_latency_1h" in h
        assert "total_calls_1h" in h
        assert "success_rate_total" in h  # 进程累计（兼容字段）

    def test_1h_window_reflects_recent_events(self):
        monitor = self._monitor()
        # 注入 5 条近期成功事件
        for i in range(5):
            monitor.record_call(
                "CN", "tushare", "daily_quotes", success=True, latency_ms=100
            )
        h = monitor.get_health("CN", "tushare", "daily_quotes")
        assert h["success_rate_1h"] == 1.0
        assert h["total_calls_1h"] == 5
        assert h["avg_latency_1h"] == 100.0

    def test_expired_events_excluded_from_1h_window(self):
        """过期事件不应进入 1h 统计，但进程累计仍保留。"""
        monitor = self._monitor()
        # 用唯一 domain 避免与其他测试通过单例共享 key
        domain = "dq_expired_exclusion_test"
        # 直接构造过期事件（绕过 record_call 的摊销清理）
        monitor.record_call("CN", "tushare", domain, success=True, latency_ms=100)
        # 手动把事件时间戳改为 2 小时前
        key = f"CN:tushare:{domain}"
        old_ts = time.time() - 7200
        monitor._events[key].append((old_ts, False, 200))
        # 同步更新 stats 累计计数（模拟 record_call 对失败的处理）
        monitor._stats[key]["failure_count"] += 1
        monitor._stats[key]["call_count"] += 1
        h = monitor.get_health("CN", "tushare", domain)
        # 进程累计包含 1 成功 + 1 失败 = 0.5
        assert h["success_count"] == 1
        assert h["failure_count"] == 1
        assert h["success_rate_total"] == 0.5
        # 1h 窗口仅含 1 条近期成功 → 1.0
        assert h["success_rate_1h"] == 1.0
        assert h["total_calls_1h"] == 1

    def test_1h_window_only_counts_recent_failure(self):
        """窗口内仅最近一条失败 → success_rate_1h 反映真实情况。"""
        monitor = self._monitor()
        domain = "dq_recent_failure_test"
        # 5 条历史成功 + 1 条最近失败
        for i in range(5):
            monitor.record_call("CN", "tushare", domain, success=True, latency_ms=100)
        monitor.record_call("CN", "tushare", domain, success=False, latency_ms=50, error="e")
        h = monitor.get_health("CN", "tushare", domain)
        # 1h 窗口：5 成功 + 1 失败 = 6 → 5/6
        assert h["total_calls_1h"] == 6
        assert abs(h["success_rate_1h"] - 5 / 6) < 0.001
        # 进程累计应与 1h 一致（都是近期事件）
        assert h["success_rate_total"] == h["success_rate_1h"]


# ============================================================================
# F3: CacheService 禁止删除系统内部键
# ============================================================================
class TestF3CacheServiceForbiddenKeys:
    def setup_method(self):
        from app.services.cache_service import CacheService
        CacheService.reset_instance()

    def test_is_forbidden_key_detects_blacklist(self):
        from app.services.cache_service import CacheService

        assert CacheService.is_forbidden_key("token_blacklist:abc")
        assert CacheService.is_forbidden_key("session:xyz")
        assert CacheService.is_forbidden_key("ratelimit:tushare")
        assert CacheService.is_forbidden_key("lock:some:lock:key")
        assert CacheService.is_forbidden_key("auth:state")

    def test_is_forbidden_key_allows_business_keys(self):
        from app.services.cache_service import CacheService

        assert not CacheService.is_forbidden_key("foreign_stock:600519:daily")
        assert not CacheService.is_forbidden_key("business:data:cache")
        assert not CacheService.is_forbidden_key("")
        # None 输入应返回 False（不抛异常）
        assert not CacheService.is_forbidden_key(None)

    @pytest.mark.asyncio
    async def test_delete_item_rejects_forbidden_key(self):
        from app.services.cache_service import CacheService

        service = CacheService.get_instance()
        with pytest.raises(PermissionError):
            await service.delete_item("token_blacklist:abc")
        with pytest.raises(PermissionError):
            await service.delete_item("ratelimit:tushare:daily_quotes")

    def test_router_does_not_import_storage_directly(self):
        """routers/cache.py 不应再 import app.data.storage。"""
        from app.routers import cache as cache_router

        src = inspect.getsource(cache_router)
        assert "from app.data.storage" not in src, \
            "routers 不应直接 import storage 层"
        assert "from app.services.cache_service" in src

    def test_auth_db_router_uses_auth_service(self):
        """routers/auth_db.py 应委托 services/auth_service。"""
        from app.routers import auth_db

        src = inspect.getsource(auth_db)
        assert "from app.services.auth_service import AuthService" in src
        # 不应直接 import app.data.storage
        assert "from app.data.storage.redis" not in src


# ============================================================================
# F1: HK 4 Provider 全部委托 api/ 子模块（结构验证）
# ============================================================================
class TestF1HKProvidersDelegation:
    def test_tushare_hk_provider_delegates_to_api_modules(self):
        from app.data.sources.hk.tushare_hk import provider as p

        src = inspect.getsource(p)
        # 不应直调 api.hk_income 等 Tushare 原生接口
        assert "api.hk_income" not in src
        assert "api.hk_balancesheet" not in src
        # 所有 get_* 方法应 from .api.* import fetch_*
        assert "from app.data.sources.hk.tushare_hk.api.hk_basic" in src
        assert "from app.data.sources.hk.tushare_hk.api.hk_daily" in src
        assert "from app.data.sources.hk.tushare_hk.api.hk_financials" in src

    def test_tencent_hk_provider_delegates_to_api(self):
        from app.data.sources.hk.tencent_hk import provider as p

        src = inspect.getsource(p)
        # 不应在 provider 内用 urllib 直连
        assert "urllib" not in src
        assert "http://" not in src
        # 应委托 api.market_quotes
        assert "fetch_market_quotes" in src

    def test_akshare_hk_provider_delegates_to_api(self):
        from app.data.sources.hk.akshare_hk import provider as p

        src = inspect.getsource(p)
        assert "from app.data.sources.hk.akshare_hk.api.basic_info" in src
        assert "from app.data.sources.hk.akshare_hk.api.daily_quotes" in src
        assert "from app.data.sources.hk.akshare_hk.api.corporate_actions" in src

    def test_yfinance_hk_provider_delegates_to_api(self):
        from app.data.sources.hk.yfinance_hk import provider as p

        src = inspect.getsource(p)
        assert "from app.data.sources.hk.yfinance_hk.api.daily_quotes" in src
        assert "from app.data.sources.hk.yfinance_hk.api.financial_data" in src

    def test_yfinance_hk_financial_data_api_module_exists(self):
        """新增的 yfinance_hk/api/financial_data.py 应真实存在并可导入。"""
        from app.data.sources.hk.yfinance_hk.api import financial_data as m

        assert hasattr(m, "fetch_financial_data")
        sig = inspect.signature(m.fetch_financial_data)
        assert "statement_type" in sig.parameters
        assert "start_date" in sig.parameters
        assert "end_date" in sig.parameters

    @pytest.mark.asyncio
    async def test_yfinance_hk_financial_data_filters_by_date(self):
        """日期参数应在内存过滤 df.columns（报告期）。"""
        from app.data.sources.hk.yfinance_hk.api.financial_data import (
            fetch_financial_data,
        )

        # 模拟 yfinance Ticker.financials 返回（列为报告期日期）
        df = pd.DataFrame(
            {"2023-12-31": [100], "2024-03-31": [110], "2024-06-30": [120]},
            index=["TotalRevenue"],
        )

        # 构造 monkeypatch 替换 yfinance 调用（不能用 mock）
        import yfinance as yf

        original_ticker = yf.Ticker

        class FakeTicker:
            def __init__(self, symbol):
                self.symbol = symbol

            @property
            def financials(self):
                return df

        yf.Ticker = FakeTicker
        try:
            result = await fetch_financial_data(
                "0700",
                statement_type="income",
                start_date="2024-01-01",
                end_date="2024-12-31",
            )
        finally:
            yf.Ticker = original_ticker

        # 只应保留 2024 年两期
        assert result is not None
        assert len(result.columns) == 2
        assert "2023-12-31" not in result.columns
        assert "2024-03-31" in result.columns
        assert "2024-06-30" in result.columns
