"""测试 BaseProvider 和 BaseAdapter 抽象类契约。"""

import pytest
import pandas as pd

from app.data.sources.base.provider import BaseProvider
from app.data.sources.base.adapter import BaseAdapter


class ConcreteProvider(BaseProvider):
    async def connect(self):
        self.connected = True
        return True

    def is_available(self):
        return self.connected


class ConcreteAdapter(BaseAdapter):
    pass


class TestBaseProvider:
    def test_init(self):
        p = ConcreteProvider(name="test", market="CN")
        assert p.name == "test"
        assert p.market == "CN"
        assert p.connected is False

    @pytest.mark.asyncio
    async def test_connect(self):
        p = ConcreteProvider(name="test", market="CN")
        result = await p.connect()
        assert result is True
        assert p.connected is True

    @pytest.mark.asyncio
    async def test_unsupported_methods_raise_not_implemented(self):
        p = ConcreteProvider(name="test", market="CN")
        with pytest.raises(NotImplementedError):
            await p.get_stock_list()
        with pytest.raises(NotImplementedError):
            await p.get_daily_quotes("000001", "2024-01-01", "2024-12-31")
        with pytest.raises(NotImplementedError):
            await p.get_news("000001", "2024-01-01", "2024-12-31")


class TestBaseAdapter:
    def test_init(self):
        p = ConcreteProvider(name="test", market="CN")
        a = ConcreteAdapter(provider=p, market="CN", source_name="test")
        assert a.market == "CN"
        assert a.source_name == "test"

    def test_unsupported_methods_raise(self):
        a = ConcreteAdapter(provider=None, market="CN", source_name="test")
        with pytest.raises(NotImplementedError):
            a.adapt_basic_info(pd.DataFrame())
        with pytest.raises(NotImplementedError):
            a.adapt_daily_quotes(pd.DataFrame())
        with pytest.raises(NotImplementedError):
            a.adapt_news(pd.DataFrame())
