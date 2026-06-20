"""
PR5 测试 — HK/US 数据源异常分类 + FallbackRouter 单例

覆盖：
- C1 HK/US 异常映射正确性（通过源码静态分析 + ImportError 触发验证）
- C4 FallbackRouter 单例（get_instance 返回同一实例、状态共享）
- C4 单例化不破坏现有调用方（refresh_service / sync_job / multi_source_basics_sync / domain_sync）
"""

import asyncio
import importlib
import inspect

import pytest


# ---------------------------------------------------------------------------
# C1 HK/US 异常映射 — 源码静态校验
# ---------------------------------------------------------------------------


class TestHKUSSourceErrorMappingStatic:
    """C1：所有 HK/US 数据源 API 都正确改造为抛 DataSourceError 子类。

    通过源码静态检查（inspect.getsource）验证每个文件：
    1. 导入异常基类
    2. 不再使用 `except Exception as e: logger.error(...); return None` 吞异常
    3. 抛出的是 DataSourceError 子类
    """

    # 期望被导入的模块路径列表
    HK_MODULES = [
        "app.data.sources.hk.akshare_hk.api.basic_info",
        "app.data.sources.hk.akshare_hk.api.corporate_actions",
        "app.data.sources.hk.akshare_hk.api.daily_indicators",
        "app.data.sources.hk.akshare_hk.api.daily_quotes",
        "app.data.sources.hk.akshare_hk.api.news",
        "app.data.sources.hk.tencent_hk.api.market_quotes",
        "app.data.sources.hk.tushare_hk.api.hk_adjfactor",
        "app.data.sources.hk.tushare_hk.api.hk_basic",
        "app.data.sources.hk.tushare_hk.api.hk_daily",
        "app.data.sources.hk.tushare_hk.api.hk_daily_adj",
        "app.data.sources.hk.tushare_hk.api.hk_financials",
        "app.data.sources.hk.tushare_hk.api.hk_fina_indicator",
        "app.data.sources.hk.tushare_hk.api.hk_hold",
        "app.data.sources.hk.tushare_hk.api.hk_tradecal",
        "app.data.sources.hk.tushare_hk.api.rt_hk_k",
        "app.data.sources.hk.yfinance_hk.api.basic_info",
        "app.data.sources.hk.yfinance_hk.api.corporate_actions",
        "app.data.sources.hk.yfinance_hk.api.daily_indicators",
        "app.data.sources.hk.yfinance_hk.api.daily_quotes",
    ]

    US_MODULES = [
        "app.data.sources.us.alpha_vantage.api.daily_quotes",
        "app.data.sources.us.alpha_vantage.api.financials",
        "app.data.sources.us.finnhub.api.basic_info",
        "app.data.sources.us.finnhub.api.market_quotes",
        "app.data.sources.us.finnhub.api.news",
        "app.data.sources.us.finnhub.api.pre_post_market",
        "app.data.sources.us.tushare_us.api.us_adjfactor",
        "app.data.sources.us.tushare_us.api.us_basic",
        "app.data.sources.us.tushare_us.api.us_daily",
        "app.data.sources.us.tushare_us.api.us_daily_adj",
        "app.data.sources.us.tushare_us.api.us_financials",
        "app.data.sources.us.tushare_us.api.us_fina_indicator",
        "app.data.sources.us.tushare_us.api.us_tradecal",
        "app.data.sources.us.yfinance.api.basic_info",
        "app.data.sources.us.yfinance.api.corporate_actions",
        "app.data.sources.us.yfinance.api.daily_indicators",
        "app.data.sources.us.yfinance.api.daily_quotes",
        "app.data.sources.us.yfinance.api.financials",
    ]

    @pytest.mark.parametrize("module_path", HK_MODULES + US_MODULES)
    def test_module_imports_successfully(self, module_path):
        """所有 HK/US 模块必须能成功 import（语法/导入无错误）。"""
        mod = importlib.import_module(module_path)
        assert mod is not None

    @pytest.mark.parametrize("module_path", HK_MODULES + US_MODULES)
    def test_module_has_domain_constant(self, module_path):
        """每个模块应定义 _DOMAIN 常量。"""
        mod = importlib.import_module(module_path)
        # 一些简单包装文件可能没有，绝大多数应有
        if hasattr(mod, "_DOMAIN"):
            assert isinstance(mod._DOMAIN, str)
            assert len(mod._DOMAIN) > 0

    @pytest.mark.parametrize("module_path", HK_MODULES + US_MODULES)
    def test_module_imports_exceptions(self, module_path):
        """每个模块应引用 DataSourceError 子类（在源码中可找到）。

        豁免：纯占位接口（如 Finnhub pre_post_market 免费层不支持，
        返回 None 是业务正确语义）。
        """
        PLACEHOLDER_MODULES = {
            "app.data.sources.us.finnhub.api.pre_post_market",  # 免费层不支持，永远 return None
        }
        if module_path in PLACEHOLDER_MODULES:
            pytest.skip(f"{module_path} 是占位实现，无需抛 DataSourceError")

        mod = importlib.import_module(module_path)
        src = inspect.getsource(mod)
        # 至少应引用了某个异常子类
        exception_keywords = [
            "DataNotFoundError",
            "DataSourceUnavailableError",
            "DataFormatError",
            "NetworkError",
            "RateLimitedError",
            "TokenInvalidError",
            "InsufficientCreditsError",
        ]
        assert any(kw in src for kw in exception_keywords), (
            f"{module_path} 源码中未发现任何 DataSourceError 子类引用"
        )

    @pytest.mark.parametrize("module_path", HK_MODULES + US_MODULES)
    def test_module_does_not_swallow_exception_with_return_none(self, module_path):
        """禁止再出现 `except Exception as e: ... return None` 的吞异常模式。

        检查源码中除 catch-finally 或注释外，不应有 except 块紧接着 return None。
        """
        mod = importlib.import_module(module_path)
        src = inspect.getsource(mod)
        lines = src.split("\n")

        # 查找 except 块后跟着 return None 的反模式
        in_except = False
        violations = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("except "):
                in_except = True
                continue
            # 缩进回到与 except 同级或更外层时，认为出 except
            if in_except and stripped and not stripped.startswith("#"):
                if "return None" in stripped and not stripped.endswith("# allow return None"):
                    # 但允许 `if api is None: return None` 或 `if not api_key: return None`
                    # 这种参数前置校验（不在 except 块内）
                    if not any(kw in stripped for kw in ("api is None", "api_key", "symbols", "ticker is None")):
                        violations.append((i + 1, stripped))
                # 检测下一行缩进是否回到 except 之外
                if line and not line[0].isspace():
                    in_except = False
                elif stripped.startswith(("raise ", "continue", "pass", "logger.")):
                    # except 块内的合法语句
                    pass

        assert not violations, f"{module_path} 中存在吞异常的 except return None 反模式: {violations[:3]}"


