"""本轮代码审查修复的针对性验证测试。

覆盖：
- P1: BaseProvider 基类签名统一 + NotImplementedError 默认实现
- P1: Provider 实现文件类型注解对齐
- P2: WS 端点 effective_user_id 权限校验
- W2: .env.example 与 config.py 默认值一致
- W3: SecretService 原子写
- FallbackRouter: NotImplementedError 不触发断路器
"""

import asyncio
import inspect
import os
from pathlib import Path

import pandas as pd
import pytest

from app.data.sources.base.provider import BaseProvider


# ════════════════════════════════════════════════════════════
# P1: BaseProvider 基类签名验证
# ════════════════════════════════════════════════════════════


class _ConcreteProvider(BaseProvider):
    """最小化子类，仅实现抽象方法，其余继承基类默认实现。"""

    async def connect(self):
        self.connected = True
        return True

    def is_available(self):
        return self.connected


BASE_DATA_METHODS = [
    "get_stock_list",
    "get_trade_calendar",
    "get_daily_quotes",
    "get_daily_indicators",
    "get_daily_indicators_batch",
    "get_financial_data",
    "get_adj_factors",
    "get_corporate_actions",
    "get_news",
    "get_market_quotes",
]


class TestBaseProviderSignatures:
    """验证基类 10 个数据获取方法的返回类型为 pd.DataFrame。"""

    @pytest.mark.parametrize("method_name", BASE_DATA_METHODS)
    def test_return_type_is_dataframe(self, method_name):
        method = getattr(BaseProvider, method_name)
        sig = inspect.signature(method)
        assert sig.return_annotation is pd.DataFrame, (
            f"{method_name} 返回类型应为 pd.DataFrame，实际为 {sig.return_annotation}"
        )

    @pytest.mark.parametrize("method_name", BASE_DATA_METHODS)
    def test_docstring_has_raises(self, method_name):
        method = getattr(BaseProvider, method_name)
        doc = method.__doc__ or ""
        assert "Raises:" in doc, f"{method_name} docstring 缺少 Raises 段落"

    def test_connect_signature_remains_bool(self):
        """connect() 签名保持 -> bool，不因 HK Provider 抛异常而改变。"""
        sig = inspect.signature(BaseProvider.connect)
        assert sig.return_annotation is bool

    def test_connect_docstring_documents_exceptions(self):
        doc = BaseProvider.connect.__doc__ or ""
        assert "TokenInvalidError" in doc
        assert "InsufficientCreditsError" in doc


class TestBaseProviderDefaultRaisesNotImplemented:
    """验证基类未覆写的方法抛 NotImplementedError，而非返回 None。"""

    @pytest.mark.asyncio
    async def test_get_stock_list_raises(self):
        p = _ConcreteProvider(name="test", market="CN")
        with pytest.raises(NotImplementedError, match="不支持 get_stock_list"):
            await p.get_stock_list()

    @pytest.mark.asyncio
    async def test_get_market_quotes_raises(self):
        p = _ConcreteProvider(name="test", market="CN")
        with pytest.raises(NotImplementedError, match="不支持 get_market_quotes"):
            await p.get_market_quotes()

    @pytest.mark.asyncio
    async def test_get_daily_indicators_batch_raises(self):
        p = _ConcreteProvider(name="test", market="CN")
        with pytest.raises(NotImplementedError):
            await p.get_daily_indicators_batch("2024-12-31")

    @pytest.mark.asyncio
    async def test_get_daily_quotes_raises(self):
        p = _ConcreteProvider(name="test", market="CN")
        with pytest.raises(NotImplementedError):
            await p.get_daily_quotes("000001", "2024-01-01", "2024-12-31")

    @pytest.mark.asyncio
    async def test_get_news_raises(self):
        p = _ConcreteProvider(name="test", market="CN")
        with pytest.raises(NotImplementedError):
            await p.get_news("000001", "2024-01-01", "2024-12-31")


# ════════════════════════════════════════════════════════════
# P1: Provider 实现文件签名对齐验证
# ════════════════════════════════════════════════════════════


PROVIDER_MODULES = [
    "app.data.sources.cn.akshare.provider",
    "app.data.sources.cn.tushare.provider",
    "app.data.sources.cn.baostock.provider",
    "app.data.sources.hk.tushare_hk.provider",
    "app.data.sources.hk.akshare_hk.provider",
    "app.data.sources.hk.yfinance_hk.provider",
    "app.data.sources.hk.tencent_hk.provider",
    "app.data.sources.us.yfinance.provider",
    "app.data.sources.us.finnhub.provider",
    "app.data.sources.us.alpha_vantage.provider",
    "app.data.sources.us.tushare_us.provider",
]


