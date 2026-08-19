"""tushare_common 共享层单元测试 — 错误分类 / 调用模板 / 客户端。

不依赖真实 Tushare Token 与网络：

- ``classify_tushare_error`` 用携带 ``code`` 属性的真实异常实例验证分类
- ``call_tushare`` 用手写的最小 pro_api 替身（真实类、真实 DataFrame、
  真实异常抛出路径）驱动模板逻辑 —— 与 conftest.SimulatedMongoDB 同精神，
  不属于 mock 库
- ``TushareClient`` 用不存在的 source_name 验证 Token 未配置路径
"""

import pandas as pd
import pytest

from app.data.sources.base.exceptions import (
    DataNotFoundError,
    InsufficientCreditsError,
    NetworkError,
    RateLimitedError,
    TokenInvalidError,
)
from app.data.sources.tushare_common.caller import call_tushare
from app.data.sources.tushare_common.client import (
    TushareClient,
    classify_tushare_error,
)


class _TushareApiError(Exception):
    """模拟 Tushare SDK 抛出的带 code 属性的业务异常（真实异常子类）。"""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class _FakeProApi:
    """最小 pro_api 替身：按 method 名返回预设结果或抛真实异常。"""

    def __init__(self, results=None, errors=None):
        self._results = results or {}
        self._errors = errors or {}

    def daily(self, **params):
        if "daily" in self._errors:
            raise self._errors["daily"]
        return self._results.get("daily")

    def missing_endpoint(self):  # pragma: no cover - 不会被调用
        raise AssertionError("不应被调用")


class TestClassifyTushareError:
    """classify_tushare_error — 错误码优先、消息关键字兜底。"""

    def test_code_10001_maps_to_token_invalid(self):
        err = classify_tushare_error(
            _TushareApiError(10001, "用户未登录或token无效"),
            "tushare_hk",
            "daily_quotes",
        )
        assert isinstance(err, TokenInvalidError)

    def test_code_5003_maps_to_rate_limited(self):
        err = classify_tushare_error(
            _TushareApiError(5003, "频次超限"), "tushare", "daily_quotes"
        )
        assert isinstance(err, RateLimitedError)

    def test_code_40203_maps_to_insufficient_credits(self):
        err = classify_tushare_error(
            _TushareApiError(40203, "积分不足"), "tushare_us", "fina_indicator"
        )
        assert isinstance(err, InsufficientCreditsError)

    def test_code_40002_maps_to_data_not_found(self):
        err = classify_tushare_error(
            _TushareApiError(40002, "无数据"), "tushare_hk", "adj_factors"
        )
        assert isinstance(err, DataNotFoundError)

    def test_message_keyword_token_fallback(self):
        # 无 code：消息含 "token" → TokenInvalidError
        err = classify_tushare_error(
            Exception("invalid token provided"), "tushare", "daily_quotes"
        )
        assert isinstance(err, TokenInvalidError)

    def test_message_keyword_credits_fallback(self):
        err = classify_tushare_error(
            Exception("抱歉，您积分不足"), "tushare_hk", "daily_quotes", min_credits=2000
        )
        assert isinstance(err, InsufficientCreditsError)

    def test_unrecognized_returns_none(self):
        err = classify_tushare_error(
            Exception("some unknown failure"), "tushare", "daily_quotes"
        )
        assert err is None

    def test_code_zero_returns_none(self):
        # code=0 是 Tushare 成功响应，不应映射为异常
        err = classify_tushare_error(
            _TushareApiError(0, "ok"), "tushare", "daily_quotes"
        )
        assert err is None


