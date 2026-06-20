"""
PR4 数据平台测试

覆盖 7 项修复：
- C1 数据源异常映射器（HTTP 状态码 / Tushare 错误码 / 网络异常 → DataSourceError 子类）
- C3 check_freshness 取 max(updated_at)
- C5 RateLimiter 锁作用域（Redis I/O 在锁外）
- C6 分布式锁 LRU 内存管理（_evict_memory_locks_if_full + release 同时清理两个 dict）
- C7 BaoStock session 引用计数（并发共享同一份 login）
- C8 init_collections 索引定义覆盖全部 22 个集合
- 综合验证：retry_policy + circuit_breaker 与异常子类联动正确
"""

import asyncio
from collections import OrderedDict

import pytest

# ---------------------------------------------------------------------------
# C1 数据源异常映射器
# ---------------------------------------------------------------------------


class TestDataSourceExceptionHierarchy:
    """C1：DataSourceError 子类继承关系。"""

    def test_all_subclasses_inherit_from_datasource_error(self):
        from app.data.sources.base.exceptions import (
            DataSourceError,
            DataSourceUnavailableError,
            RateLimitedError,
            TokenInvalidError,
            InsufficientCreditsError,
            SymbolNotFoundError,
            DataFormatError,
            NetworkError,
            DataNotFoundError,
        )

        for cls in [
            DataSourceUnavailableError,
            RateLimitedError,
            TokenInvalidError,
            InsufficientCreditsError,
            SymbolNotFoundError,
            DataFormatError,
            NetworkError,
            DataNotFoundError,
        ]:
            assert issubclass(cls, DataSourceError)

    def test_exception_carries_code_source_domain(self):
        from app.data.sources.base.exceptions import RateLimitedError
        from app.data.sources.base.error_codes import DataErrorCode

        exc = RateLimitedError("tushare", "daily_quotes", "限流测试")
        assert exc.source == "tushare"
        assert exc.domain == "daily_quotes"
        assert exc.code == DataErrorCode.RATE_LIMITED
        assert "限流测试" in str(exc)

    def test_network_error_is_retryable_code(self):
        from app.data.sources.base.exceptions import NetworkError
        from app.data.sources.base.error_codes import DataErrorCode

        exc = NetworkError("akshare", "basic_info")
        assert exc.code == DataErrorCode.NETWORK_TIMEOUT

    def test_data_not_found_is_non_retryable_code(self):
        from app.data.sources.base.exceptions import DataNotFoundError
        from app.data.sources.base.error_codes import DataErrorCode

        exc = DataNotFoundError("tushare", "financial_data")
        assert exc.code == DataErrorCode.EMPTY_RESULT


class TestMapHttpStatusToError:
    """C1：HTTP 状态码 → DataSourceError 子类。"""

    def test_429_maps_to_rate_limited(self):
        from app.data.sources.base.mappers import map_http_status_to_error
        from app.data.sources.base.exceptions import RateLimitedError

        exc = map_http_status_to_error(429, "tushare", "daily_quotes")
        assert isinstance(exc, RateLimitedError)

    def test_401_403_maps_to_token_invalid(self):
        from app.data.sources.base.mappers import map_http_status_to_error
        from app.data.sources.base.exceptions import TokenInvalidError

        for status in (401, 403):
            exc = map_http_status_to_error(status, "akshare", "basic_info")
            assert isinstance(exc, TokenInvalidError), f"status={status}"

    def test_5xx_maps_to_unavailable(self):
        from app.data.sources.base.mappers import map_http_status_to_error
        from app.data.sources.base.exceptions import DataSourceUnavailableError

        for status in (500, 502, 503):
            exc = map_http_status_to_error(status, "tushare", "daily_quotes")
            assert isinstance(exc, DataSourceUnavailableError), f"status={status}"

    def test_408_504_maps_to_network_error(self):
        from app.data.sources.base.mappers import map_http_status_to_error
        from app.data.sources.base.exceptions import NetworkError

        for status in (408, 504):
            exc = map_http_status_to_error(status, "tushare", "daily_quotes")
            assert isinstance(exc, NetworkError), f"status={status}"

    def test_4xx_client_error_maps_to_data_not_found(self):
        from app.data.sources.base.mappers import map_http_status_to_error
        from app.data.sources.base.exceptions import DataNotFoundError

        for status in (400, 404):
            exc = map_http_status_to_error(status, "tushare", "basic_info")
            assert isinstance(exc, DataNotFoundError), f"status={status}"


