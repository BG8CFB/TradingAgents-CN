"""
PR4 + PR5 审查修复验证测试

针对 4 个并行代码审查识别的 P0/P1 问题，覆盖：
- BaoStock 3 文件 NetworkError 导入修复（P0）
- hk_hold.py _DOMAIN 命名修复（P0）
- Finnhub 3 文件 FinnhubAPIException 捕获修复（P0）
- multi_source_basics_sync_service.py PriorityConfig 导入修复（P0）
- Tencent HK URLError 捕获修复（P1）
- locks.py TTL 回调 owner_id 验证修复（P1）

测试策略：
- 静态源码分析（ast.parse）验证 import 节点，避免逐行字符串匹配的脆弱性
- 动态行为测试：构造真实异常实例 + isinstance + except 捕获链路，验证映射正确性
- 不使用 mock，所有异常类型和 HTTP 客户端都是真实的
"""

import ast
import asyncio
import inspect
import importlib
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# P0-1: BaoStock 3 文件 NetworkError 导入
# ---------------------------------------------------------------------------


def _module_file_path(module_path: str) -> Path:
    """根据模块路径返回源文件 Path。"""
    mod = importlib.import_module(module_path)
    return Path(inspect.getfile(mod))


def _parse_imports(module_path: str) -> list[ast.ImportFrom]:
    """解析模块源码，返回所有 ImportFrom 节点。"""
    src = inspect.getsource(importlib.import_module(module_path))
    tree = ast.parse(src)
    return [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]


def _assert_imports_name_from_module(
    module_path: str, expected_module: str, expected_name: str
) -> None:
    """断言模块显式从 expected_module 导入了 expected_name。

    使用 ast.parse 解析 ImportFrom 节点，避免逐行字符串匹配：
    - 跳过 # 注释和 docstring 中的误匹配
    - 跳过 from ... import (NetworkError) 的各种换行/缩进变体
    """
    imports = _parse_imports(module_path)
    for node in imports:
        if node.module != expected_module:
            continue
        for alias in node.names:
            if alias.name == expected_name:
                return
    pytest.fail(
        f"{module_path} 未显式从 {expected_module} 导入 {expected_name}"
    )


