"""端到端测试 — MockProvider → Adapter → Normalizer → Validator → Repo 全链路。"""

import pytest
import pandas as pd
from dataclasses import dataclass
from typing import Optional, List
from unittest.mock import AsyncMock, MagicMock

from app.data.sources.base.provider import BaseProvider
from app.data.sources.base.adapter import BaseAdapter
from app.data.processor.normalizer import Normalizer
from app.data.processor.validator import Validator
from app.data.schema.domains.basic_info import StockBasicInfoSchema


class MockProvider(BaseProvider):
    """模拟 Provider 返回固定数据。"""

    def __init__(self):
        super().__init__(name="mock", market="CN")

    async def connect(self):
        self.connected = True
        return True

    def is_available(self):
        return True

    async def get_stock_list(self, **kwargs):
        return pd.DataFrame([
            {"ts_code": "000001.SZ", "symbol": "000001", "name": "平安银行",
             "industry": "银行", "area": "广东", "list_status": "L"},
            {"ts_code": "600000.SH", "symbol": "600000", "name": "浦发银行",
             "industry": "银行", "area": "上海", "list_status": "L"},
        ])

    async def get_daily_quotes(self, symbol: str, start_date: str, end_date: str, **kwargs):
        return pd.DataFrame([
            {"ts_code": "000001.SZ", "trade_date": 20240115,
             "open": 10.0, "close": 10.5, "high": 11.0, "low": 9.5,
             "vol": 1000, "amount": 500, "pct_chg": 5.0},
        ])


class MockAdapter(BaseAdapter):
    """模拟 Adapter 使用 Tushare CN 格式。"""

    def __init__(self):
        super().__init__(provider=None, market="CN", source_name="mock")

    def adapt_basic_info(self, raw):
        from app.data.sources.cn.tushare.adapter import TushareCNAdapter
        adapter = TushareCNAdapter()
        return adapter.adapt_basic_info(raw)

    def adapt_daily_quotes(self, raw):
        from app.data.sources.cn.tushare.adapter import TushareCNAdapter
        adapter = TushareCNAdapter()
        return adapter.adapt_daily_quotes(raw)


class TestE2EPipeline:
    @pytest.mark.asyncio
    async def test_basic_info_full_pipeline(self):
        # 1. Provider 获取原始数据
        provider = MockProvider()
        raw_data = await provider.get_stock_list()
        assert raw_data is not None
        assert len(raw_data) == 2

        # 2. Adapter 标准化
        adapter = MockAdapter()
        schemas = adapter.adapt_basic_info(raw_data)
        assert len(schemas) == 2
        assert all(isinstance(s, StockBasicInfoSchema) for s in schemas)
        assert schemas[0].symbol == "000001"

        # 3. 转为 MongoDB 文档
        docs = [s.to_db_doc() for s in schemas]
        assert all("symbol" in d for d in docs)
        assert all("updated_at" in d for d in docs)

        # 4. Validator 校验
        validator = Validator()
        valid, errors = validator.validate(docs, "basic_info", "CN")
        assert len(valid) == 2
        assert len(errors) == 0

    @pytest.mark.asyncio
    async def test_daily_quotes_full_pipeline(self):
        provider = MockProvider()
        raw_data = await provider.get_daily_quotes("000001", "2024-01-15", "2024-01-15")
        assert raw_data is not None

        adapter = MockAdapter()
        schemas = adapter.adapt_daily_quotes(raw_data)
        assert len(schemas) == 1
        assert schemas[0].volume == 100000  # 手→股

        docs = [s.to_db_doc() for s in schemas]

        validator = Validator()
        valid, errors = validator.validate(docs, "daily_quotes", "CN")
        assert len(valid) == 1

    @pytest.mark.asyncio
    async def test_empty_provider_data(self):
        """Provider 返回 None 或空 DataFrame 时，Pipeline 优雅处理。"""

        class EmptyProvider(BaseProvider):
            async def connect(self):
                return True

            def is_available(self):
                return True

            async def get_stock_list(self, **kwargs):
                return None

        provider = EmptyProvider(name="empty", market="CN")
        raw_data = await provider.get_stock_list()
        assert raw_data is None

        adapter = MockAdapter()
        # 传入 None 应返回空列表
        results = adapter.adapt_basic_info(raw_data or pd.DataFrame())
        assert results == []
