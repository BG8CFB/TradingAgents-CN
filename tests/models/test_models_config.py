"""
系统配置相关数据模型单元测试
覆盖 ModelProvider, LLMProvider, LLMConfig, DataSourceConfig, DatabaseConfig,
MarketCategory, SystemConfig, UsageRecord 等
"""

import pytest
from datetime import datetime, timezone
from bson import ObjectId
from pydantic import ValidationError

from app.models.config import (
    ModelProvider,
    LLMProvider,
    ModelInfo,
    ModelCatalog,
    LLMProviderRequest,
    LLMProviderResponse,
    DataSourceType,
    DatabaseType,
    LLMConfig,
    DataSourceConfig,
    DatabaseConfig,
    MarketCategory,
    DataSourceGrouping,
    UsageRecord,
    UsageStatistics,
    SystemConfig,
    LLMConfigRequest,
    DataSourceConfigRequest,
    MarketCategoryRequest,
    DataSourceGroupingRequest,
    DatabaseConfigRequest,
    SystemConfigResponse,
    ConfigTestRequest,
    ConfigTestResponse,
)


# ---------------------------------------------------------------------------
# ModelProvider 枚举
# ---------------------------------------------------------------------------


class TestModelProvider:
    """大模型提供商枚举测试"""

    def test_common_providers(self):
        """常见提供商应存在"""
        assert ModelProvider.OPENAI == "openai"
        assert ModelProvider.DEEPSEEK == "deepseek"
        assert ModelProvider.QWEN == "qwen"
        assert ModelProvider.GEMINI == "gemini"
        assert ModelProvider.ANTHROPIC == "anthropic"

    def test_aggregator_providers(self):
        """聚合渠道提供商应存在"""
        assert ModelProvider.SILICONFLOW == "siliconflow"
        assert ModelProvider.OPENROUTER == "openrouter"
        assert ModelProvider.AI302 == "302ai"
        assert ModelProvider.ONEAPI == "oneapi"
        assert ModelProvider.CUSTOM_AGGREGATOR == "custom_aggregator"

    def test_enum_is_string(self):
        """枚举应继承 str"""
        assert isinstance(ModelProvider.OPENAI, str)

    def test_provider_count_reasonable(self):
        """提供商数量应 >= 15"""
        assert len(ModelProvider) >= 15


# ---------------------------------------------------------------------------
# LLMProvider
# ---------------------------------------------------------------------------


class TestLLMProvider:
    """大模型厂家配置模型测试"""

    def test_create_provider(self):
        """创建厂家配置"""
        provider = LLMProvider(
            name="openai",
            display_name="OpenAI",
        )
        assert provider.name == "openai"
        assert provider.display_name == "OpenAI"
        assert provider.is_active is True
        assert provider.supported_features == []
        assert provider.is_aggregator is False
        assert provider.aggregator_type is None

    def test_full_provider(self):
        """完整厂家配置"""
        provider = LLMProvider(
            name="302ai",
            display_name="302.AI",
            description="AI聚合平台",
            default_base_url="https://api.302.ai/v1",
            api_key="sk-test-key",
            is_aggregator=True,
            aggregator_type="openai_compatible",
            model_name_format="{provider}/{model}",
        )
        assert provider.is_aggregator is True
        assert provider.aggregator_type == "openai_compatible"
        assert provider.model_name_format == "{provider}/{model}"

    def test_populate_by_name(self):
        """通过 _id 别名填充"""
        oid = ObjectId()
        provider = LLMProvider(_id=oid, name="test", display_name="Test")
        assert provider.id == oid


# ---------------------------------------------------------------------------
# ModelInfo
# ---------------------------------------------------------------------------


class TestModelInfo:
    """模型信息测试"""

    def test_create_model_info(self):
        """创建模型信息"""
        info = ModelInfo(
            name="gpt-4",
            display_name="GPT-4",
        )
        assert info.name == "gpt-4"
        assert info.display_name == "GPT-4"
        assert info.is_deprecated is False
        assert info.capabilities == []

    def test_full_model_info(self):
        """完整模型信息"""
        info = ModelInfo(
            name="gpt-4",
            display_name="GPT-4",
            context_length=128000,
            max_tokens=4096,
            input_price_per_1k=0.03,
            output_price_per_1k=0.06,
            currency="USD",
            capabilities=["vision", "function_calling"],
            original_provider="openai",
            original_model="gpt-4-turbo",
        )
        assert info.context_length == 128000
        assert len(info.capabilities) == 2
        assert info.original_provider == "openai"