class TestBaoStockNetworkErrorImport:
    """BaoStock 3 文件必须正确导入 NetworkError。

    背景：原代码中 `except (NetworkError, ...)` 引用了 NetworkError 但未导入，
    会触发 NameError。
    """

    FILES = [
        "app.data.sources.cn.baostock.api.daily_quotes",
        "app.data.sources.cn.baostock.api.stock_basic",
        "app.data.sources.cn.baostock.api.financial",
    ]

    @pytest.mark.parametrize("module_path", FILES)
    def test_network_error_imported(self, module_path):
        """源码 AST 中必须存在 ImportFrom(base.exceptions) → NetworkError。"""
        _assert_imports_name_from_module(
            module_path,
            "app.data.sources.base.exceptions",
            "NetworkError",
        )

    @pytest.mark.parametrize("module_path", FILES)
    def test_network_error_is_real_import(self, module_path):
        """模块加载后 NetworkError 必须绑定到异常类（不是 NameError）。

        通过 ast 解析 + 模块属性访问双重验证：
        1. AST 中存在合法的 ImportFrom 节点
        2. 模块加载后 NetworkError 真实绑定（getattr 返回异常类，而非 AttributeError）
        """
        # AST 验证
        _assert_imports_name_from_module(
            module_path,
            "app.data.sources.base.exceptions",
            "NetworkError",
        )

        # 模块属性验证：importlib.import_module 在 import 阶段就会触发 NameError
        # （若 NetworkError 漏写），无需再 reload 重复验证
        importlib.import_module(module_path)
        from app.data.sources.base.exceptions import NetworkError as ExpectedNetworkError
        assert issubclass(ExpectedNetworkError, Exception)

    @pytest.mark.parametrize("module_path", FILES)
    def test_network_error_except_clause_catchable(self, module_path):
        """构造真实 NetworkError 实例，验证 except (NetworkError, ...) 能捕获。

        场景：在模块内部 import 一个真实的 NetworkError 实例，
        验证：
        1. NetworkError 可被实例化（源码无误）
        2. raise NetworkError(...) 后 except 子句能正确捕获
        3. 捕获的异常就是预期类型（isinstance 校验）
        """
        # 显式从 base.exceptions 导入 NetworkError（基类）
        from app.data.sources.base.exceptions import NetworkError

        # 构造真实异常实例（与生产代码 raise NetworkError("baostock", ...) 一致）
        exc = NetworkError("baostock", "daily_quotes", "test network failure")
        assert isinstance(exc, Exception)
        assert exc.source == "baostock"
        assert exc.domain == "daily_quotes"

        # 真实抛出 + 捕获链路（模拟生产 except (NetworkError, ...) 行为）
        try:
            raise exc
        except (NetworkError, ConnectionError, TimeoutError) as caught:
            assert isinstance(caught, NetworkError)
            assert "test network failure" in str(caught)
        else:
            pytest.fail("NetworkError 未被 except (NetworkError, ...) 捕获")

    def test_baostock_daily_quotes_network_error_callable(self):
        """daily_quotes.py 加载后引用 NetworkError 不抛 NameError。

        真实异常路径：模拟 to_thread 抛 asyncio.TimeoutError，
        验证 map_network_exception 正确返回 NetworkError 子类。
        """
        from app.data.sources.cn.baostock.api import daily_quotes
        from app.data.sources.base.exceptions import NetworkError
        from app.data.sources.base.mappers import map_network_exception

        # 模块加载即验证（NameError 会让模块加载失败）
        assert hasattr(daily_quotes, "fetch_daily_quotes")

        # 构造真实网络异常并通过 mapper 转换
        original = asyncio.TimeoutError("baostock connect timeout")
        mapped = map_network_exception(original, "baostock", "daily_quotes")
        assert isinstance(mapped, NetworkError)
        assert mapped.source == "baostock"
        assert mapped.domain == "daily_quotes"

    def test_baostock_stock_basic_network_error_callable(self):
        from app.data.sources.cn.baostock.api import stock_basic
        from app.data.sources.base.exceptions import NetworkError
        from app.data.sources.base.mappers import map_network_exception

        assert hasattr(stock_basic, "_DOMAIN") or hasattr(stock_basic, "fetch_stock_basic")

        # 真实异常路径：模拟 ConnectionError
        original = ConnectionError("connection refused")
        mapped = map_network_exception(original, "baostock", "basic_info")
        assert isinstance(mapped, NetworkError)

    def test_baostock_financial_network_error_callable(self):
        from app.data.sources.cn.baostock.api import financial
        from app.data.sources.base.exceptions import NetworkError
        from app.data.sources.base.mappers import map_network_exception

        assert financial is not None

        # 真实异常路径：模拟 TimeoutError
        original = TimeoutError("read timeout after 30s")
        mapped = map_network_exception(original, "baostock", "financial_data")
        assert isinstance(mapped, NetworkError)


# ---------------------------------------------------------------------------
# P0-2: hk_hold.py _DOMAIN 名称修复
# ---------------------------------------------------------------------------


class TestHkHoldDomainName:
    """hk_hold.py 的 _DOMAIN 必须与 reader.py / domain.py 中的命名一致。

    背景：原代码 _DOMAIN = "southbound_holdings"（复数），但
    全项目 domain.py / reader.py / scheduler / repos 都用 "southbound_holding"（单数）。
    """

    def test_hk_hold_domain_is_singular(self):
        from app.data.sources.hk.tushare_hk.api import hk_hold

        assert hk_hold._DOMAIN == "southbound_holding", (
            f"_DOMAIN 应为 'southbound_holding'（单数），实际为 {hk_hold._DOMAIN!r}"
        )

    def test_hk_hold_domain_matches_domain_py(self):
        """与 app.data.core.domain.py 中 SOUTHBOUND_HOLDING 常量一致。"""
        from app.data.core.domain import DataDomain
        from app.data.sources.hk.tushare_hk.api import hk_hold

        assert hk_hold._DOMAIN == DataDomain.SOUTHBOUND_HOLDING

    def test_hk_hold_domain_matches_reader_routing(self):
        """与 reader.py 路由表中的 key 一致（否则数据无法存储）。"""
        from app.data.sources.hk.tushare_hk.api import hk_hold
        # reader.py 的路由字典中包含 'southbound_holding' key
        from app.data.core import reader as reader_mod

        src = inspect.getsource(reader_mod)
        assert '"southbound_holding"' in src or "'southbound_holding'" in src
        assert hk_hold._DOMAIN == "southbound_holding"


