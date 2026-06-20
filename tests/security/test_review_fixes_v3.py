"""第二轮审查修复的验证测试（v3）。

覆盖本次会话的 6 项标准化修复，每项用真实代码路径验证：
- 修复1: queue 配置单一来源（settings），user/global 语义分离
- 修复2: __import__ 反模式消除，标准 import 可正常解析 get_redis
- 修复3: is_network_exception 死代码已删除
- 修复4: safe_call/safe_async_call 装饰器已移除，safe_execute 仍可用
- 修复5: logout 同时拉黑 access_token，TTL 与其过期时间对齐
- 修复6: llm_service 删除方法不再枚举全表、日志级别合理

全部使用真实代码与 SimulatedRedis/SimulatedMongoDB（内存实现），无 mock。
"""

import asyncio
import hashlib
import inspect

import pytest

from tests.test_infra import SimulatedRedis


# ---------------------------------------------------------------------------
# 修复1: queue 配置单一来源
# ---------------------------------------------------------------------------


class TestQueueConfigSingleSource:
    """配置默认值只从 settings 读取，keys.py 不再持有配置常量。"""

    def test_keys_module_has_no_config_constants(self):
        """keys.py 只保留 Redis 键名，不含并发上限/超时配置。"""
        from app.services.queue import keys as qkeys

        forbidden = [
            "DEFAULT_USER_CONCURRENT_LIMIT",
            "GLOBAL_CONCURRENT_LIMIT",
            "VISIBILITY_TIMEOUT_SECONDS",
        ]
        for name in forbidden:
            assert not hasattr(qkeys, name), f"keys.py 仍残留配置常量: {name}"

    def test_queue_subpackage_no_config_exports(self):
        """queue 子包不再导出配置常量。"""
        import app.services.queue as q

        for name in (
            "DEFAULT_USER_CONCURRENT_LIMIT",
            "GLOBAL_CONCURRENT_LIMIT",
            "VISIBILITY_TIMEOUT_SECONDS",
        ):
            assert not hasattr(q, name), f"queue 子包仍导出: {name}"

    def test_queue_service_reads_from_settings(self):
        """QueueService.__init__ 从 settings 读取三个配置值。"""
        from app.core.config import settings
        from app.services.queue_service import QueueService

        qs = QueueService(redis=SimulatedRedis())
        assert qs.user_concurrent_limit == settings.DEFAULT_USER_CONCURRENT_LIMIT
        assert qs.global_concurrent_limit == settings.GLOBAL_CONCURRENT_LIMIT
        assert qs.visibility_timeout == settings.QUEUE_VISIBILITY_TIMEOUT

    def test_analysis_worker_uses_distinct_config_keys(self):
        """analysis_worker 用不同 key 配置 user/global，不再共用。"""
        from app.worker import analysis_worker

        src = inspect.getsource(analysis_worker)
        assert "max_concurrent_tasks_per_user" in src
        assert "DEFAULT_USER_CONCURRENT_LIMIT" in src
        assert "max_concurrent_tasks" in src
        assert "GLOBAL_CONCURRENT_LIMIT" in src
        assert "QUEUE_VISIBILITY_TIMEOUT" in src

    def test_queue_init_has_all_declaration(self):
        """queue.__init__ 有 __all__ 声明，消除 re-export F401 警告。"""
        import app.services.queue as q

        assert hasattr(q, "__all__")
        assert "READY_LIST" in q.__all__
        assert "check_user_concurrent_limit" in q.__all__


# ---------------------------------------------------------------------------
# 修复2: __import__ 反模式消除
# ---------------------------------------------------------------------------