# ---------------------------------------------------------------------------
# ModelCatalog
# ---------------------------------------------------------------------------


class TestModelCatalog:
    """模型目录测试"""

    def test_create_catalog(self):
        """创建模型目录"""
        catalog = ModelCatalog(
            provider="openai",
            provider_name="OpenAI",
            models=[
                ModelInfo(name="gpt-4", display_name="GPT-4"),
            ],
        )
        assert catalog.provider == "openai"
        assert len(catalog.models) == 1


# ---------------------------------------------------------------------------
# LLMProviderResponse - 脱敏测试
# ---------------------------------------------------------------------------


class TestLLMProviderResponse:
    """大模型厂家响应测试"""

    def test_api_key_sanitization_long(self):
        """长 API Key 应脱敏"""
        resp = LLMProviderResponse(
            id="abc",
            name="test",
            display_name="Test",
            is_active=True,
            supported_features=[],
            api_key="sk-1234567890abcdef",
        )
        data = resp.model_dump()
        sanitized = data["api_key"]
        assert "****" in sanitized
        assert sanitized.startswith("sk-123")
        assert sanitized.endswith("cdef")

    def test_api_key_sanitization_short(self):
        """短 API Key 应完全遮盖"""
        resp = LLMProviderResponse(
            id="abc",
            name="test",
            display_name="Test",
            is_active=True,
            supported_features=[],
            api_key="short",
        )
        data = resp.model_dump()
        assert data["api_key"] == "****"

    def test_api_key_none(self):
        """无 API Key"""
        resp = LLMProviderResponse(
            id="abc",
            name="test",
            display_name="Test",
            is_active=True,
            supported_features=[],
        )
        data = resp.model_dump()
        assert data["api_key"] is None


# ---------------------------------------------------------------------------
# DataSourceType 枚举
# ---------------------------------------------------------------------------


class TestDataSourceType:
    """数据源类型枚举测试"""

    def test_china_sources(self):
        """中国市场数据源"""
        assert DataSourceType.TUSHARE == "tushare"
        assert DataSourceType.AKSHARE == "akshare"
        assert DataSourceType.BAOSTOCK == "baostock"

    def test_us_sources(self):
        """美国市场数据源"""
        assert DataSourceType.FINNHUB == "finnhub"
        assert DataSourceType.YAHOO_FINANCE == "yahoo_finance"

    def test_cache_source(self):
        """缓存数据源"""
        assert DataSourceType.MONGODB == "mongodb"


# ---------------------------------------------------------------------------
# DatabaseType 枚举
# ---------------------------------------------------------------------------


class TestDatabaseType:
    """数据库类型枚举测试"""

    def test_all_types(self):
        """所有数据库类型"""
        assert DatabaseType.MONGODB == "mongodb"
        assert DatabaseType.MYSQL == "mysql"
        assert DatabaseType.POSTGRESQL == "postgresql"
        assert DatabaseType.REDIS == "redis"
        assert DatabaseType.SQLITE == "sqlite"


# ---------------------------------------------------------------------------
# LLMConfig
# ---------------------------------------------------------------------------


