"""
测试 app/core/startup_validator.py — 启动配置验证器
"""

import pytest

from app.core.startup_validator import (
    ConfigLevel,
    ConfigItem,
    ValidationResult,
    StartupValidator,
    ConfigurationError,
    validate_startup_config,
)


class TestConfigLevel:

    def test_required_level(self):
        assert ConfigLevel.REQUIRED.value == "required"

    def test_recommended_level(self):
        assert ConfigLevel.RECOMMENDED.value == "recommended"

    def test_optional_level(self):
        assert ConfigLevel.OPTIONAL.value == "optional"


class TestConfigItem:

    def test_config_item_basic_fields(self):
        item = ConfigItem(
            key="TEST_KEY",
            level=ConfigLevel.REQUIRED,
            description="测试配置项",
        )
        assert item.key == "TEST_KEY"
        assert item.level == ConfigLevel.REQUIRED
        assert item.description == "测试配置项"
        assert item.example is None
        assert item.help_url is None
        assert item.validator is None

    def test_config_item_with_all_fields(self):
        validator = lambda v: len(v) > 0
        item = ConfigItem(
            key="TEST_KEY",
            level=ConfigLevel.RECOMMENDED,
            description="测试配置项",
            example="example_value",
            help_url="https://example.com",
            validator=validator,
        )
        assert item.example == "example_value"
        assert item.help_url == "https://example.com"
        assert item.validator is validator


class TestValidationResult:

    def test_default_values(self):
        result = ValidationResult(
            success=True,
            missing_required=[],
            missing_recommended=[],
            invalid_configs=[],
            warnings=[],
        )
        assert result.success is True
        assert result.missing_required == []
        assert result.missing_recommended == []
        assert result.invalid_configs == []
        assert result.warnings == []