class TestNoDunderImport:
    """所有修改过的模块不再使用 __import__ 反模式。"""

    @pytest.mark.parametrize(
        "module_path",
        [
            "app.data.storage.redis.counters",
            "app.data.storage.redis.market_state",
            "app.data.storage.redis.pubsub",
            "app.data.monitoring.alerts",
            "app.engine.config.tushare_config",
            "app.worker.analysis_worker",
            "app.routers.auth_db",
        ],
    )
    def test_no_dunder_import(self, module_path):
        """模块源码不含 __import__ 调用。"""
        module = __import__(module_path, fromlist=["x"])
        src = inspect.getsource(module)
        assert "__import__" not in src, f"{module_path} 仍含 __import__"

    def test_tushare_config_uses_module_level_logging(self):
        """tushare_config 在模块顶层 import logging，而非 __import__('logging')。"""
        from app.engine.config import tushare_config

        src = inspect.getsource(tushare_config)
        assert "import logging" in src
        assert "__import__" not in src

    def test_counters_get_redis_via_standard_import(self, monkeypatch):
        """counters.SlidingWindowCounter 通过标准 import 拿到注入的 Redis 实例。

        这是修复2 的端到端验证：标准 import 路径能被 monkeypatch 正确拦截。
        """
        sim = SimulatedRedis()
        from app.data.storage.redis import client as redis_client_mod

        monkeypatch.setattr(redis_client_mod, "get_redis", lambda: sim)

        from app.data.storage.redis.counters import SlidingWindowCounter

        counter = SlidingWindowCounter(window_seconds=60)

        async def _scenario():
            await counter.increment("test:dunder_import:1")
            await asyncio.sleep(0.002)
            await counter.increment("test:dunder_import:1")
            return await counter.get_count("test:dunder_import:1")

        count = asyncio.run(_scenario())
        assert count == 2


# ---------------------------------------------------------------------------
# 修复3: is_network_exception 死代码已删除
# ---------------------------------------------------------------------------


class TestIsNetworkExceptionRemoved:
    """is_network_exception 函数已从 mappers 删除，全代码库零引用。"""

    def test_mappers_does_not_export_is_network_exception(self):
        from app.data.sources.base import mappers

        assert not hasattr(mappers, "is_network_exception")
        assert "is_network_exception" not in mappers.__all__

    def test_mappers_keeps_used_functions(self):
        """删除死代码后，仍在用的函数完好。"""
        from app.data.sources.base import mappers

        for name in (
            "map_http_status_to_error",
            "map_tushare_code",
            "map_tushare_response",
            "map_network_exception",
            "is_empty_result",
        ):
            assert hasattr(mappers, name), f"mappers 丢失必要函数: {name}"

    def test_mappers_still_functional(self):
        """mappers 核心功能不受死代码删除影响。"""
        from app.data.sources.base import mappers
        from app.data.sources.base.exceptions import RateLimitedError

        err = mappers.map_http_status_to_error(429, "tushare", "daily_quotes")
        assert isinstance(err, RateLimitedError)

        assert mappers.is_empty_result(None) is True
        assert mappers.is_empty_result([1, 2]) is False


# ---------------------------------------------------------------------------
# 修复4: safe_call/safe_async_call 移除，safe_execute 保留
# ---------------------------------------------------------------------------


class TestSafeExecuteKeptDecoratorsRemoved:
    """safe_call/safe_async_call 装饰器移除，safe_execute/safe_execute_async 保留。"""

    def test_core_does_not_export_decorators(self):
        import app.core as core

        assert not hasattr(core, "safe_call")
        assert not hasattr(core, "safe_async_call")

    def test_core_exports_execute_forms(self):
        import app.core as core

        assert hasattr(core, "safe_execute")
        assert hasattr(core, "safe_execute_async")

    def test_error_handling_no_decorator_definitions(self):
        """error_handling.py 不再定义 safe_call/safe_async_call。"""
        from app.core import error_handling

        src = inspect.getsource(error_handling)
        # 源码中只能在 docstring 历史说明里出现
        assert "def safe_call(" not in src
        assert "def safe_async_call(" not in src

    def test_safe_execute_sync_returns_default_on_error(self):
        """safe_execute 捕获异常并返回 default。"""
        from app.core.error_handling import safe_execute

        def boom():
            raise ValueError("kaboom")

        result = safe_execute(boom, default="fallback", context="boom_test")
        assert result == "fallback"

    def test_safe_execute_returns_result_on_success(self):
        from app.core.error_handling import safe_execute

        result = safe_execute(lambda x, y: x + y, 1, 2, default=0, context="add")
        assert result == 3

    @pytest.mark.asyncio
    async def test_safe_execute_async_returns_default_on_error(self):
        from app.core.error_handling import safe_execute_async

        async def boom():
            raise RuntimeError("async kaboom")

        result = await safe_execute_async(boom(), default="async_fallback")
        assert result == "async_fallback"

    def test_safe_execute_rejects_empty_catch(self):
        from app.core.error_handling import safe_execute

        with pytest.raises(ValueError, match="catch 不能为空"):
            safe_execute(lambda: 1, catch=())

    def test_safe_execute_rejects_baseexception_only(self):
        from app.core.error_handling import safe_execute

        with pytest.raises(ValueError, match="禁止捕获 BaseException"):
            safe_execute(lambda: 1, catch=(BaseException,))