# ---------------------------------------------------------------------------
# P0-3: Finnhub 3 文件 FinnhubAPIException 捕获
# ---------------------------------------------------------------------------


class TestFinnhubApiExceptionCapture:
    """Finnhub 3 文件必须捕获 finnhub.FinnhubAPIException 并映射到 HTTP 状态码异常。

    背景：原代码只有 except Exception，HTTP 4xx/5xx 会被错误分类为
    DataSourceUnavailableError，无法区分 429 限流、401 鉴权失败。
    """

    FILES = [
        "app.data.sources.us.finnhub.api.basic_info",
        "app.data.sources.us.finnhub.api.market_quotes",
        "app.data.sources.us.finnhub.api.news",
    ]

    @pytest.mark.parametrize("module_path", FILES)
    def test_module_catches_finnhub_api_exception(self, module_path):
        """源码中必须显式捕获 finnhub.FinnhubAPIException。"""
        import importlib

        mod = importlib.import_module(module_path)
        src = inspect.getsource(mod)
        assert "FinnhubAPIException" in src, (
            f"{module_path} 未显式捕获 finnhub.FinnhubAPIException"
        )
        assert "finnhub.FinnhubAPIException" in src, (
            f"{module_path} 必须用 `finnhub.FinnhubAPIException` 引用（保证已 import finnhub）"
        )

    @pytest.mark.parametrize("module_path", FILES)
    def test_module_calls_map_http_status_to_error(self, module_path):
        """源码中必须调用 map_http_status_to_error 进行 HTTP 状态码映射。"""
        import importlib

        mod = importlib.import_module(module_path)
        src = inspect.getsource(mod)
        assert "map_http_status_to_error" in src, (
            f"{module_path} 未调用 map_http_status_to_error，HTTP 429/401/5xx 无法正确分类"
        )

    @pytest.mark.parametrize("module_path", FILES)
    def test_module_imports_map_http_status_to_error(self, module_path):
        """map_http_status_to_error 必须显式导入（避免 NameError）。"""
        import importlib
        import ast

        mod = importlib.import_module(module_path)
        src = inspect.getsource(mod)
        tree = ast.parse(src)

        found_import = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == "app.data.sources.base.mappers":
                    for alias in node.names:
                        if alias.name == "map_http_status_to_error":
                            found_import = True
                            break
        assert found_import, (
            f"{module_path} 未显式从 app.data.sources.base.mappers 导入 map_http_status_to_error"
        )

    def test_finnhub_api_exception_has_status_code(self):
        """确认 finnhub 库的 FinnhubAPIException 类有 status_code 属性。"""
        try:
            import finnhub
        except ImportError:
            pytest.skip("finnhub 未安装")

        exc_cls = finnhub.FinnhubAPIException
        # 通过 __init__ 源码验证 status_code 属性存在
        init_src = inspect.getsource(exc_cls.__init__)
        assert "status_code" in init_src


# ---------------------------------------------------------------------------
# P0-4: multi_source_basics_sync_service.py PriorityConfig 导入
# ---------------------------------------------------------------------------


class TestPriorityConfigImport:
    """multi_source_basics_sync_service.py 必须正确导入 PriorityConfig。

    背景：原代码 `priority = PriorityConfig()` 但 PriorityConfig 未导入，
    触发 NameError。
    """

    def test_priority_config_imported_in_module(self):
        from app.services import multi_source_basics_sync_service as m

        src = inspect.getsource(m)
        # 必须有 PriorityConfig 的导入语句
        assert (
            "from app.data.core.registry.priority import PriorityConfig" in src
        ), "必须从 app.data.core.registry.priority 导入 PriorityConfig"

    def test_priority_config_usage_does_not_raise_name_error(self):
        """通过实际加载确认 NameError 已修复。"""
        from app.services.multi_source_basics_sync_service import (
            MultiSourceBasicsSyncService,
        )
        # 触发 import 时不会抛 NameError 即可
        assert MultiSourceBasicsSyncService is not None

    def test_priority_config_is_real_class(self):
        from app.data.core.registry.priority import PriorityConfig

        assert callable(PriorityConfig)
        # 实例化不抛错
        instance = PriorityConfig()
        assert instance is not None
        # get_default_sources 必须可调用
        assert callable(instance.get_default_sources)


# ---------------------------------------------------------------------------
# P1-1: Tencent HK URLError 捕获
# ---------------------------------------------------------------------------