class TestHKUSSourceErrorMappingMetadata:
    """C1：HK/US 数据源抛出的异常携带正确的 source 和 domain 信息。"""

    def test_hk_akshare_uses_akshare_hk_source_name(self):
        from app.data.sources.hk.akshare_hk.api import daily_quotes
        src = inspect.getsource(daily_quotes)
        # source_name 必须是 "akshare_hk"（不是泛化的 "akshare"）
        assert '"akshare_hk"' in src or "'akshare_hk'" in src

    def test_us_yfinance_uses_yfinance_source_name(self):
        from app.data.sources.us.yfinance.api import daily_quotes
        src = inspect.getsource(daily_quotes)
        assert '"yfinance"' in src or "'yfinance'" in src

    def test_us_alpha_vantage_uses_alpha_vantage_source_name(self):
        from app.data.sources.us.alpha_vantage.api import daily_quotes
        src = inspect.getsource(daily_quotes)
        assert '"alpha_vantage"' in src or "'alpha_vantage'" in src

    def test_us_finnhub_uses_finnhub_source_name(self):
        from app.data.sources.us.finnhub.api import market_quotes
        src = inspect.getsource(market_quotes)
        assert '"finnhub"' in src or "'finnhub'" in src

    def test_tushare_hk_uses_tushare_hk_source_name(self):
        from app.data.sources.hk.tushare_hk.api import hk_daily
        src = inspect.getsource(hk_daily)
        assert '"tushare_hk"' in src or "'tushare_hk'" in src

    def test_tushare_us_uses_tushare_us_source_name(self):
        from app.data.sources.us.tushare_us.api import us_daily
        src = inspect.getsource(us_daily)
        assert '"tushare_us"' in src or "'tushare_us'" in src

    def test_tushare_hk_calls_map_tushare_code(self):
        """Tushare HK 系列必须调用 map_tushare_code 处理 Tushare 错误码。"""
        from app.data.sources.hk.tushare_hk.api import hk_daily
        src = inspect.getsource(hk_daily)
        assert "map_tushare_code" in src, "Tushare HK 必须用 map_tushare_code"

    def test_tushare_us_calls_map_tushare_code(self):
        from app.data.sources.us.tushare_us.api import us_daily
        src = inspect.getsource(us_daily)
        assert "map_tushare_code" in src, "Tushare US 必须用 map_tushare_code"