class TestMapTushareCode:
    """C1：Tushare 错误码 → DataSourceError 子类。"""

    def test_5003_maps_to_rate_limited(self):
        from app.data.sources.base.mappers import map_tushare_code
        from app.data.sources.base.exceptions import RateLimitedError

        exc = map_tushare_code(5003, "tushare", "daily_quotes")
        assert isinstance(exc, RateLimitedError)

    def test_40203_maps_to_insufficient_credits(self):
        from app.data.sources.base.mappers import map_tushare_code
        from app.data.sources.base.exceptions import InsufficientCreditsError

        exc = map_tushare_code(40203, "tushare", "adj_factors")
        assert isinstance(exc, InsufficientCreditsError)

    def test_10001_maps_to_token_invalid(self):
        from app.data.sources.base.mappers import map_tushare_code
        from app.data.sources.base.exceptions import TokenInvalidError

        exc = map_tushare_code(10001, "tushare", "daily_quotes")
        assert isinstance(exc, TokenInvalidError)

    def test_zero_or_none_returns_none(self):
        from app.data.sources.base.mappers import map_tushare_code

        assert map_tushare_code(0, "tushare", "x") is None
        assert map_tushare_code(None, "tushare", "x") is None

    def test_unknown_code_returns_none(self):
        from app.data.sources.base.mappers import map_tushare_code

        # 未知错误码（无映射）→ None 表示是正常结果
        assert map_tushare_code(99999, "tushare", "x") is None

    def test_string_code_handled(self):
        from app.data.sources.base.mappers import map_tushare_code
        from app.data.sources.base.exceptions import RateLimitedError

        # 字符串 "5003" 也应被识别
        exc = map_tushare_code("5003", "tushare", "daily_quotes")
        assert isinstance(exc, RateLimitedError)


class TestMapTushareResponse:
    """C1：从 Tushare 完整响应字典提取错误。"""

    def test_none_response_returns_data_not_found(self):
        from app.data.sources.base.mappers import map_tushare_response
        from app.data.sources.base.exceptions import DataNotFoundError

        exc = map_tushare_response(None, "tushare", "daily_quotes")
        assert isinstance(exc, DataNotFoundError)

    def test_success_response_returns_none(self):
        from app.data.sources.base.mappers import map_tushare_response

        response = {"code": 0, "msg": "", "data": [{"ts_code": "000001.SZ"}]}
        assert map_tushare_response(response, "tushare", "daily_quotes") is None

    def test_empty_data_returns_data_not_found(self):
        from app.data.sources.base.mappers import map_tushare_response
        from app.data.sources.base.exceptions import DataNotFoundError

        response = {"code": 0, "msg": "", "data": []}
        exc = map_tushare_response(response, "tushare", "daily_quotes")
        assert isinstance(exc, DataNotFoundError)

    def test_rate_limited_response(self):
        from app.data.sources.base.mappers import map_tushare_response
        from app.data.sources.base.exceptions import RateLimitedError

        response = {"code": 5003, "msg": "frequency limit"}
        exc = map_tushare_response(response, "tushare", "daily_quotes")
        assert isinstance(exc, RateLimitedError)


class TestMapNetworkException:
    """C1：底层网络异常 → NetworkError。"""

    def test_asyncio_timeout_error(self):
        from app.data.sources.base.mappers import map_network_exception
        from app.data.sources.base.exceptions import NetworkError

        exc = map_network_exception(asyncio.TimeoutError(), "tushare", "daily_quotes")
        assert isinstance(exc, NetworkError)

    def test_connection_error(self):
        from app.data.sources.base.mappers import map_network_exception
        from app.data.sources.base.exceptions import NetworkError

        exc = map_network_exception(ConnectionError("refused"), "akshare", "basic_info")
        assert isinstance(exc, NetworkError)
        assert "refused" in str(exc)


class TestIsEmptyResult:
    """C1：空结果检测工具函数。"""

    def test_none_is_empty(self):
        from app.data.sources.base.mappers import is_empty_result

        assert is_empty_result(None) is True

    def test_empty_list_dict_str(self):
        from app.data.sources.base.mappers import is_empty_result

        assert is_empty_result([]) is True
        assert is_empty_result({}) is True
        assert is_empty_result("") is True

    def test_non_empty_list(self):
        from app.data.sources.base.mappers import is_empty_result

        assert is_empty_result([1, 2, 3]) is False

    def test_pandas_empty_dataframe(self):
        from app.data.sources.base.mappers import is_empty_result
        import pandas as pd

        assert is_empty_result(pd.DataFrame()) is True
        assert is_empty_result(pd.DataFrame({"a": [1]})) is False