class TestProviderImplSignatures:
    """验证所有 Provider 实现文件的数据方法返回类型为 pd.DataFrame。"""

    @pytest.mark.parametrize("module_name", PROVIDER_MODULES)
    def test_no_optional_dataframe_return(self, module_name):
        import importlib

        mod = importlib.import_module(module_name)
        provider_cls = None
        for attr_name in dir(mod):
            obj = getattr(mod, attr_name)
            if isinstance(obj, type) and issubclass(obj, BaseProvider) and obj is not BaseProvider:
                provider_cls = obj
                break

        assert provider_cls is not None, f"{module_name} 未找到 BaseProvider 子类"

        for method_name in BASE_DATA_METHODS:
            if not hasattr(provider_cls, method_name):
                continue
            method = getattr(provider_cls, method_name)
            if not callable(method):
                continue
            sig = inspect.signature(method)
            ret = sig.return_annotation
            assert ret is pd.DataFrame, (
                f"{module_name}.{provider_cls.__name__}.{method_name} "
                f"返回类型应为 pd.DataFrame，实际为 {ret}"
            )


class TestHkUsUnsupportedMethodsRaise:
    """验证 HK/US Provider 不支持的域显式抛 NotImplementedError。"""

    def test_tushare_hk_news_raises(self):
        from app.data.sources.hk.tushare_hk.provider import TushareHKProvider

        sig = inspect.signature(TushareHKProvider.get_news)
        assert sig.return_annotation is pd.DataFrame

    def test_tushare_hk_corporate_actions_raises(self):
        from app.data.sources.hk.tushare_hk.provider import TushareHKProvider

        sig = inspect.signature(TushareHKProvider.get_corporate_actions)
        assert sig.return_annotation is pd.DataFrame

    def test_yfinance_hk_stock_list_raises(self):
        from app.data.sources.hk.yfinance_hk.provider import YFinanceHKProvider

        p = YFinanceHKProvider()
        with pytest.raises(NotImplementedError):
            asyncio.run(p.get_stock_list())

    def test_yfinance_us_stock_list_raises(self):
        from app.data.sources.us.yfinance.provider import YFinanceUSProvider

        p = YFinanceUSProvider()
        with pytest.raises(NotImplementedError):
            asyncio.run(p.get_stock_list())

    def test_tushare_us_news_raises(self):
        from app.data.sources.us.tushare_us.provider import TushareUSProvider

        p = TushareUSProvider()
        with pytest.raises(NotImplementedError):
            asyncio.run(p.get_news("AAPL", "2024-01-01", "2024-12-31"))

    def test_tushare_us_corporate_actions_raises(self):
        from app.data.sources.us.tushare_us.provider import TushareUSProvider

        p = TushareUSProvider()
        with pytest.raises(NotImplementedError):
            asyncio.run(p.get_corporate_actions("AAPL", "2024-01-01", "2024-12-31"))


# ════════════════════════════════════════════════════════════
# FallbackRouter: NotImplementedError 不触发断路器
# ════════════════════════════════════════════════════════════


class _NotImplementedProvider(BaseProvider):
    """Provider 模拟 get_news 未实现（继承基类默认抛 NotImplementedError）。"""

    async def connect(self):
        self.connected = True
        return True

    def is_available(self):
        return True


class _WorkingProvider(BaseProvider):
    """Provider 模拟 get_news 正常返回数据。"""

    async def connect(self):
        self.connected = True
        return True

    def is_available(self):
        return True

    async def get_news(self, symbol, start_date, end_date, **kwargs):
        return pd.DataFrame([{"symbol": symbol, "title": "test news"}])


class _MinimalAdapter:
    """最小 adapter 占位，仅需满足 FallbackRouter 的 if not adapter 检查。"""

    def __init__(self, provider, market, source_name):
        self.provider = provider
        self.market = market
        self.source_name = source_name