class TestStartupValidator:

    def test_init_creates_empty_result(self):
        validator = StartupValidator()
        assert validator.result.success is True
        assert validator.result.missing_required == []
        assert validator.result.missing_recommended == []
        assert validator.result.invalid_configs == []
        assert validator.result.warnings == []

    def test_validate_with_all_required_present(self):
        """conftest.py 已设置所有必需环境变量"""
        validator = StartupValidator()
        result = validator.validate()
        assert isinstance(result, ValidationResult)
        assert result.success is True

    def test_validate_detects_missing_required(self):
        """缺少必需配置时验证失败"""
        from app.core.config import settings

        validator = StartupValidator()
        original_host = settings.MONGODB_HOST
        settings.MONGODB_HOST = ""
        try:
            validator._validate_required_configs()
            assert len(validator.result.missing_required) > 0
        finally:
            settings.MONGODB_HOST = original_host

    def test_validate_recommended_configs(self):
        """缺少推荐配置时加入 missing_recommended"""
        import os

        validator = StartupValidator()

        # 使用环境变量控制（settings 从 env 读取）
        original_deepseek = os.environ.get("DEEPSEEK_API_KEY", "")
        original_dashscope = os.environ.get("DASHSCOPE_API_KEY", "")
        original_tushare = os.environ.get("TUSHARE_TOKEN", "")

        os.environ["DEEPSEEK_API_KEY"] = ""
        os.environ["DASHSCOPE_API_KEY"] = ""
        os.environ["TUSHARE_TOKEN"] = ""
        try:
            validator._validate_recommended_configs()
            assert len(validator.result.missing_recommended) >= 3
        finally:
            if original_deepseek:
                os.environ["DEEPSEEK_API_KEY"] = original_deepseek
            else:
                os.environ.pop("DEEPSEEK_API_KEY", None)
            if original_dashscope:
                os.environ["DASHSCOPE_API_KEY"] = original_dashscope
            else:
                os.environ.pop("DASHSCOPE_API_KEY", None)
            if original_tushare:
                os.environ["TUSHARE_TOKEN"] = original_tushare
            else:
                os.environ.pop("TUSHARE_TOKEN", None)

    def test_validate_detects_invalid_jwt_secret_too_short(self):
        from app.core.config import settings

        validator = StartupValidator()
        original_jwt = settings.JWT_SECRET
        settings.JWT_SECRET = "short"
        try:
            validator._validate_required_configs()
            invalid_keys = [c.key for c, _ in validator.result.invalid_configs]
            assert "JWT_SECRET" in invalid_keys
        finally:
            settings.JWT_SECRET = original_jwt

    def test_validate_detects_insecure_jwt_default(self):
        from app.core.config import settings

        validator = StartupValidator()
        original_jwt = settings.JWT_SECRET
        original_csrf = settings.CSRF_SECRET
        settings.JWT_SECRET = "change-me-in-production"
        settings.CSRF_SECRET = "change-me-csrf-secret"
        try:
            validator._check_security_configs()
            assert len(validator.result.warnings) >= 2
        finally:
            settings.JWT_SECRET = original_jwt
            settings.CSRF_SECRET = original_csrf

    def test_validate_detects_insecure_csrf_default(self):
        from app.core.config import settings

        validator = StartupValidator()
        original_jwt = settings.JWT_SECRET
        original_csrf = settings.CSRF_SECRET
        settings.JWT_SECRET = "valid-long-secret-key-here"
        settings.CSRF_SECRET = "change-me-csrf-secret"
        try:
            validator._check_security_configs()
            warning_text = " ".join(validator.result.warnings)
            assert "CSRF_SECRET" in warning_text
        finally:
            settings.JWT_SECRET = original_jwt
            settings.CSRF_SECRET = original_csrf

    def test_validate_port_range_validator(self):
        redis_port_config = None
        for c in StartupValidator.REQUIRED_CONFIGS:
            if c.key == "REDIS_PORT":
                redis_port_config = c
                break

        assert redis_port_config is not None
        validator = redis_port_config.validator

        assert validator("6379") is True
        assert validator("27017") is True
        assert validator("1") is True
        assert validator("65535") is True
        assert validator("0") is False
        assert validator("65536") is False
        assert validator("-1") is False
        assert validator("abc") is False
        assert validator("") is False

    def test_validate_jwt_length_validator(self):
        jwt_config = None
        for c in StartupValidator.REQUIRED_CONFIGS:
            if c.key == "JWT_SECRET":
                jwt_config = c
                break

        assert jwt_config is not None
        validator = jwt_config.validator

        assert validator("a" * 16) is True
        assert validator("this-is-a-valid-jwt-secret-key") is True
        assert validator("short") is False
        assert validator("a" * 15) is False


class TestRaiseIfFailed:

    def test_raise_if_failed_no_error_on_success(self):
        validator = StartupValidator()
        validator.result.success = True
        validator.raise_if_failed()

    def test_raise_if_failed_raises_on_failure(self):
        validator = StartupValidator()
        validator.result.success = False
        validator.result.missing_required.append(
            ConfigItem(key="TEST_KEY", level=ConfigLevel.REQUIRED, description="测试")
        )
        with pytest.raises(ConfigurationError):
            validator.raise_if_failed()

    def test_raise_if_failed_error_message_contains_missing_keys(self):
        validator = StartupValidator()
        validator.result.success = False
        validator.result.missing_required.append(
            ConfigItem(key="MISSING_KEY_A", level=ConfigLevel.REQUIRED, description="测试A")
        )
        with pytest.raises(ConfigurationError, match="MISSING_KEY_A"):
            validator.raise_if_failed()


class TestValidateStartupConfig:

    def test_returns_validation_result(self):
        result = validate_startup_config()
        assert isinstance(result, ValidationResult)

    def test_success_when_all_required_present(self):
        result = validate_startup_config()
        assert result.success is True


class TestConfigurationError:

    def test_is_exception(self):
        assert issubclass(ConfigurationError, Exception)

    def test_can_be_caught(self):
        try:
            raise ConfigurationError("test error")
        except ConfigurationError as e:
            assert str(e) == "test error"
        except Exception:
            pytest.fail("ConfigurationError 应该能被自身捕获")
