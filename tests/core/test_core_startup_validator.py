"""
测试 app/core/startup_validator.py — 启动配置验证器
"""

from unittest.mock import patch, MagicMock

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
    """测试 ConfigLevel 枚举"""

    def test_required_level(self):
        assert ConfigLevel.REQUIRED.value == "required"

    def test_recommended_level(self):
        assert ConfigLevel.RECOMMENDED.value == "recommended"

    def test_optional_level(self):
        assert ConfigLevel.OPTIONAL.value == "optional"


class TestConfigItem:
    """测试 ConfigItem 数据类"""

    def test_config_item_basic_fields(self):
        """基本字段正确"""
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
        """所有字段正确"""
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
    """测试 ValidationResult 数据类"""

    def test_default_values(self):
        """默认值正确"""
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
    """测试 StartupValidator 核心验证逻辑"""

    def test_init_creates_empty_result(self):
        """初始化创建空的验证结果"""
        validator = StartupValidator()
        assert validator.result.success is True
        assert validator.result.missing_required == []
        assert validator.result.missing_recommended == []
        assert validator.result.invalid_configs == []
        assert validator.result.warnings == []

    def test_validate_with_all_required_present(self):
        """所有必需配置都存在时验证通过"""
        validator = StartupValidator()
        # conftest.py 已设置所有必需环境变量
        result = validator.validate()
        assert isinstance(result, ValidationResult)
        # 在测试环境中，必需配置应该都已通过 conftest 设置
        assert result.success is True

    def test_validate_detects_missing_required(self):
        """缺少必需配置时验证失败"""
        validator = StartupValidator()

        # 创建一个配置对象模拟 MONGODB_HOST 为空
        mock_settings = MagicMock()
        mock_settings.MONGODB_HOST = ""
        mock_settings.MONGODB_PORT = "27017"
        mock_settings.MONGODB_DATABASE = "tradingagents"
        mock_settings.REDIS_HOST = "localhost"
        mock_settings.REDIS_PORT = "6379"
        mock_settings.JWT_SECRET = "test-jwt-secret-for-testing-only"

        with patch("app.core.startup_validator.settings", mock_settings):
            validator._validate_required_configs()
            assert len(validator.result.missing_required) > 0

    def test_validate_recommended_configs(self):
        """缺少推荐配置时加入 missing_recommended"""
        validator = StartupValidator()

        # 创建一个配置对象模拟所有推荐 API key 都为空
        mock_settings = MagicMock()
        mock_settings.DEEPSEEK_API_KEY = ""
        mock_settings.DASHSCOPE_API_KEY = ""
        mock_settings.TUSHARE_TOKEN = ""

        with patch("app.core.startup_validator.settings", mock_settings):
            validator._validate_recommended_configs()
            # 至少应该有 3 个缺少的推荐配置
            assert len(validator.result.missing_recommended) >= 3

    def test_validate_detects_invalid_jwt_secret_too_short(self):
        """JWT_SECRET 过短时检测为无效配置"""
        validator = StartupValidator()

        mock_settings = MagicMock()
        mock_settings.MONGODB_HOST = "localhost"
        mock_settings.MONGODB_PORT = "27017"
        mock_settings.MONGODB_DATABASE = "tradingagents"
        mock_settings.REDIS_HOST = "localhost"
        mock_settings.REDIS_PORT = "6379"
        mock_settings.JWT_SECRET = "short"  # 少于 16 个字符

        with patch("app.core.startup_validator.settings", mock_settings):
            validator._validate_required_configs()
            # JWT_SECRET 过短应被检测为无效
            invalid_keys = [c.key for c, _ in validator.result.invalid_configs]
            assert "JWT_SECRET" in invalid_keys

    def test_validate_detects_insecure_jwt_default(self):
        """检测到不安全的 JWT_SECRET 默认值"""
        validator = StartupValidator()

        mock_settings = MagicMock()
        mock_settings.JWT_SECRET = "change-me-in-production"
        mock_settings.CSRF_SECRET = "change-me-csrf-secret"

        with patch("app.core.startup_validator.settings", mock_settings):
            validator._check_security_configs()
            assert len(validator.result.warnings) >= 2

    def test_validate_detects_insecure_csrf_default(self):
        """检测到不安全的 CSRF_SECRET 默认值"""
        validator = StartupValidator()

        mock_settings = MagicMock()
        mock_settings.JWT_SECRET = "valid-long-secret-key-here"
        mock_settings.CSRF_SECRET = "change-me-csrf-secret"

        with patch("app.core.startup_validator.settings", mock_settings):
            validator._check_security_configs()
            warning_text = " ".join(validator.result.warnings)
            assert "CSRF_SECRET" in warning_text

    def test_validate_port_range_validator(self):
        """端口范围验证器正确工作"""
        # 从 REQUIRED_CONFIGS 找到 REDIS_PORT 的 validator
        redis_port_config = None
        for c in StartupValidator.REQUIRED_CONFIGS:
            if c.key == "REDIS_PORT":
                redis_port_config = c
                break

        assert redis_port_config is not None
        validator = redis_port_config.validator

        # 有效端口
        assert validator("6379") is True
        assert validator("27017") is True
        assert validator("1") is True
        assert validator("65535") is True

        # 无效端口
        assert validator("0") is False
        assert validator("65536") is False
        assert validator("-1") is False
        assert validator("abc") is False
        assert validator("") is False

    def test_validate_jwt_length_validator(self):
        """JWT 密钥长度验证器正确工作"""
        jwt_config = None
        for c in StartupValidator.REQUIRED_CONFIGS:
            if c.key == "JWT_SECRET":
                jwt_config = c
                break

        assert jwt_config is not None
        validator = jwt_config.validator

        # 有效长度
        assert validator("a" * 16) is True
        assert validator("this-is-a-valid-jwt-secret-key") is True

        # 无效长度
        assert validator("short") is False
        assert validator("a" * 15) is False