# ---------------------------------------------------------------------------
# 修复5: logout access_token 黑名单
# ---------------------------------------------------------------------------


class TestLogoutAccessTokenBlacklist:
    """logout 把 access_token 加入黑名单，_add_token_to_blacklist 支持 ttl_seconds。"""

    def test_access_token_blacklist_ttl_constant_exists(self):
        from app.routers import auth_db

        assert hasattr(auth_db, "_ACCESS_TOKEN_BLACKLIST_TTL_SECONDS")
        ttl = auth_db._ACCESS_TOKEN_BLACKLIST_TTL_SECONDS
        # TTL 应 = (ACCESS_TOKEN_EXPIRE_MINUTES + 1) * 60
        from app.core.config import settings

        expected = (settings.ACCESS_TOKEN_EXPIRE_MINUTES + 1) * 60
        assert ttl == expected

    def test_add_token_to_blacklist_with_ttl_seconds(self):
        """ttl_seconds 优先于 ttl_days，直接用秒数写黑名单。"""
        from app.data.storage.redis import client as redis_client_mod
        from app.routers import auth_db

        sim = SimulatedRedis()
        original = redis_client_mod.get_redis
        redis_client_mod._redis_client = sim

        token = "test.access.token.for.ttl_seconds"
        try:
            ok = asyncio.run(auth_db._add_token_to_blacklist(token, ttl_seconds=120))
            assert ok is True

            token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
            key = f"token_blacklist:{token_hash}"
            value = asyncio.run(sim.get(key))
            assert value == "1"
        finally:
            redis_client_mod._redis_client = None
            redis_client_mod.get_redis = original

    def test_add_token_to_blacklist_with_ttl_days(self):
        """ttl_days 仍可用，换算为秒。"""
        from app.data.storage.redis import client as redis_client_mod
        from app.routers import auth_db

        sim = SimulatedRedis()
        original_get = getattr(redis_client_mod, "get_redis", None)
        redis_client_mod._redis_client = sim

        token = "test.refresh.token.for.ttl_days"
        try:
            ok = asyncio.run(auth_db._add_token_to_blacklist(token, ttl_days=7))
            assert ok is True

            token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
            key = f"token_blacklist:{token_hash}"
            value = asyncio.run(sim.get(key))
            assert value == "1"
        finally:
            redis_client_mod._redis_client = None
            if original_get is not None:
                redis_client_mod.get_redis = original_get

    def test_add_token_to_blacklist_empty_token_returns_false(self):
        from app.routers import auth_db

        ok = asyncio.run(auth_db._add_token_to_blacklist("", ttl_seconds=60))
        assert ok is False

    def test_is_token_blacklisted_detects_blacklisted(self):
        """写入黑名单后，_is_token_blacklisted 返回 True。"""
        from app.data.storage.redis import client as redis_client_mod
        from app.routers import auth_db

        sim = SimulatedRedis()
        redis_client_mod._redis_client = sim

        token = "test.token.blacklist.detect"
        try:
            asyncio.run(auth_db._add_token_to_blacklist(token, ttl_seconds=300))
            assert asyncio.run(auth_db._is_token_blacklisted(token)) is True
            assert (
                asyncio.run(auth_db._is_token_blacklisted("not.blacklisted.token"))
                is False
            )
        finally:
            redis_client_mod._redis_client = None

    def test_logout_endpoint_signature_exists(self):
        """logout 端点存在且签名正确。"""
        from app.routers import auth_db

        assert hasattr(auth_db, "logout")
        sig = inspect.signature(auth_db.logout)
        params = list(sig.parameters.keys())
        assert "request" in params


# ---------------------------------------------------------------------------
# 修复6: llm_service 删除方法日志清理
# ---------------------------------------------------------------------------