class TestLLMConfig:
    """大模型配置模型测试"""

    def test_default_values(self):
        """默认值应正确"""
        config = LLMConfig(model_name="gpt-4")
        assert config.provider == "openai"
        assert config.model_name == "gpt-4"
        assert config.max_tokens == 4000
        assert config.temperature == 0.7
        assert config.timeout == 180
        assert config.retry_times == 3
        assert config.enabled is True
        assert config.capability_level == 2
        assert config.currency == "CNY"
        assert config.suitable_roles == ["both"]
        assert config.enable_memory is False
        assert config.enable_debug is False
        assert config.priority == 0

    def test_max_tokens_boundary(self):
        """max_tokens 边界值"""
        config = LLMConfig(model_name="test", max_tokens=1)
        assert config.max_tokens == 1
        config = LLMConfig(model_name="test", max_tokens=200000)
        assert config.max_tokens == 200000

    def test_max_tokens_out_of_range(self):
        """max_tokens 超范围应报错"""
        with pytest.raises(ValidationError):
            LLMConfig(model_name="test", max_tokens=0)
        with pytest.raises(ValidationError):
            LLMConfig(model_name="test", max_tokens=200001)

    def test_temperature_boundary(self):
        """temperature 边界值"""
        config = LLMConfig(model_name="test", temperature=0.0)
        assert config.temperature == 0.0
        config = LLMConfig(model_name="test", temperature=2.0)
        assert config.temperature == 2.0

    def test_temperature_out_of_range(self):
        """temperature 超范围应报错"""
        with pytest.raises(ValidationError):
            LLMConfig(model_name="test", temperature=-0.1)
        with pytest.raises(ValidationError):
            LLMConfig(model_name="test", temperature=2.1)

    def test_capability_level_boundary(self):
        """capability_level 边界值"""
        config = LLMConfig(model_name="test", capability_level=1)
        assert config.capability_level == 1
        config = LLMConfig(model_name="test", capability_level=5)
        assert config.capability_level == 5

    def test_capability_level_out_of_range(self):
        """capability_level 超范围应报错"""
        with pytest.raises(ValidationError):
            LLMConfig(model_name="test", capability_level=0)
        with pytest.raises(ValidationError):
            LLMConfig(model_name="test", capability_level=6)

    def test_model_name_required(self):
        """model_name 为必填"""
        with pytest.raises(ValidationError):
            LLMConfig()


# ---------------------------------------------------------------------------
# DataSourceConfig
# ---------------------------------------------------------------------------


class TestDataSourceConfig:
    """数据源配置模型测试"""

    def test_create_config(self):
        """创建数据源配置"""
        config = DataSourceConfig(
            name="tushare",
            type=DataSourceType.TUSHARE,
        )
        assert config.name == "tushare"
        assert config.type == "tushare"
        assert config.timeout == 30
        assert config.rate_limit == 100
        assert config.enabled is True
        assert config.priority == 0

    def test_full_config(self):
        """完整数据源配置"""
        config = DataSourceConfig(
            name="tushare",
            type=DataSourceType.TUSHARE,
            api_key="test_key",
            endpoint="https://api.tushare.pro",
            timeout=60,
            rate_limit=200,
            enabled=True,
            priority=10,
            market_categories=["CN"],
            display_name="Tushare Pro",
            provider="tushare",
        )
        assert config.api_key == "test_key"
        assert config.priority == 10
        assert config.market_categories == ["CN"]

    def test_missing_required_fields(self):
        """缺少必填字段应报错"""
        with pytest.raises(ValidationError):
            DataSourceConfig(name="test")
        with pytest.raises(ValidationError):
            DataSourceConfig(type=DataSourceType.TUSHARE)


# ---------------------------------------------------------------------------
# DatabaseConfig
# ---------------------------------------------------------------------------


class TestDatabaseConfig:
    """数据库配置模型测试"""

    def test_create_config(self):
        """创建数据库配置"""
        config = DatabaseConfig(
            name="main_db",
            type=DatabaseType.MONGODB,
            host="localhost",
            port=27017,
        )
        assert config.name == "main_db"
        assert config.host == "localhost"
        assert config.port == 27017
        assert config.pool_size == 10
        assert config.max_overflow == 20
        assert config.enabled is True

    def test_full_config(self):
        """完整数据库配置"""
        config = DatabaseConfig(
            name="main",
            type=DatabaseType.MONGODB,
            host="mongo.example.com",
            port=27017,
            username="admin",
            password="secret",
            database="tradingagents",
            pool_size=20,
            max_overflow=50,
        )
        assert config.username == "admin"
        assert config.database == "tradingagents"
        assert config.pool_size == 20

    def test_missing_required_fields(self):
        """缺少必填字段应报错"""
        with pytest.raises(ValidationError):
            DatabaseConfig(name="test", type=DatabaseType.MONGODB)
        with pytest.raises(ValidationError):
            DatabaseConfig(name="test", host="localhost")


# ---------------------------------------------------------------------------
# MarketCategory
# ---------------------------------------------------------------------------


