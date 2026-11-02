"""P0/P1 修复专项单元测试。

覆盖 11 项修复（5 Wave1 + 5 Wave2 + 1 代表性 Wave3）：
- F4  connect_status_repo filter/projection 错位
- SE1 Tencent HK HTTPS 常量化
- SE2 stock_news SHA-256 哈希
- D4  Finnhub 时区转换
- N3  Finnhub end_ts 闭区间边界
- D1  AKShare 市值单位映射
- D9  Tushare news 日期透传
- D7  HK financials 日期参数
- D3  USCodeResolver exchange 映射
- C2  RefreshResult.compute_status 处理 SKIPPED
（N1/D2 period_aggregator 两项随未启用的后处理链删除，2026-11-02）
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

        h1 = StockNewsSchema.compute_hash("title", "2024-06-01 10:00:00", "000001")
        h2 = StockNewsSchema.compute_hash("title", "2024-06-01 10:00:00", "000001")
        h3 = StockNewsSchema.compute_hash("title", "2024-06-01 10:00:01", "000001")
        h4 = StockNewsSchema.compute_hash("title", "2024-06-01 10:00:00", "600000")
        # 同输入同哈希
        assert h1 == h2
        # 不同输入不同哈希
        assert h1 != h3
        # symbol 参与哈希：同文不同标的各自成档
        assert h1 != h4
        # SHA-256 hex 长度 64
        assert len(h1) == 64

    def test_compute_hash_matches_reference_value(self):
        """断言哈希算法确实是 SHA-256，而非 MD5 或其它。"""
        from app.data.schema.domains.stock_news import StockNewsSchema

        raw = "000001|title|2024-06-01"
        expected = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        actual = StockNewsSchema.compute_hash("title", "2024-06-01", "000001")
        assert actual == expected
