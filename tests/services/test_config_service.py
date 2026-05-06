"""测试配置服务门面"""

import pytest


class TestConfigServiceImport:
    def test_config_service_importable(self):
        from app.services.config_service import config_service
        assert config_service is not None

    def test_config_service_has_methods(self):
        from app.services.config_service import config_service
        assert hasattr(config_service, "get_system_config")
        assert callable(config_service.get_system_config)