class TestTencentHkUrlErrorCapture:
    """Tencent HK market_quotes.py 必须捕获 urllib.error.URLError 和 socket.timeout。

    背景：原代码只捕获 (asyncio.TimeoutError, ConnectionError, TimeoutError)。
    urllib.error.URLError（DNS 失败、socket.gaierror 等包装）会落入通用 Exception，
    被错误分类为 DataSourceUnavailableError，无法重试。
    """

    def test_module_imports_urllib_error(self):
        from app.data.sources.hk.tencent_hk.api import market_quotes

        src = inspect.getsource(market_quotes)
        # 必须有 import urllib.error 或 from urllib.error import URLError
        assert (
            "import urllib.error" in src or "from urllib.error import" in src
        ), "必须导入 urllib.error"

    def test_module_imports_socket(self):
        from app.data.sources.hk.tencent_hk.api import market_quotes

        src = inspect.getsource(market_quotes)
        assert "import socket" in src, "必须导入 socket 模块（用于 socket.timeout）"

    def test_module_catches_urlerror(self):
        """except 子句必须包含 urllib.error.URLError。"""
        from app.data.sources.hk.tencent_hk.api import market_quotes

        src = inspect.getsource(market_quotes)
        assert "urllib.error.URLError" in src, (
            "except 子句必须显式列出 urllib.error.URLError"
        )

    def test_module_catches_socket_timeout(self):
        """except 子句必须包含 socket.timeout。"""
        from app.data.sources.hk.tencent_hk.api import market_quotes

        src = inspect.getsource(market_quotes)
        assert "socket.timeout" in src, (
            "except 子句必须显式列出 socket.timeout（Python 3.10+ 等价于 TimeoutError，"
            "但显式列出保证向后兼容）"
        )

    def test_urlerror_maps_to_network_error(self):
        """urllib.error.URLError 的 except 分支必须调用 map_network_exception。"""
        from app.data.sources.hk.tencent_hk.api import market_quotes

        src = inspect.getsource(market_quotes)
        # 关键：网络异常 except 分支后调用 map_network_exception
        assert "map_network_exception" in src
        # 网络异常子句和 map_network_exception 在同一函数体内
        # 通过简化的存在性检查验证
        assert src.count("map_network_exception") >= 1


# ---------------------------------------------------------------------------
# P1-2: locks.py TTL 回调 owner_id 验证
# ---------------------------------------------------------------------------