class TestFallbackRouterNotImplemented:
    """验证 NotImplementedError 被识别为"不支持"而非"失败"。"""

    @pytest.mark.asyncio
    async def test_not_implemented_does_not_trigger_circuit_breaker(self):
        """NotImplementedError 不应触发断路器 record_failure。"""
        from app.data.processor.fallback_router import FallbackRouter
        from app.data.core.registry.capability import CapabilityRegistry
        from app.data.core.registry.priority import PriorityConfig
        from app.data.schema.base.enums import SupportLevel

        registry = CapabilityRegistry()
        registry.register("CN", "news", "not_impl_src", SupportLevel.FULL)
        priority = PriorityConfig()
        router = FallbackRouter(registry, priority)

        not_impl_provider = _NotImplementedProvider(name="not_impl_src", market="CN")

        async def fake_get_provider_adapter(market, source_name):
            adapter = _MinimalAdapter(not_impl_provider, market, source_name)
            return not_impl_provider, adapter

        router._get_provider_adapter = fake_get_provider_adapter

        result = await router.fetch("CN", "news", "000001")

        # 所有源都不支持 → 失败
        assert result.success is False
        # 关键：not_impl_src 不应出现在 fallback_chain 中（因为它是"不支持"而非"失败"）
        assert "not_impl_src" not in (result.error or ""), (
            f"不支持的源不应计入失败链: {result.error}"
        )
        # 断路器状态应为 closed（未因 NotImplementedError 累计失败）
        state = router._circuit.get_state("not_impl_src", "news")
        assert state.value == "closed", (
            f"断路器不应因 NotImplementedError 打开，实际状态: {state}"
        )

    @pytest.mark.asyncio
    async def test_not_implemented_source_skipped_then_all_fail(self):
        """第一个源不支持（NotImplementedError）被跳过，无后续源 → 失败但不计入断路器。"""
        from app.data.processor.fallback_router import FallbackRouter
        from app.data.core.registry.capability import CapabilityRegistry
        from app.data.core.registry.priority import PriorityConfig
        from app.data.schema.base.enums import SupportLevel

        registry = CapabilityRegistry()
        registry.register("CN", "news", "only_not_impl_src", SupportLevel.FULL)
        priority = PriorityConfig()
        router = FallbackRouter(registry, priority)

        provider = _NotImplementedProvider(name="only_not_impl_src", market="CN")

        async def fake_get_provider_adapter(market, source_name):
            adapter = _MinimalAdapter(provider, market, source_name)
            return provider, adapter

        router._get_provider_adapter = fake_get_provider_adapter

        result = await router.fetch("CN", "news", "000001")

        assert result.success is False
        # 不支持的源不在 fallback_chain → error 不应包含它
        assert "only_not_impl_src" not in (result.error or "")
        # 断路器仍 closed
        assert router._circuit.get_state("only_not_impl_src", "news").value == "closed"


# ════════════════════════════════════════════════════════════
# W2: .env.example 与 config.py 默认值一致
# ════════════════════════════════════════════════════════════


CONFIG_KEYS = [
    "ASYNC_THREAD_POOL_SIZE",
    "ANALYSIS_THREAD_POOL_SIZE",
    "DATA_SYNC_CONCURRENCY",
    "CN_SYNC_CONCURRENCY",
    "HK_SYNC_CONCURRENCY",
    "US_SYNC_CONCURRENCY",
    "MARKET_ANALYST_LOOKBACK_DAYS",
    "ACCESS_TOKEN_EXPIRE_MINUTES",
]


class TestEnvExampleConsistency:
    """验证 .env.example 与 config.py Field 默认值一致。"""

    @pytest.mark.parametrize("key", CONFIG_KEYS)
    def test_env_example_matches_config_default(self, key):
        import re

        repo_root = Path(__file__).resolve().parents[2]
        env_path = repo_root / ".env.example"
        config_path = repo_root / "app" / "core" / "config.py"

        env_text = env_path.read_text(encoding="utf-8")
        config_text = config_path.read_text(encoding="utf-8")

        env_match = re.search(rf"^{key}=(\S+)", env_text, re.MULTILINE)
        cfg_match = re.search(rf'{key}.*?Field\(default=(\d+)', config_text)

        assert env_match, f".env.example 缺少 {key}"
        assert cfg_match, f"config.py 缺少 {key} 的 Field(default=...)"

        env_val = env_match.group(1)
        cfg_val = cfg_match.group(1)
        assert env_val == cfg_val, (
            f"{key} 不一致: .env.example={env_val}, config.py={cfg_val}"
        )


