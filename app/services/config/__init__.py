"""
配置管理服务包

提供统一的 ConfigServiceFacade，委托到各子服务。
保持与原始 ConfigService 完全相同的公共 API。
"""

from typing import List, Optional, Dict, Any

from app.models.config import (
    SystemConfig, LLMConfig, DataSourceConfig, DatabaseConfig,
    ModelProvider, DataSourceType, DatabaseType, LLMProvider,
    MarketCategory, DataSourceGrouping, ModelCatalog, ModelInfo
)

from app.services.config.market_service import MarketService
from app.services.config.data_source_service import DataSourceService
from app.services.config.system_service import SystemService
from app.services.config.database_service import DatabaseService
from app.services.config.llm_service import LLMService

__all__ = [
    "ConfigServiceFacade",
    "config_service",
    "MarketService",
    "DataSourceService",
    "SystemService",
    "DatabaseService",
    "LLMService",
]


class ConfigServiceFacade:
    """
    配置管理服务外观类

    将所有子服务的方法统一暴露，保持与原始 ConfigService 完全兼容的公共 API。
    """

    def __init__(self, db_manager=None):
        self._market = MarketService(db_manager=db_manager)
        self._data_source = DataSourceService(db_manager=db_manager)
        self._system = SystemService(db_manager=db_manager)
        self._database = DatabaseService(db_manager=db_manager)
        self._llm = LLMService(db_manager=db_manager)

    # ==================== 市场分类管理（委托 MarketService）====================

    async def get_market_categories(self) -> List[MarketCategory]:
        return await self._market.get_market_categories()

    async def add_market_category(self, category: MarketCategory) -> bool:
        return await self._market.add_market_category(category)

    async def update_market_category(self, category_id: str, updates: Dict[str, Any]) -> bool:
        return await self._market.update_market_category(category_id, updates)

    async def delete_market_category(self, category_id: str) -> bool:
        return await self._market.delete_market_category(category_id)

    # ==================== 数据源分组管理（委托 DataSourceService）====================

    async def get_datasource_groupings(self) -> List[DataSourceGrouping]:
        return await self._data_source.get_datasource_groupings()

    async def add_datasource_to_category(self, grouping: DataSourceGrouping) -> bool:
        return await self._data_source.add_datasource_to_category(grouping)

    async def remove_datasource_from_category(self, data_source_name: str, category_id: str) -> bool:
        return await self._data_source.remove_datasource_from_category(data_source_name, category_id)

    async def update_datasource_grouping(self, data_source_name: str, category_id: str, updates: Dict[str, Any]) -> bool:
        return await self._data_source.update_datasource_grouping(data_source_name, category_id, updates)

    async def update_category_datasource_order(self, category_id: str, ordered_datasources: List[Dict[str, Any]]) -> bool:
        return await self._data_source.update_category_datasource_order(category_id, ordered_datasources)

    # ==================== 系统配置管理（委托 SystemService）====================

    async def get_system_config(self) -> Optional[SystemConfig]:
        return await self._system.get_system_config()

    async def save_system_config(self, config: SystemConfig) -> bool:
        return await self._system.save_system_config(config)

    async def update_system_settings(self, settings: Dict[str, Any]) -> bool:
        return await self._system.update_system_settings(settings)

    async def get_system_settings(self) -> Dict[str, Any]:
        return await self._system.get_system_settings()

    async def set_default_data_source(self, data_source_name: str) -> bool:
        return await self._system.set_default_data_source(data_source_name)

    async def export_config(self) -> Dict[str, Any]:
        return await self._system.export_config()

    async def import_config(self, config_data: Dict[str, Any]) -> bool:
        return await self._system.import_config(config_data)

    async def migrate_legacy_config(self) -> bool:
        return await self._system.migrate_legacy_config()

    # ==================== 数据源测试（委托 DataSourceService）====================

    async def test_data_source_config(self, ds_config: DataSourceConfig) -> Dict[str, Any]:
        """测试数据源配置 - 通过 system_service 获取系统配置"""
        return await self._data_source.test_data_source_config(
            ds_config,
            system_config_getter=self._system.get_system_config
        )

    # ==================== 数据库配置管理（委托 DatabaseService）====================

    async def add_database_config(self, db_config: DatabaseConfig) -> bool:
        return await self._database.add_database_config(db_config)

    async def update_database_config(self, db_config: DatabaseConfig) -> bool:
        return await self._database.update_database_config(db_config)

    async def delete_database_config(self, db_name: str) -> bool:
        return await self._database.delete_database_config(db_name)

    async def get_database_config(self, db_name: str) -> Optional[DatabaseConfig]:
        return await self._database.get_database_config(db_name)

    async def get_database_configs(self) -> List[DatabaseConfig]:
        return await self._database.get_database_configs()

    async def test_database_config(self, db_config: DatabaseConfig) -> Dict[str, Any]:
        return await self._database.test_database_config(db_config)

    # ==================== 模型目录管理（委托 MarketService）====================

    async def get_model_catalog(self) -> List[ModelCatalog]:
        return await self._market.get_model_catalog()

    async def get_provider_models(self, provider: str) -> Optional[ModelCatalog]:
        return await self._market.get_provider_models(provider)

    async def save_model_catalog(self, catalog: ModelCatalog) -> bool:
        return await self._market.save_model_catalog(catalog)

    async def delete_model_catalog(self, provider: str) -> bool:
        return await self._market.delete_model_catalog(provider)

    async def init_default_model_catalog(self) -> bool:
        return await self._market.init_default_model_catalog()

    async def get_available_models(self) -> List[Dict[str, Any]]:
        return await self._market.get_available_models()

    # ==================== LLM 配置管理（委托 LLMService）====================

    async def update_llm_config(self, llm_config: LLMConfig) -> bool:
        return await self._llm.update_llm_config(llm_config)

    async def delete_llm_config(self, provider: str, model_name: str) -> bool:
        return await self._llm.delete_llm_config(provider, model_name)

    async def set_default_llm(self, model_name: str) -> bool:
        return await self._llm.set_default_llm(model_name)

    async def test_llm_config(self, llm_config: LLMConfig) -> Dict[str, Any]:
        return await self._llm.test_llm_config(llm_config)

    # ==================== LLM 厂家管理（委托 LLMService）====================

    async def get_llm_providers(self) -> List[LLMProvider]:
        return await self._llm.get_llm_providers()

    async def add_llm_provider(self, provider: LLMProvider) -> str:
        return await self._llm.add_llm_provider(provider)

    async def update_llm_provider(self, provider_id: str, update_data: Dict[str, Any]) -> bool:
        return await self._llm.update_llm_provider(provider_id, update_data)

    async def delete_llm_provider(self, provider_id: str) -> bool:
        return await self._llm.delete_llm_provider(provider_id)

    async def toggle_llm_provider(self, provider_id: str, is_active: bool) -> bool:
        return await self._llm.toggle_llm_provider(provider_id, is_active)

    async def init_aggregator_providers(self) -> Dict[str, Any]:
        return await self._llm.init_aggregator_providers()

    async def migrate_env_to_providers(self) -> Dict[str, Any]:
        return await self._llm.migrate_env_to_providers()

    async def test_provider_api(self, provider_id: str) -> dict:
        return await self._llm.test_provider_api(provider_id)

    async def fetch_provider_models(self, provider_id: str) -> dict:
        return await self._llm.fetch_provider_models(provider_id)


# 创建全局单例（与原始 config_service 兼容）
config_service = ConfigServiceFacade()