class TestMarketCategory:
    """市场分类配置模型测试"""

    def test_create_category(self):
        """创建市场分类"""
        cat = MarketCategory(
            id="cn",
            name="A股",
            display_name="中国A股",
        )
        assert cat.id == "cn"
        assert cat.name == "A股"
        assert cat.display_name == "中国A股"
        assert cat.enabled is True
        assert cat.sort_order == 1

    def test_custom_category(self):
        """自定义市场分类"""
        cat = MarketCategory(
            id="hk",
            name="港股",
            display_name="香港股市",
            description="香港联合交易所",
            enabled=True,
            sort_order=2,
        )
        assert cat.description == "香港联合交易所"
        assert cat.sort_order == 2

    def test_missing_required_fields(self):
        """缺少必填字段应报错"""
        with pytest.raises(ValidationError):
            MarketCategory(id="cn")
        with pytest.raises(ValidationError):
            MarketCategory(name="A股", display_name="A股")


# ---------------------------------------------------------------------------
# SystemConfig
# ---------------------------------------------------------------------------


class TestSystemConfig:
    """系统配置模型测试"""

    def test_create_system_config(self):
        """创建系统配置"""
        config = SystemConfig(
            config_name="default",
            config_type="system",
        )
        assert config.config_name == "default"
        assert config.config_type == "system"
        assert config.llm_configs == []
        assert config.data_source_configs == []
        assert config.database_configs == []
        assert config.system_settings == {}
        assert config.version == 1
        assert config.is_active is True

    def test_with_llm_configs(self):
        """带 LLM 配置列表"""
        config = SystemConfig(
            config_name="default",
            config_type="system",
            llm_configs=[
                LLMConfig(model_name="gpt-4", provider="openai"),
                LLMConfig(model_name="qwen-max", provider="qwen"),
            ],
            default_llm="gpt-4",
        )
        assert len(config.llm_configs) == 2
        assert config.default_llm == "gpt-4"

    def test_populate_by_name(self):
        """通过 _id 别名填充"""
        oid = ObjectId()
        config = SystemConfig(_id=oid, config_name="test", config_type="system")
        assert config.id == oid


# ---------------------------------------------------------------------------
# UsageRecord
# ---------------------------------------------------------------------------


class TestUsageRecord:
    """使用记录模型测试"""

    def test_create_record(self):
        """创建使用记录"""
        record = UsageRecord(
            timestamp="2024-01-15T10:00:00Z",
            provider="openai",
            model_name="gpt-4",
            input_tokens=1000,
            output_tokens=500,
            cost=0.05,
            session_id="sess_001",
        )
        assert record.provider == "openai"
        assert record.input_tokens == 1000
        assert record.cost == 0.05
        assert record.currency == "CNY"
        assert record.analysis_type == "stock_analysis"

    def test_missing_required_fields(self):
        """缺少必填字段应报错"""
        with pytest.raises(ValidationError):
            UsageRecord(timestamp="2024-01-15")


# ---------------------------------------------------------------------------
# UsageStatistics
# ---------------------------------------------------------------------------


class TestUsageStatistics:
    """使用统计模型测试"""

    def test_default_values(self):
        """默认值"""
        stats = UsageStatistics()
        assert stats.total_requests == 0
        assert stats.total_input_tokens == 0
        assert stats.total_output_tokens == 0
        assert stats.total_cost == 0.0
        assert stats.cost_by_currency == {}
        assert stats.by_provider == {}
        assert stats.by_model == {}
        assert stats.by_date == {}


# ---------------------------------------------------------------------------
# ConfigTestRequest / ConfigTestResponse
# ---------------------------------------------------------------------------


class TestConfigTestModels:
    """配置测试请求/响应模型测试"""

    def test_config_test_request(self):
        """创建配置测试请求"""
        req = ConfigTestRequest(
            config_type="llm",
            config_data={"provider": "openai", "model": "gpt-4"},
        )
        assert req.config_type == "llm"
        assert "provider" in req.config_data

    def test_config_test_response(self):
        """创建配置测试响应"""
        resp = ConfigTestResponse(
            success=True,
            message="连接成功",
            response_time=0.5,
        )
        assert resp.success is True
        assert resp.response_time == 0.5
        assert resp.details is None