# ---------------------------------------------------------------------------
# C3 check_freshness
# ---------------------------------------------------------------------------


class TestCheckFreshness:
    """C3：check_freshness 取 max(updated_at) 而非 data[0]。"""

    @pytest.mark.asyncio
    async def test_takes_max_updated_at_for_ascending_list(self):
        """仓储返回 trade_date 升序时，data[0] 是最早记录，
        必须取 max(updated_at) 才能拿到最新更新时间。

        构造：最新一条 trade_date 的 updated_at 也是最新的，其他两条是历史 STALE。
        这样如果 max() 生效 → FRESH；如果错误取了 data[0] → STALE（旧记录 updated_at）。
        对照测试让断言更严格，不再"只判 != UNKNOWN"。
        """
        from app.data.core.reader import Reader

        reader = Reader()
        # 列表 trade_date 升序，updated_at 严格单调递增（最新记录最新更新）
        data = [
            {
                "trade_date": "2024-01-01",
                "updated_at": "2024-01-02T00:00:00Z",
            },  # 最早 STALE
            {
                "trade_date": "2024-01-02",
                "updated_at": "2024-06-01T00:00:00Z",
            },  # 中间 STALE
            {
                "trade_date": "2024-01-03",
                "updated_at": "2099-12-31T00:00:00Z",
            },  # 最新 FRESH
        ]
        freshness = await reader.check_freshness("CN", "000001", "daily_quotes", data)
        # 严格断言：取了 max(updated_at) 才会判 FRESH；错误取 data[0] 会判 STALE
        from app.data.schema.base.enums import FreshnessState

        assert freshness == FreshnessState.FRESH, (
            f"应取 max(updated_at) 得到 FRESH，实际: {freshness} "
            "（如果取了 data[0] 会因为旧 updated_at 得到 STALE）"
        )

    @pytest.mark.asyncio
    async def test_empty_list_returns_unknown(self):
        from app.data.core.reader import Reader
        from app.data.schema.base.enums import FreshnessState

        reader = Reader()
        freshness = await reader.check_freshness("CN", "000001", "daily_quotes", [])
        assert freshness == FreshnessState.UNKNOWN

    @pytest.mark.asyncio
    async def test_list_without_updated_at_returns_unknown(self):
        from app.data.core.reader import Reader
        from app.data.schema.base.enums import FreshnessState

        reader = Reader()
        data = [{"trade_date": "2024-01-01"}]  # 没有 updated_at 字段
        freshness = await reader.check_freshness("CN", "000001", "daily_quotes", data)
        assert freshness == FreshnessState.UNKNOWN

    @pytest.mark.asyncio
    async def test_dict_input_uses_direct_field(self):
        from app.data.core.reader import Reader
        from app.data.schema.base.enums import FreshnessState

        reader = Reader()
        # 单条 dict 时直接读 data["updated_at"]
        data = {"updated_at": "2024-12-01T00:00:00Z"}
        freshness = await reader.check_freshness("CN", "000001", "basic_info", data)
        assert freshness != FreshnessState.UNKNOWN

    @pytest.mark.asyncio
    async def test_unknown_domain_returns_unknown(self):
        from app.data.core.reader import Reader
        from app.data.schema.base.enums import FreshnessState

        reader = Reader()
        data = [{"updated_at": "2024-12-01T00:00:00Z"}]
        freshness = await reader.check_freshness(
            "CN", "000001", "nonexistent_domain", data
        )
        assert freshness == FreshnessState.UNKNOWN


# ---------------------------------------------------------------------------
# C5 RateLimiter 锁作用域
# ---------------------------------------------------------------------------