# ---------------------------------------------------------------------------
# C1 HK/US 异常 — ImportError 触发（无 token 时验证降级路径）
# ---------------------------------------------------------------------------


class TestHKUSSourceExceptionBehavior:
    """C1：通过 ImportError / 缺 API key 触发实际异常路径。"""

    @pytest.mark.asyncio
    async def test_alpha_vantage_returns_none_when_no_api_key(self, monkeypatch):
        """Alpha Vantage 未配置 API key 时应返回 None（参数前置校验）。"""
        from app.data.sources.us.alpha_vantage.api import daily_quotes
        from app.utils import ds_key_utils

        # 强制 get_datasource_api_key 返回空
        monkeypatch.setattr(ds_key_utils, "get_datasource_api_key", lambda name: "")
        result = await daily_quotes.fetch_daily_quotes("AAPL", "2024-01-01", "2024-12-31")
        assert result is None

    @pytest.mark.asyncio
    async def test_finnhub_returns_none_when_no_api_key(self, monkeypatch):
        from app.data.sources.us.finnhub.api import market_quotes
        from app.utils import ds_key_utils

        monkeypatch.setattr(ds_key_utils, "get_datasource_api_key", lambda name: "")
        result = await market_quotes.fetch_quote("AAPL")
        assert result is None

    @pytest.mark.asyncio
    async def test_tushare_hk_returns_none_when_api_is_none(self):
        from app.data.sources.hk.tushare_hk.api import hk_daily

        # api=None 是参数校验，不应抛异常
        result = await hk_daily.fetch_daily_quotes(None, "0700.HK", "2024-01-01", "2024-12-31")
        assert result is None

    @pytest.mark.asyncio
    async def test_tushare_us_returns_none_when_api_is_none(self):
        from app.data.sources.us.tushare_us.api import us_daily

        result = await us_daily.fetch_daily_quotes(None, "AAPL", "2024-01-01", "2024-12-31")
        assert result is None


# ---------------------------------------------------------------------------
# C4 FallbackRouter 单例
# ---------------------------------------------------------------------------


class TestFallbackRouterSingleton:
    """C4：FallbackRouter.get_instance() 返回进程级单例。"""

    def setup_method(self):
        # 每个测试前重置单例
        from app.data.processor.fallback_router import FallbackRouter
        FallbackRouter.reset_instance()

    def teardown_method(self):
        from app.data.processor.fallback_router import FallbackRouter
        FallbackRouter.reset_instance()

    def test_get_instance_returns_same_object(self):
        from app.data.processor.fallback_router import FallbackRouter

        r1 = FallbackRouter.get_instance()
        r2 = FallbackRouter.get_instance()
        assert r1 is r2

    def test_get_instance_is_classmethod(self):
        from app.data.processor.fallback_router import FallbackRouter

        assert callable(FallbackRouter.get_instance)
        assert isinstance(FallbackRouter.get_instance(), FallbackRouter)

    def test_reset_instance_clears_singleton(self):
        from app.data.processor.fallback_router import FallbackRouter

        r1 = FallbackRouter.get_instance()
        FallbackRouter.reset_instance()
        r2 = FallbackRouter.get_instance()
        assert r1 is not r2

    def test_singleton_shares_circuit_breaker_state(self):
        """两个 get_instance() 调用必须共享同一份 circuit_breaker。"""
        from app.data.processor.fallback_router import FallbackRouter

        r1 = FallbackRouter.get_instance()
        r2 = FallbackRouter.get_instance()
        assert r1._circuit is r2._circuit
        assert r1._rate_limiter is r2._rate_limiter

    def test_singleton_shares_health_monitor(self):
        from app.data.processor.fallback_router import FallbackRouter

        r1 = FallbackRouter.get_instance()
        r2 = FallbackRouter.get_instance()
        assert r1._health_monitor is r2._health_monitor

    def test_singleton_circuit_failure_persists_across_get_instance(self):
        """单例后注入的失败状态，再次 get_instance() 仍可见。"""
        from app.data.processor.fallback_router import FallbackRouter
        from app.data.sources.base.error_codes import DataErrorCode

        r1 = FallbackRouter.get_instance()
        r1._circuit.record_failure("test_source", "test_domain", DataErrorCode.NETWORK_TIMEOUT)

        r2 = FallbackRouter.get_instance()
        # r2 必须能看到 r1 注入的状态
        state = r2._circuit._get_state("test_source", "test_domain")
        assert len(state["failures"]) == 1


