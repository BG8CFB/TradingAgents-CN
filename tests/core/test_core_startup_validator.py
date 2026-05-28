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

    def test_validate_recommended_configs_infra_only(self):
        """推荐配置仅包含基础设施项（MONGODB_HOST/PORT/DB, REDIS_HOST/PORT）"""
        recommended_keys = [c.key for c in StartupValidator.RECOMMENDED_CONFIGS]
        assert "MONGODB_HOST" in recommended_keys
        assert "MONGODB_PORT" in recommended_keys
        assert "REDIS_HOST" in recommended_keys
        assert "REDIS_PORT" in recommended_keys
        # LLM API Key 和数据源 Token 不再在推荐配置中
        assert "DEEPSEEK_API_KEY" not in recommended_keys
        assert "DASHSCOPE_API_KEY" not in recommended_keys
        assert "TUSHARE_TOKEN" not in recommended_keys

    def test_required_configs_is_empty(self):
        """必需配置为空（JWT_SECRET 已改为自动生成，不再需要手动配置）"""
        assert StartupValidator.REQUIRED_CONFIGS == []

    def test_validate_detects_unconfigured_jwt_secret(self):
        """检查 JWT_SECRET 未在环境变量中配置时产生警告"""
        import os

        validator = StartupValidator()
        original = os.environ.get("JWT_SECRET")
        os.environ.pop("JWT_SECRET", None)
        try:
            validator._check_security_configs()
            warning_text = " ".join(validator.result.warnings)
            assert "JWT_SECRET" in warning_text
        finally:
            if original is not None:
                os.environ["JWT_SECRET"] = original

    def test_validate_detects_unconfigured_csrf_secret(self):
        """检查 CSRF_SECRET 未在环境变量中配置时产生警告"""
        import os

        validator = StartupValidator()
        original = os.environ.get("CSRF_SECRET")
        os.environ.pop("CSRF_SECRET", None)
        try:
            validator._check_security_configs()
            warning_text = " ".join(validator.result.warnings)
            assert "CSRF_SECRET" in warning_text
        finally:
            if original is not None:
                os.environ["CSRF_TOKEN"] = original

    def test_validate_port_range_validator(self):
        """验证端口范围校验器（REDIS_PORT 已移至 RECOMMENDED_CONFIGS）"""
        redis_port_config = None
        for c in StartupValidator.RECOMMENDED_CONFIGS:
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