class TestRateLimiterLockScope:
    """C5：Redis I/O 移出锁外，仅 last_request_time 在锁内。"""

    def test_acquire_allowed_for_unconfigured_source(self):
        """未配置的 source 应直接放行。"""
        from app.data.processor.rate_limiter import RateLimiter

        limiter = RateLimiter()
        allowed, wait = asyncio.run(limiter.acquire("unknown_source", "daily_quotes"))
        assert allowed is True
        assert wait == 0

    def test_polite_interval_blocks_second_request(self):
        """polite_interval_ms 内的二次请求必须被拒。"""
        from app.data.processor.rate_limiter import RateLimiter

        limiter = RateLimiter()
        limiter.configure("test_src", rate_per_minute=100, polite_interval_ms=500)

        allowed1, _ = asyncio.run(limiter.acquire("test_src", "x"))
        assert allowed1 is True

        allowed2, wait2 = asyncio.run(limiter.acquire("test_src", "x"))
        assert allowed2 is False
        assert wait2 > 0

    def test_redis_failure_transitions_to_fail_open_after_3_errors(self):
        """Redis 持续故障：前 N-1 次返回 (False, 5) 退避；达阈值后切到 fail-open 内存计数放行。

        与 H3 实现对齐：原 test_redis_failure_does_not_block_business 假设 Redis 故障即
        放行，但实际 H3 用熔断式策略——前 2 次仍 fail-closed 短暂退避给 Redis 恢复机会，
        第 3 次起切到内存计数兜底，避免单点故障拖死所有同步任务。
        """
        from app.data.processor.rate_limiter import RateLimiter

        # 注入会抛异常的计数器，模拟 Redis 故障（不使用 mock，符合 CLAUDE.md 测试规则）
        class BoomCounter:
            async def get_count(self, key):
                raise ConnectionError("redis down")

            async def increment(self, key):
                raise ConnectionError("redis down")

        async def _run():
            limiter = RateLimiter()
            limiter.configure(
                "fail_open_test", rate_per_minute=100, polite_interval_ms=0
            )
            limiter._counters["fail_open_test"] = BoomCounter()

            # 第 1、2 次：未到阈值，fail-closed 退避
            r1 = await limiter.acquire("fail_open_test", "x")
            r2 = await limiter.acquire("fail_open_test", "x")
            # 第 3 次：达到阈值，切换 fail-open 内存计数
            r3 = await limiter.acquire("fail_open_test", "x")
            # 第 4 次：仍处于 fail-open（探测间隔内）
            r4 = await limiter.acquire("fail_open_test", "x")
            return r1, r2, r3, r4

        r1, r2, r3, r4 = asyncio.run(_run())
        assert r1 == (False, 5.0) and r2 == (
            False,
            5.0,
        ), f"前两次应 fail-closed 退避 5s: r1={r1} r2={r2}"
        assert r3[0] is True, f"第 3 次应切到 fail-open 放行: r3={r3}"
        assert r4[0] is True, f"第 4 次应继续 fail-open 放行: r4={r4}"

    def test_lock_is_module_level_not_per_call(self):
        """每个 source 共用同一把锁（非每次 acquire 新建）。"""
        from app.data.processor.rate_limiter import RateLimiter

        limiter = RateLimiter()
        limiter.configure("lock_test", rate_per_minute=100)
        lock1 = limiter._locks.get("lock_test")

        # 再次 configure 不应创建新锁
        limiter.configure("lock_test", rate_per_minute=200)
        lock2 = limiter._locks.get("lock_test")

        assert lock1 is lock2


# ---------------------------------------------------------------------------
# C6 分布式锁 LRU 内存管理
# ---------------------------------------------------------------------------