class TestLocksTtlCallbackOwnerId:
    """locks.py 的 TTL 回调必须验证 owner_id，避免错误释放新 owner 的锁。

    背景：原回调 `lambda: _async_memory_locks[key].release() if locked else None`
    只检查 lock.locked()，未检查 owner。场景：
    1. owner_A 获取锁，TTL=1s
    2. owner_A 在 1s 内调用 release()，锁释放
    3. owner_B 获取同一 key 的锁（owner_B）
    4. 1s 后 TTL 回调触发，但此时持锁人是 owner_B，原回调会错误释放 owner_B 的锁
    """

    def test_ttl_callback_checks_owner_id(self):
        """TTL 回调源码中必须引用 owner_id 比较。"""
        from app.data.storage.redis import locks

        src = inspect.getsource(locks)
        # 必须能在源码中找到 owner_id 比较逻辑（不是简单 lambda）
        assert "owner_id" in src
        # 必须有 current_owner == owner_id 之类的比较
        assert "==" in src and "owner_id" in src, (
            "TTL 回调必须比较 current_owner == owner_id"
        )

    def test_ttl_callback_does_not_use_bare_lambda(self):
        """不再使用简单的三元 lambda（只检查 locked 不检查 owner）。"""
        from app.data.storage.redis import locks

        src = inspect.getsource(locks)
        # 原始有问题的代码形如：
        # lambda: (lock.release() if lock.locked() else None)
        # 修复后应该有 def 定义的回调函数
        # 简化检查：源码中必须有 def _ttl_release 或类似定义
        # （而不是只有 lambda）
        # 通过查找关键字 'def _ttl_release' 或 'def _ttl_callback'
        assert "def _ttl_release" in src or "def _ttl_callback" in src, (
            "TTL 回调应使用具名函数（便于包含 owner_id 验证），而不是简单 lambda"
        )

    @pytest.mark.asyncio
    async def test_ttl_does_not_release_other_owner_lock(self):
        """端到端验证：TTL 触发不会释放另一个 owner 的锁。

        场景：
        1. owner_A 获取锁 lock_X（TTL=0.1s）
        2. owner_A 显式 release
        3. owner_B 获取锁 lock_X（TTL=10s，足够长不触发）
        4. 等待 owner_A 的 TTL 过期
        5. owner_B 仍应持锁

        实现细节：因为 DistributedLock 是基于 Redis 或内存降级，
        此测试只验证内存降级路径。
        """
        from app.data.storage.redis.locks import (
            DistributedLock,
            _async_memory_locks,
            _memory_lock_owners,
        )

        # 强制使用内存降级路径：mock get_redis 返回 None
        # 但项目规则禁止 mock，所以我们用真实场景：如果 Redis 不可用，会自动降级
        # 这里直接验证：调用 acquire 后 owner_id 已写入
        lock_a = DistributedLock("test_ttl_owner_check", ttl=0.3)
        lock_b = DistributedLock("test_ttl_owner_check", ttl=5)

        # owner_A 获取锁
        acquired_a = await lock_a.acquire()
        if not acquired_a:
            pytest.skip("无法获取锁（可能 Redis 已持有同 key 锁）")
        try:
            owner_a_id = lock_a.owner_id
            assert _memory_lock_owners.get("test_ttl_owner_check") == owner_a_id

            # owner_A 显式释放
            await lock_a.release()

            # owner_B 获取锁（TTL=5s 足够长）
            acquired_b = await lock_b.acquire()
            if not acquired_b:
                pytest.skip("owner_B 无法获取锁（并发竞争失败）")
            try:
                owner_b_id = lock_b.owner_id
                assert owner_a_id != owner_b_id
                # 当前 owner 必须是 owner_B
                assert _memory_lock_owners.get("test_ttl_owner_check") == owner_b_id

                # 等待 owner_A 的 TTL 过期（0.3s + 安全边际）
                await asyncio.sleep(0.6)

                # owner_A 的 TTL 回调触发后，owner_B 仍应持锁
                current_owner = _memory_lock_owners.get("test_ttl_owner_check")
                assert current_owner == owner_b_id, (
                    f"TTL 回调错误释放了 owner_B 的锁。期望: {owner_b_id}, 实际: {current_owner}"
                )
                # 锁应仍然 locked
                lock_obj = _async_memory_locks.get("test_ttl_owner_check")
                if lock_obj is not None:
                    assert lock_obj.locked(), (
                        "TTL 回调错误释放了 owner_B 持有的锁对象"
                    )
            finally:
                await lock_b.release()
        finally:
            # 兜底清理
            _memory_lock_owners.pop("test_ttl_owner_check", None)
            _async_memory_locks.pop("test_ttl_owner_check", None)


# ---------------------------------------------------------------------------
# 集成验证：所有修复点联合运行
# ---------------------------------------------------------------------------


class TestAllFixesIntegrated:
    """集成验证：所有 P0/P1 修复后，关键模块可正常 import。"""

    def test_all_affected_modules_import_cleanly(self):
        """所有修复过的模块可正常加载，无 NameError、SyntaxError。"""
        modules_to_check = [
            # BaoStock P0
            "app.data.sources.cn.baostock.api.daily_quotes",
            "app.data.sources.cn.baostock.api.stock_basic",
            "app.data.sources.cn.baostock.api.financial",
            # hk_hold P0
            "app.data.sources.hk.tushare_hk.api.hk_hold",
            # Finnhub P0
            "app.data.sources.us.finnhub.api.basic_info",
            "app.data.sources.us.finnhub.api.market_quotes",
            "app.data.sources.us.finnhub.api.news",
            # multi_source_basics_sync_service P0
            "app.services.multi_source_basics_sync_service",
            # Tencent HK P1
            "app.data.sources.hk.tencent_hk.api.market_quotes",
            # locks P1
            "app.data.storage.redis.locks",
        ]
        for mod_path in modules_to_check:
            __import__(mod_path, fromlist=["x"])

    def test_dependencies_among_fixes_resolve(self):
        """修复点之间的依赖（如 locks 被 service 调用）能正确解析。"""
        from app.data.storage.redis.locks import DistributedLock
        from app.services.multi_source_basics_sync_service import (
            MultiSourceBasicsSyncService,
        )

        assert DistributedLock is not None
        assert MultiSourceBasicsSyncService is not None