class TestCallTushare:
    """call_tushare 调用模板 — 空结果 / 错误码 / 网络 / 前置校验。"""

    @pytest.mark.asyncio
    async def test_none_api_returns_none(self):
        result = await call_tushare(None, "daily", "tushare_hk", "daily_quotes")
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_method_returns_none(self):
        api = _FakeProApi()
        result = await call_tushare(
            api, "no_such_endpoint", "tushare_hk", "daily_quotes"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_dataframe_raises_data_not_found(self):
        api = _FakeProApi(results={"daily": pd.DataFrame()})
        with pytest.raises(DataNotFoundError):
            await call_tushare(api, "daily", "tushare_hk", "daily_quotes", "00700.HK")

    @pytest.mark.asyncio
    async def test_none_result_raises_data_not_found(self):
        api = _FakeProApi(results={"daily": None})
        with pytest.raises(DataNotFoundError):
            await call_tushare(api, "daily", "tushare_hk", "daily_quotes", "00700.HK")

    @pytest.mark.asyncio
    async def test_tushare_code_error_maps_to_rate_limited(self):
        api = _FakeProApi(errors={"daily": _TushareApiError(5003, "频次超限")})
        with pytest.raises(RateLimitedError):
            await call_tushare(api, "daily", "tushare", "daily_quotes")

    @pytest.mark.asyncio
    async def test_tushare_code_error_maps_to_token_invalid(self):
        api = _FakeProApi(errors={"daily": _TushareApiError(10001, "未登录")})
        with pytest.raises(TokenInvalidError):
            await call_tushare(api, "daily", "tushare_us", "daily_quotes")

    @pytest.mark.asyncio
    async def test_connection_error_maps_to_network_error(self):
        api = _FakeProApi(errors={"daily": ConnectionError("refused")})
        with pytest.raises(NetworkError):
            await call_tushare(api, "daily", "tushare", "daily_quotes")

    @pytest.mark.asyncio
    async def test_unknown_error_maps_to_unavailable(self):
        from app.data.sources.base.exceptions import DataSourceUnavailableError

        api = _FakeProApi(errors={"daily": ValueError("weird failure")})
        with pytest.raises(DataSourceUnavailableError):
            await call_tushare(api, "daily", "tushare_hk", "daily_quotes", "00700.HK")

    @pytest.mark.asyncio
    async def test_valid_dataframe_returned(self):
        df = pd.DataFrame({"ts_code": ["00700.HK"], "close": [300.0]})
        api = _FakeProApi(results={"daily": df})
        result = await call_tushare(
            api, "daily", "tushare_hk", "daily_quotes", "00700.HK"
        )
        assert result is df


class TestTushareClientTokenUnconfigured:
    """Token 未配置路径 — 使用不存在的 source_name，不触网。"""

    def test_connect_sync_fails_when_token_missing(self):
        client = TushareClient(
            source_name="tushare_no_such_source_xyz",
            probe_endpoint="stock_basic",
        )
        # DB（system_configs）与 ENV 链都不可能配置该源 → Token 为 None
        assert client.resolve_token() is None
        assert client.connect_sync() is False
        assert client.is_available() is False
        assert client.get_api() is None

    def test_invalidate_then_single_rebuild(self):
        client = TushareClient(
            source_name="tushare_no_such_source_xyz",
            probe_endpoint="stock_basic",
        )
        client.api = object()  # 预置一个"连接"
        client.connected = True
        assert client.get_api() is not None

        client.invalidate()
        assert client.api is None and client.connected is False
        # 第一次重建尝试（Token 缺失 → 失败返回 None）
        assert client.get_api() is None
        # 第二次起不再重建（_rebuild_count 已达上限）
        assert client.get_api() is None
        assert client._rebuild_count == 1


class TestResolveApiAgainstDataApiMagic:
    """_resolve_api 必须免疫 tushare DataApi 的万能 __getattr__。

    DataApi.__getattr__ 对任意属性返回 partial(query, name)，
    历史 bug：getattr(api, "get_api") 变成执行 query("get_api") →
    服务端报"请指定正确的接口名" → HK/US 全部 fetch 静默失败。
    用真实 tushare DataApi 实例（不发网络请求）回归。
    """

    def test_bare_data_api_passthrough(self):
        from tushare.pro.client import DataApi

        from app.data.sources.tushare_common.caller import _resolve_api

        api = DataApi(token="dummy-token-for-type-check-only")
        # 关键：getattr(api, "get_api") 是 callable（__getattr__ 魔法），
        # _resolve_api 必须原样返回 DataApi 而不是误调 query("get_api")
        assert callable(getattr(api, "get_api"))
        assert _resolve_api(api) is api

    async def test_call_tushare_with_bare_data_api_uses_given_endpoint(self):
        """裸 DataApi 走 call_tushare 时方法名必须原样生效（不触发 get_api 探测）。"""

        class _RecordingApi:
            """记录被调用接口名的最小替身（真实类，非 mock 库）。"""

            def __init__(self):
                self.called = None

            def hk_basic(self, **kwargs):
                self.called = ("hk_basic", kwargs)
                return pd.DataFrame([{"ts_code": "00700.HK"}])

        from app.data.sources.tushare_common.caller import _resolve_api, call_tushare

        api = _RecordingApi()
        df = await call_tushare(api, "hk_basic", "tushare_hk", "basic_info", "test")
        assert len(df) == 1
        assert api.called[0] == "hk_basic"