class TestDistributedLockLRU:
    """C6：_async_memory_locks LRU 上限 + release 同时清理两个 dict。"""

    def test_memory_lock_dict_has_upper_bound(self):
        from app.data.storage.redis import locks as locks_mod

        # 默认上限 1000
        assert locks_mod._MEMORY_LOCK_MAX_ENTRIES == 1000

    def test_evict_function_exists_and_callable(self):
        from app.data.storage.redis import locks as locks_mod

        assert callable(locks_mod._evict_memory_locks_if_full)

    def test_evict_removes_unlocked_entries_when_over_limit(self):
        """超出上限时，未持锁的旧 entry 应被淘汰。"""
        from app.data.storage.redis import locks as locks_mod

        # 临时降低上限便于测试
        original_max = locks_mod._MEMORY_LOCK_MAX_ENTRIES
        original_locks = locks_mod._async_memory_locks
        original_owners = locks_mod._memory_lock_owners
        try:
            locks_mod._MEMORY_LOCK_MAX_ENTRIES = 3
            locks_mod._async_memory_locks = OrderedDict()
            locks_mod._memory_lock_owners = {}

            # 插入 4 个未持锁的 entry（应淘汰 1 个）
            for i in range(4):
                locks_mod._async_memory_locks[f"lock_{i}"] = asyncio.Lock()
                locks_mod._memory_lock_owners[f"lock_{i}"] = f"owner_{i}"

            locks_mod._evict_memory_locks_if_full()

            # 上限是 3，所以应保留 3 个
            assert len(locks_mod._async_memory_locks) <= 3
        finally:
            locks_mod._MEMORY_LOCK_MAX_ENTRIES = original_max
            locks_mod._async_memory_locks = original_locks
            locks_mod._memory_lock_owners = original_owners

    def test_evict_keeps_locked_entries(self):
        """持锁中的 entry 不应被淘汰（移到末尾延后处理）。"""
        from app.data.storage.redis import locks as locks_mod

        original_max = locks_mod._MEMORY_LOCK_MAX_ENTRIES
        original_locks = locks_mod._async_memory_locks
        original_owners = locks_mod._memory_lock_owners
        try:
            locks_mod._MEMORY_LOCK_MAX_ENTRIES = 2
            locks_mod._async_memory_locks = OrderedDict()
            locks_mod._memory_lock_owners = {}

            # 第一个锁处于 locked 状态
            held_lock = asyncio.Lock()
            locks_mod._async_memory_locks["held_lock"] = held_lock
            locks_mod._memory_lock_owners["held_lock"] = "owner1"
            asyncio.run(held_lock.acquire())

            # 插入 2 个未持锁的（应淘汰一个，但 held_lock 不被淘汰）
            locks_mod._async_memory_locks["free1"] = asyncio.Lock()
            locks_mod._async_memory_locks["free2"] = asyncio.Lock()

            locks_mod._evict_memory_locks_if_full()

            # held_lock 必须保留
            assert "held_lock" in locks_mod._async_memory_locks
        finally:
            # 清理
            try:
                held_lock.release()
            except Exception:
                pass
            locks_mod._MEMORY_LOCK_MAX_ENTRIES = original_max
            locks_mod._async_memory_locks = original_locks
            locks_mod._memory_lock_owners = original_owners

    def test_release_clears_both_dicts(self):
        """release() 必须同时从 _async_memory_locks 和 _memory_lock_owners 删除。"""
        from app.data.storage.redis import locks as locks_mod
        from app.data.storage.redis.locks import DistributedLock

        original_locks = locks_mod._async_memory_locks
        original_owners = locks_mod._memory_lock_owners
        try:
            locks_mod._async_memory_locks = OrderedDict()
            locks_mod._memory_lock_owners = {}

            lock = DistributedLock("test_release_key", ttl=30)

            acquired = asyncio.run(lock.acquire())
            assert acquired is True
            # 内存降级路径下 entry 应存在
            assert "test_release_key" in locks_mod._async_memory_locks
            assert "test_release_key" in locks_mod._memory_lock_owners

            asyncio.run(lock.release())
            # release 后两个 dict 都应清除该 key
            assert "test_release_key" not in locks_mod._async_memory_locks
            assert "test_release_key" not in locks_mod._memory_lock_owners
        finally:
            locks_mod._async_memory_locks = original_locks
            locks_mod._memory_lock_owners = original_owners


# ---------------------------------------------------------------------------
# C7 BaoStock session 引用计数
# ---------------------------------------------------------------------------