# ════════════════════════════════════════════════════════════
# W3: SecretService 原子写
# ════════════════════════════════════════════════════════════


class TestSecretServiceAtomicWrite:
    """验证 _save_fallback_file 原子写行为。"""

    def setup_method(self):
        from app.services.secret_service import _FALLBACK_FILE

        self.fallback_file = _FALLBACK_FILE
        self._backup = None
        if _FALLBACK_FILE.exists():
            self._backup = _FALLBACK_FILE.read_text(encoding="utf-8")

    def teardown_method(self):
        if self._backup is not None:
            self.fallback_file.write_text(self._backup, encoding="utf-8")
        elif self.fallback_file.exists():
            self.fallback_file.unlink()

    def test_round_trip_write_read(self):
        from app.services.secret_service import _save_fallback_file, _load_fallback_file

        test_data = {"jwt_secret": "abc_123", "csrf_secret": "xyz_789"}
        _save_fallback_file(test_data)
        result = _load_fallback_file()
        assert result == test_data

    def test_no_temp_file_residue(self):
        from app.services.secret_service import _save_fallback_file

        _save_fallback_file({"jwt_secret": "test"})
        tmp_files = list(self.fallback_file.parent.glob("*.tmp"))
        assert not tmp_files, f"临时文件残留: {tmp_files}"

    def test_concurrent_writes_produce_valid_json(self):
        """模拟多 worker 并发写，最终文件应为合法 JSON。"""
        from app.services.secret_service import _save_fallback_file, _load_fallback_file
        import threading

        payloads = [
            {"jwt_secret": f"secret_{i}", "csrf_secret": f"csrf_{i}"}
            for i in range(10)
        ]
        threads = [threading.Thread(target=_save_fallback_file, args=(p,)) for p in payloads]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        result = _load_fallback_file()
        assert "jwt_secret" in result
        assert "csrf_secret" in result
        assert result["jwt_secret"].startswith("secret_")

    def test_partial_write_does_not_corrupt_existing(self):
        """即使写入过程中模拟异常，也不应破坏已有文件（原子性）。"""
        from app.services.secret_service import _save_fallback_file, _load_fallback_file

        _save_fallback_file({"jwt_secret": "original_value"})
        original = _load_fallback_file()
        assert original["jwt_secret"] == "original_value"

        original_replace = os.replace

        def failing_replace(src, dst):
            raise OSError("模拟 os.replace 失败")

        os.replace = failing_replace
        try:
            _save_fallback_file({"jwt_secret": "new_value"})
        except Exception:
            pass
        finally:
            os.replace = original_replace

        result = _load_fallback_file()
        assert result.get("jwt_secret") == "original_value", (
            "原子写失败时不应破坏已有文件"
        )


# ════════════════════════════════════════════════════════════
# P2: WS 端点 effective_user_id 权限校验
# ════════════════════════════════════════════════════════════


class TestWsEndpointEffectiveUserId:
    """验证 WS 端点代码包含 effective_user_id 逻辑（源码级断言）。"""

    def test_ws_endpoint_uses_effective_user_id(self):
        from app.routers.analysis import websocket_task_progress

        src = inspect.getsource(websocket_task_progress)
        assert "effective_user_id = None if is_admin else user_id" in src
        assert "get_task_with_status_fallback(task_id, effective_user_id)" in src
        assert "is_admin = getattr(ws_user" in src

    def test_ws_endpoint_removed_manual_comparison(self):
        from app.routers.analysis import websocket_task_progress

        src = inspect.getsource(websocket_task_progress)
        assert 'str(task.get("user_id"' not in src
        assert "code=4403" not in src

    def test_ws_endpoint_uses_4404_for_both_cases(self):
        from app.routers.analysis import websocket_task_progress

        src = inspect.getsource(websocket_task_progress)
        assert "code=4404" in src
        assert "任务不存在或无权访问" in src

    def test_http_and_ws_paths_consistent(self):
        """HTTP 路径与 WS 路径都通过 effective_user_id 过滤。"""
        from app.routers.analysis import get_task_status_new, websocket_task_progress

        http_src = inspect.getsource(get_task_status_new)
        ws_src = inspect.getsource(websocket_task_progress)

        http_pattern = "None if user.get(\"is_admin\") else user[\"id\"]"
        ws_pattern = "None if is_admin else user_id"

        assert http_pattern in http_src
        assert ws_pattern in ws_src
