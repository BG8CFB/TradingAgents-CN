"""看板 / 质量概览短 TTL 缓存的守卫测试。

这两个接口单次调用要跨 13 个数据域查询，且页面会同时打它们；加缓存后必须保证
**不串数据**（三市场、不同域集合各自独立），并且过期后确实重算。
"""

from __future__ import annotations

import pytest

from app.services import data_dashboard_service as dash
from app.services import data_quality_service as quality


@pytest.fixture(autouse=True)
def _clear_caches():
    dash._dashboard_cache.clear()
    quality._quality_cache.clear()
    yield
    dash._dashboard_cache.clear()
    quality._quality_cache.clear()


def _counting_builder(calls: list):
    async def build(*args):
        calls.append(args)
        return {"args": args}

    return build


class TestDashboardCache:
    @pytest.mark.asyncio
    async def test_second_call_within_ttl_is_served_from_cache(self, monkeypatch):
        calls: list = []
        monkeypatch.setattr(dash, "_build_dashboard_payload", _counting_builder(calls))

        first = await dash.get_dashboard_payload("CN")
        second = await dash.get_dashboard_payload("CN")

        assert first == second
        assert len(calls) == 1, "TTL 内重复调用不应重复组装载荷"

    @pytest.mark.asyncio
    async def test_cache_is_partitioned_by_market(self, monkeypatch):
        calls: list = []
        monkeypatch.setattr(dash, "_build_dashboard_payload", _counting_builder(calls))

        await dash.get_dashboard_payload("CN")
        await dash.get_dashboard_payload("HK")

        assert calls == [("CN",), ("HK",)], "不同市场必须各自缓存，否则串数据"

    @pytest.mark.asyncio
    async def test_expired_entry_is_rebuilt(self, monkeypatch):
        calls: list = []
        monkeypatch.setattr(dash, "_build_dashboard_payload", _counting_builder(calls))
        dash._dashboard_cache["CN"] = (0.0, {"stale": True})  # 过期时间戳

        payload = await dash.get_dashboard_payload("CN")

        assert payload != {"stale": True}, "过期条目必须重算"
        assert len(calls) == 1

    def test_ttl_is_bounded(self):
        """TTL 必须是个短窗口：看板反映同步状态，不能长期陈旧。"""
        assert 0 < dash._DASHBOARD_TTL_SECONDS <= 300


class TestQualityCache:
    @pytest.mark.asyncio
    async def test_key_includes_market_and_domains(self, monkeypatch):
        calls: list = []
        monkeypatch.setattr(quality, "_build_quality_overview", _counting_builder(calls))

        await quality.get_quality_overview("CN", ["daily_quotes"])
        await quality.get_quality_overview("CN", ["daily_quotes"])  # 命中缓存
        await quality.get_quality_overview("HK", ["daily_quotes"])  # 换市场 → 重算
        await quality.get_quality_overview("CN", ["adj_factors"])  # 换域集合 → 重算

        assert len(calls) == 3, "键必须含 market 与 domains，否则跨市场/跨域集合串数据"
        assert calls == [
            ("CN", ["daily_quotes"]),
            ("HK", ["daily_quotes"]),
            ("CN", ["adj_factors"]),
        ]