class TestBaoStockSessionRefCount:
    """C7：BaoStock bs.login()/logout() 引用计数。"""

    def test_session_lock_is_module_level(self):
        from app.data.sources.cn.baostock.api import connection as conn_mod

        # 全局锁与计数器必须存在
        assert conn_mod._session_lock is not None
        assert hasattr(conn_mod, "_session_refcount")
        assert hasattr(conn_mod, "_session_logged_in")

    def test_concurrent_contexts_share_single_login(self):
        """多个并发 baostock_session() 上下文只 login 一次。

        通过 monkey-patch bs.login/logout 计数，验证不会相互 logout。
        """
        from app.data.sources.cn.baostock.api import connection as conn_mod

        if not conn_mod.BAOSTOCK_AVAILABLE:
            pytest.skip("BaoStock 未安装，跳过")

        login_count = {"value": 0}
        logout_count = {"value": 0}
        original_login = conn_mod.bs.login
        original_logout = conn_mod.bs.logout

        def counting_login(*args, **kwargs):
            login_count["value"] += 1
            return type("R", (), {"error_code": "0", "error_msg": ""})()

        def counting_logout(*args, **kwargs):
            logout_count["value"] += 1
            return type("R", (), {"error_code": "0", "error_msg": ""})()

        # 重置 refcount
        original_refcount = conn_mod._session_refcount
        original_logged_in = conn_mod._session_logged_in
        conn_mod._session_refcount = 0
        conn_mod._session_logged_in = False

        try:
            conn_mod.bs.login = counting_login
            conn_mod.bs.logout = counting_logout

            async def run_concurrent():
                async with conn_mod.baostock_session():
                    # 在第一个还没退出时进入第二个
                    async with conn_mod.baostock_session():
                        async with conn_mod.baostock_session():
                            pass

            asyncio.run(run_concurrent())

            # 三个嵌套上下文只应 login 1 次、logout 1 次
            assert (
                login_count["value"] == 1
            ), f"期望 login 1 次，实际 {login_count['value']}"
            assert (
                logout_count["value"] == 1
            ), f"期望 logout 1 次，实际 {logout_count['value']}"
        finally:
            conn_mod.bs.login = original_login
            conn_mod.bs.logout = original_logout
            conn_mod._session_refcount = original_refcount
            conn_mod._session_logged_in = original_logged_in

    def test_nested_contexts_increment_decrement_refcount(self):
        """refcount 应正确增减。"""
        from app.data.sources.cn.baostock.api import connection as conn_mod

        if not conn_mod.BAOSTOCK_AVAILABLE:
            pytest.skip("BaoStock 未安装，跳过")

        original_login = conn_mod.bs.login
        original_logout = conn_mod.bs.logout

        def noop_login(*args, **kwargs):
            return type("R", (), {"error_code": "0", "error_msg": ""})()

        def noop_logout(*args, **kwargs):
            return type("R", (), {"error_code": "0", "error_msg": ""})()

        original_refcount = conn_mod._session_refcount
        original_logged_in = conn_mod._session_logged_in
        conn_mod._session_refcount = 0
        conn_mod._session_logged_in = False

        try:
            conn_mod.bs.login = noop_login
            conn_mod.bs.logout = noop_logout

            async def single_context():
                async with conn_mod.baostock_session():
                    # 进入时 refcount >= 1
                    assert conn_mod._session_refcount >= 1
                # 退出后应回到 0
                assert conn_mod._session_refcount == 0

            asyncio.run(single_context())
        finally:
            conn_mod.bs.login = original_login
            conn_mod.bs.logout = original_logout
            conn_mod._session_refcount = original_refcount
            conn_mod._session_logged_in = original_logged_in


# ---------------------------------------------------------------------------
# C8 init_collections 索引定义
# ---------------------------------------------------------------------------


class TestInitCollectionsIndexes:
    """C8：INDEX_DEFINITIONS 覆盖所有业务集合。"""

    def test_index_definitions_covers_all_business_domains(self):
        """22 个 domain 必须都有索引定义。"""
        from app.data.scripts.init_collections import INDEX_DEFINITIONS
        from app.data.storage.mongo.collections import _BUSINESS_COLLECTIONS

        # 业务集合的 domain 集合
        business_domains = set(_BUSINESS_COLLECTIONS.keys())
        defined_domains = set(INDEX_DEFINITIONS.keys())

        missing = business_domains - defined_domains
        assert not missing, f"缺失索引定义的 domain: {missing}"

    def test_index_definitions_covers_metadata_collections(self):
        """sync_checkpoints / sync_events / source_health / system_configs 都应有索引。"""
        from app.data.scripts.init_collections import INDEX_DEFINITIONS

        required_metadata = {
            "sync_checkpoints",
            "sync_events",
            "source_health",
            "system_configs",
        }
        for name in required_metadata:
            assert name in INDEX_DEFINITIONS, f"缺少元数据集合索引: {name}"

    def test_corporate_actions_index_is_unique(self):
        """corporate_actions 必须有 (symbol, ex_date, action_type) 唯一索引。"""
        from app.data.scripts.init_collections import INDEX_DEFINITIONS

        specs = INDEX_DEFINITIONS["corporate_actions"]
        # 找到唯一索引
        unique_specs = [(fields, unique) for fields, unique in specs if unique]
        assert unique_specs, "corporate_actions 应至少有一个唯一索引"

        # 验证字段包含 symbol + ex_date
        fields_list = [dict(fields) for fields, _ in unique_specs]
        has_symbol_ex_date = any("symbol" in f and "ex_date" in f for f in fields_list)
        assert has_symbol_ex_date, "缺少 (symbol, ex_date) 唯一索引"

    def test_daily_quotes_index_includes_period(self):
        """daily_quotes 必须有 (symbol, trade_date, period) 复合唯一索引。"""
        from app.data.scripts.init_collections import INDEX_DEFINITIONS

        specs = INDEX_DEFINITIONS["daily_quotes"]
        # 检查所有 spec 中是否包含 period 字段
        all_field_names = set()
        for fields, _ in specs:
            for fname, _ in fields:
                all_field_names.add(fname)
        assert "period" in all_field_names, "daily_quotes 索引应包含 period 字段"

    def test_financial_data_has_compound_unique_index(self):
        """financial_data 按 (symbol, report_period, statement_type) 唯一。"""
        from app.data.scripts.init_collections import INDEX_DEFINITIONS

        specs = INDEX_DEFINITIONS["financial_data"]
        unique_specs = [dict(f) for f, u in specs if u]
        assert unique_specs
        has_required = any(
            "symbol" in s and "report_period" in s and "statement_type" in s
            for s in unique_specs
        )
        assert has_required

    def test_intraday_quotes_compound_unique_index(self):
        """intraday_quotes 按 (symbol, datetime, freq) 唯一。"""
        from app.data.scripts.init_collections import INDEX_DEFINITIONS

        specs = INDEX_DEFINITIONS["intraday_quotes"]
        unique_specs = [(f, u) for f, u in specs if u]
        assert unique_specs
        # 索引字段名应与 schema/repo filter 一致：datetime + freq
        has_datetime_in_unique = any(
            any(fname == "datetime" for fname, _ in fields)
            for fields, _ in unique_specs
        )
        assert has_datetime_in_unique