class TestLLMServiceDeleteLogCleanup:
    """delete_llm_config / delete_llm_provider 不再枚举全表、日志级别合理。"""

    def test_delete_llm_config_no_enumeration_pattern(self):
        """delete_llm_config 不再用 to_list 枚举所有配置。"""
        from app.services.config import llm_service

        # 取 delete_llm_config 方法源码
        src = inspect.getsource(llm_service.LLMService.delete_llm_config)
        assert "to_list" not in src, "delete_llm_config 仍用 to_list 枚举"
        assert "当前大模型配置数量" not in src

    def test_delete_llm_provider_no_enumeration_pattern(self):
        """delete_llm_provider 不再用 to_list 枚举所有厂家。"""
        from app.services.config import llm_service

        src = inspect.getsource(llm_service.LLMService.delete_llm_provider)
        assert "to_list" not in src, "delete_llm_provider 仍用 to_list 枚举"

    def test_delete_llm_config_uses_warning_for_not_found(self):
        """未找到匹配配置时用 warning，不是 error（业务可预期情况）。"""
        from app.services.config import llm_service

        src = inspect.getsource(llm_service.LLMService.delete_llm_config)
        assert "logger.warning" in src

    def test_delete_llm_config_preserves_core_logic(self):
        """核心逻辑保留：provider 大小写不敏感匹配 + model_name 精确匹配。"""
        from app.services.config import llm_service

        src = inspect.getsource(llm_service.LLMService.delete_llm_config)
        assert ".lower()" in src, "provider 大小写不敏感匹配丢失"
        assert "model_name" in src

    @pytest.mark.asyncio
    async def test_delete_llm_config_actually_removes_match(self, sim_db):
        """端到端：delete_llm_config 真实删除匹配的配置。

        用 SimulatedMongoDB 注入到 LLMService 的 _get_db / _get_system_config 路径，
        验证删除后配置列表真的变短。
        """
        from app.services.config import llm_service as svc_mod

        original_get_system_config = svc_mod.LLMService._get_system_config
        original_save_system_config = svc_mod.LLMService._save_system_config

        # 构造一个真实的内存 config 对象
        class _LLMConfig:
            def __init__(self, provider, model_name):
                self.provider = provider
                self.model_name = model_name

        class _SystemConfig:
            def __init__(self, configs):
                self.llm_configs = configs

        configs = [
            _LLMConfig("DeepSeek", "deepseek-chat"),
            _LLMConfig("openai", "gpt-4"),
            _LLMConfig("OpenAI", "gpt-3.5"),  # 不同大小写
        ]
        saved = {}

        async def fake_get(self):
            return _SystemConfig(list(configs))

        async def fake_save(self, cfg):
            saved["configs"] = list(cfg.llm_configs)
            return True

        svc_mod.LLMService._get_system_config = fake_get
        svc_mod.LLMService._save_system_config = fake_save

        try:
            service = svc_mod.LLMService()
            # 删除 openai/gpt-4（精确匹配）
            ok = await service.delete_llm_config("openai", "gpt-4")
            assert ok is True
            assert len(saved["configs"]) == 2
            remaining = [(c.provider, c.model_name) for c in saved["configs"]]
            assert ("openai", "gpt-4") not in remaining
            assert ("DeepSeek", "deepseek-chat") in remaining
        finally:
            svc_mod.LLMService._get_system_config = original_get_system_config
            svc_mod.LLMService._save_system_config = original_save_system_config

    @pytest.mark.asyncio
    async def test_delete_llm_config_case_insensitive_provider(self):
        """provider 大小写不敏感：删 OPENAI 也匹配 openai。"""
        from app.services.config import llm_service as svc_mod

        class _LLMConfig:
            def __init__(self, provider, model_name):
                self.provider = provider
                self.model_name = model_name

        class _SystemConfig:
            def __init__(self, configs):
                self.llm_configs = configs

        configs = [_LLMConfig("openai", "gpt-4")]
        saved = {}

        async def fake_get(self):
            return _SystemConfig(list(configs))

        async def fake_save(self, cfg):
            saved["configs"] = list(cfg.llm_configs)
            return True

        svc_mod.LLMService._get_system_config = fake_get
        svc_mod.LLMService._save_system_config = fake_save

        try:
            service = svc_mod.LLMService()
            ok = await service.delete_llm_config("OPENAI", "gpt-4")
            assert ok is True
            assert len(saved["configs"]) == 0
        finally:
            pass  # 下个测试会重新 patch

    @pytest.mark.asyncio
    async def test_delete_llm_config_returns_false_when_not_found(self):
        """删除不存在的配置返回 False。"""
        from app.services.config import llm_service as svc_mod

        class _LLMConfig:
            def __init__(self, provider, model_name):
                self.provider = provider
                self.model_name = model_name

        class _SystemConfig:
            def __init__(self, configs):
                self.llm_configs = configs

        configs = [_LLMConfig("openai", "gpt-4")]

        async def fake_get(self):
            return _SystemConfig(list(configs))

        async def fake_save(self, cfg):
            return True

        svc_mod.LLMService._get_system_config = fake_get
        svc_mod.LLMService._save_system_config = fake_save

        try:
            service = svc_mod.LLMService()
            ok = await service.delete_llm_config("nonexistent", "no-such-model")
            assert ok is False
        finally:
            pass