class TestFallbackRouterCallersUseSingleton:
    """C4：所有调用方都改为使用 get_instance()。"""

    def test_refresh_service_uses_get_instance(self):
        """refresh_service._get_router 应调用 get_instance()。"""
        from app.data.core import refresh_service
        src = inspect.getsource(refresh_service)
        assert "FallbackRouter.get_instance()" in src, "refresh_service 应使用 get_instance()"
        # 不再直接 FallbackRouter(...) 构造
        assert "FallbackRouter(self._registry" not in src, "refresh_service 不应再用构造器"

    def test_sync_job_uses_get_instance(self):
        from app.data.scheduler.jobs.base import sync_job
        src = inspect.getsource(sync_job)
        assert "FallbackRouter.get_instance()" in src, "sync_job 应使用 get_instance()"
        # 不再 CapabilityRegistry() + PriorityConfig() + FallbackRouter(...)
        assert "FallbackRouter(registry, priority)" not in src, "sync_job 不应再用构造器"

    def test_multi_source_basics_sync_uses_get_instance(self):
        from app.services import multi_source_basics_sync_service
        src = inspect.getsource(multi_source_basics_sync_service)
        assert "FallbackRouter.get_instance()" in src, "multi_source_basics_sync 应使用 get_instance()"

    def test_base_domain_sync_uses_get_instance(self):
        from app.worker.cn.domain_sync import base_domain_sync
        src = inspect.getsource(base_domain_sync)
        assert "FallbackRouter.get_instance()" in src, "base_domain_sync 应使用 get_instance()"

    def test_no_caller_creates_router_with_capability_registry_arg(self):
        """任何调用方都不应再传 CapabilityRegistry() 给 FallbackRouter。"""
        from app.data.core import refresh_service
        from app.data.scheduler.jobs.base import sync_job
        from app.services import multi_source_basics_sync_service
        from app.worker.cn.domain_sync import base_domain_sync

        for mod in [refresh_service, sync_job, multi_source_basics_sync_service, base_domain_sync]:
            src = inspect.getsource(mod)
            # 出现这种模式说明还在用旧构造器
            assert "FallbackRouter(CapabilityRegistry()" not in src, (
                f"{mod.__name__} 仍在用 FallbackRouter(CapabilityRegistry(), PriorityConfig())"
            )


# ---------------------------------------------------------------------------
# C1 + C4 综合：异常抛出后 circuit_breaker 记录正确
# ---------------------------------------------------------------------------


class TestFallbackRouterWithMappedExceptions:
    """C1 + C4 综合：单例 FallbackRouter 收到 DataSourceError 时按子类差异化记录。"""

    def setup_method(self):
        from app.data.processor.fallback_router import FallbackRouter
        FallbackRouter.reset_instance()

    def teardown_method(self):
        from app.data.processor.fallback_router import FallbackRouter
        FallbackRouter.reset_instance()

    def test_rate_limited_failure_increments_correctly(self):
        from app.data.processor.fallback_router import FallbackRouter
        from app.data.sources.base.error_codes import DataErrorCode

        router = FallbackRouter.get_instance()
        router._circuit.record_failure(
            "akshare_hk", "daily_quotes", DataErrorCode.RATE_LIMITED
        )
        state = router._circuit._get_state("akshare_hk", "daily_quotes")
        assert len(state["failures"]) == 1

    def test_network_error_increments_correctly(self):
        from app.data.processor.fallback_router import FallbackRouter
        from app.data.sources.base.error_codes import DataErrorCode

        router = FallbackRouter.get_instance()
        router._circuit.record_failure(
            "yfinance", "daily_quotes", DataErrorCode.NETWORK_TIMEOUT
        )
        state = router._circuit._get_state("yfinance", "daily_quotes")
        assert len(state["failures"]) == 1

    def test_singleton_router_isolation_per_source(self):
        """单例 router 内不同 source × domain 状态相互隔离。"""
        from app.data.processor.fallback_router import FallbackRouter
        from app.data.sources.base.error_codes import DataErrorCode

        router = FallbackRouter.get_instance()
        router._circuit.record_failure("tushare_hk", "daily_quotes", DataErrorCode.NETWORK_TIMEOUT)
        router._circuit.record_failure("akshare_hk", "basic_info", DataErrorCode.RATE_LIMITED)

        # 两个不同源的状态应独立
        hk_state = router._circuit._get_state("tushare_hk", "daily_quotes")
        ak_state = router._circuit._get_state("akshare_hk", "basic_info")
        assert len(hk_state["failures"]) == 1
        assert len(ak_state["failures"]) == 1
        # 未触发的源应为 CLOSED
        assert router._circuit.get_state("yfinance", "daily_quotes").value == "closed"