# ---------------------------------------------------------------------------
# 综合验证：retry_policy + circuit_breaker 与异常子类联动
# ---------------------------------------------------------------------------


class TestRetryPolicyWithMappedErrors:
    """C1 综合验证：retry_policy 与 DataSourceError 子类的联动。"""

    def test_rate_limited_is_retryable(self):
        from app.data.processor.retry_policy import is_retryable
        from app.data.sources.base.exceptions import RateLimitedError

        assert is_retryable(RateLimitedError("tushare", "daily_quotes")) is True

    def test_network_error_is_retryable(self):
        from app.data.processor.retry_policy import is_retryable
        from app.data.sources.base.exceptions import NetworkError

        assert is_retryable(NetworkError("akshare", "basic_info")) is True

    def test_token_invalid_is_not_retryable(self):
        from app.data.processor.retry_policy import is_retryable
        from app.data.sources.base.exceptions import TokenInvalidError

        assert is_retryable(TokenInvalidError("tushare", "x")) is False

    def test_data_not_found_is_not_retryable(self):
        from app.data.processor.retry_policy import is_retryable
        from app.data.sources.base.exceptions import DataNotFoundError

        assert is_retryable(DataNotFoundError("tushare", "x")) is False

    def test_insufficient_credits_is_not_retryable(self):
        from app.data.processor.retry_policy import is_retryable
        from app.data.sources.base.exceptions import InsufficientCreditsError

        assert is_retryable(InsufficientCreditsError("tushare", "x")) is False

    @pytest.mark.asyncio
    async def test_execute_with_retry_retries_on_network_error(self):
        """NetworkError 应触发重试，最终成功。"""
        from app.data.processor.retry_policy import RetryPolicy
        from app.data.sources.base.exceptions import NetworkError

        call_count = {"value": 0}

        async def flaky():
            call_count["value"] += 1
            if call_count["value"] < 2:
                raise NetworkError("tushare", "daily_quotes", "transient")
            return "success"

        policy = RetryPolicy(max_retries=2)
        # 把 backoff 改为 0 加快测试
        import app.data.processor.retry_policy as rp_mod

        original_backoff = rp_mod.get_backoff
        rp_mod.get_backoff = lambda e, a: 0
        try:
            result = await policy.execute_with_retry(flaky)
            assert result == "success"
            assert call_count["value"] == 2
        finally:
            rp_mod.get_backoff = original_backoff

    @pytest.mark.asyncio
    async def test_execute_with_retry_does_not_retry_token_invalid(self):
        """TokenInvalidError 应立即抛出，不重试。"""
        from app.data.processor.retry_policy import RetryPolicy
        from app.data.sources.base.exceptions import TokenInvalidError

        call_count = {"value": 0}

        async def always_fails():
            call_count["value"] += 1
            raise TokenInvalidError("tushare", "daily_quotes")

        policy = RetryPolicy(max_retries=3)
        with pytest.raises(TokenInvalidError):
            await policy.execute_with_retry(always_fails)
        assert call_count["value"] == 1  # 不重试