class TestRaiseIfFailed:
    """测试 raise_if_failed() 方法"""

    def test_raise_if_failed_no_error_on_success(self):
        """验证成功时不抛异常"""
        validator = StartupValidator()
        validator.result.success = True
        # 不应抛出异常
        validator.raise_if_failed()

    def test_raise_if_failed_raises_on_failure(self):
        """验证失败时抛出 ConfigurationError"""
        validator = StartupValidator()
        validator.result.success = False
        validator.result.missing_required.append(
            ConfigItem(
                key="TEST_KEY",
                level=ConfigLevel.REQUIRED,
                description="测试",
            )
        )
        with pytest.raises(ConfigurationError):
            validator.raise_if_failed()

    def test_raise_if_failed_error_message_contains_missing_keys(self):
        """错误消息包含缺少的配置键名"""
        validator = StartupValidator()
        validator.result.success = False
        validator.result.missing_required.append(
            ConfigItem(
                key="MISSING_KEY_A",
                level=ConfigLevel.REQUIRED,
                description="测试A",
            )
        )
        with pytest.raises(ConfigurationError, match="MISSING_KEY_A"):
            validator.raise_if_failed()


class TestValidateStartupConfig:
    """测试 validate_startup_config() 便捷函数"""

    def test_returns_validation_result(self):
        """返回 ValidationResult 实例"""
        # conftest 已设置所有必需配置
        result = validate_startup_config()
        assert isinstance(result, ValidationResult)

    def test_success_when_all_required_present(self):
        """所有必需配置存在时成功"""
        result = validate_startup_config()
        assert result.success is True


class TestConfigurationError:
    """测试 ConfigurationError 异常"""

    def test_is_exception(self):
        """ConfigurationError 是 Exception 子类"""
        assert issubclass(ConfigurationError, Exception)

    def test_can_be_caught(self):
        """可以被 try/except 捕获"""
        try:
            raise ConfigurationError("test error")
        except ConfigurationError as e:
            assert str(e) == "test error"
        except Exception:
            pytest.fail("ConfigurationError 应该能被自身捕获")