class TestCircuitBreakerDifferentialCooldown:
    """C1 综合验证：不同错误类型冷却时间差异化。"""

    def test_rate_limited_cooldown_double_of_baseline(self):
        """RateLimitedError 冷却时间是 baseline 的 2 倍。"""
        from app.data.processor.circuit_breaker import (
            CircuitBreaker,
            COOLDOWN_STEPS,
            _ERROR_COOLDOWN_MULTIPLIERS,
        )
        from app.data.sources.base.error_codes import DataErrorCode

        # 触发熔断（3 次失败）
        cb = CircuitBreaker()
        for _ in range(3):
            cb.record_failure("tushare", "daily_quotes", DataErrorCode.RATE_LIMITED)

        state = cb._get_state("tushare", "daily_quotes")
        baseline = COOLDOWN_STEPS[0]  # 60s
        expected = min(
            int(baseline * _ERROR_COOLDOWN_MULTIPLIERS[DataErrorCode.RATE_LIMITED]),
            3600,
        )
        assert state["cooldown"] == expected
        assert state["cooldown"] == baseline * 2

    def test_token_invalid_cooldown_5x_baseline(self):
        """TokenInvalidError 冷却时间是 baseline 的 5 倍。"""
        from app.data.processor.circuit_breaker import (
            CircuitBreaker,
            COOLDOWN_STEPS,
            _ERROR_COOLDOWN_MULTIPLIERS,
        )
        from app.data.sources.base.error_codes import DataErrorCode

        cb = CircuitBreaker()
        for _ in range(3):
            cb.record_failure("akshare", "basic_info", DataErrorCode.TOKEN_INVALID)

        state = cb._get_state("akshare", "basic_info")
        baseline = COOLDOWN_STEPS[0]
        assert (
            state["cooldown"]
            == baseline * _ERROR_COOLDOWN_MULTIPLIERS[DataErrorCode.TOKEN_INVALID]
        )
        assert state["cooldown"] == baseline * 5

    def test_network_error_cooldown_equals_baseline(self):
        """NetworkError 冷却时间等于 baseline（×1）。"""
        from app.data.processor.circuit_breaker import (
            CircuitBreaker,
            COOLDOWN_STEPS,
            _ERROR_COOLDOWN_MULTIPLIERS,
        )
        from app.data.sources.base.error_codes import DataErrorCode

        cb = CircuitBreaker()
        for _ in range(3):
            cb.record_failure("tushare", "daily_quotes", DataErrorCode.NETWORK_TIMEOUT)

        state = cb._get_state("tushare", "daily_quotes")
        baseline = COOLDOWN_STEPS[0]
        assert (
            state["cooldown"]
            == baseline * _ERROR_COOLDOWN_MULTIPLIERS[DataErrorCode.NETWORK_TIMEOUT]
        )
        assert state["cooldown"] == baseline  # 1x


# ---------------------------------------------------------------------------
# C1 综合验证：完整 fetch 流程中异常分类正确
# ---------------------------------------------------------------------------


class TestExceptionChaining:
    """C1 综合验证：异常保留原始信息便于排查。"""

    def test_network_error_preserves_original_exception_class_name(self):
        from app.data.sources.base.mappers import map_network_exception

        original = ConnectionRefusedError("connection refused by host")
        exc = map_network_exception(original, "tushare", "daily_quotes")
        # 异常信息中应包含原始类名
        assert (
            "ConnectionRefusedError" in str(exc)
            or "connection refused" in str(exc).lower()
        )

    def test_http_status_error_message_contains_status(self):
        from app.data.sources.base.mappers import map_http_status_to_error

        exc = map_http_status_to_error(503, "tushare", "daily_quotes")
        assert "503" in str(exc)

    def test_rate_limited_error_has_retry_after_field(self):
        from app.data.sources.base.mappers import map_http_status_to_error
        from app.data.sources.base.exceptions import RateLimitedError

        exc = map_http_status_to_error(429, "tushare", "daily_quotes", retry_after=30)
        assert isinstance(exc, RateLimitedError)
        assert exc.retry_after == 30

    def test_insufficient_credits_error_has_required_field(self):
        from app.data.sources.base.mappers import map_tushare_code
        from app.data.sources.base.exceptions import InsufficientCreditsError

        exc = map_tushare_code(40203, "tushare", "adj_factors", "需要 5000 积分")
        assert isinstance(exc, InsufficientCreditsError)
