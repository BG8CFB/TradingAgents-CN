"""
测试 app/core/config.py — Settings 配置类
"""

import importlib
import os
import sys
import warnings

import pytest
from test_infra import env_vars

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSettingsDefaults:
    """测试 Settings 类的默认值"""

    def test_debug_default(self, settings):
        """DEBUG 默认为 True"""
        assert settings.DEBUG is True

    def test_host_default(self, settings):
        """HOST 默认为 0.0.0.0"""
        assert settings.HOST == "0.0.0.0"

    def test_port_default(self, settings):
        """PORT 默认为 8000"""
        assert settings.PORT == 8000

    def test_allowed_origins_default(self, settings):
        """ALLOWED_ORIGINS 默认包含 '*' 或具体来源列表"""
        # 环境变量可能覆盖默认值，因此只检查类型和非空
        assert isinstance(settings.ALLOWED_ORIGINS, list)
        assert len(settings.ALLOWED_ORIGINS) > 0

    def test_allowed_hosts_default(self, settings):
        """ALLOWED_HOSTS 默认为 ['*']"""
        assert settings.ALLOWED_HOSTS == ["*"]

    def test_mongodb_database_default(self, settings):
        """MONGODB_DATABASE 默认为 'tradingagents'"""
        # conftest 可能通过环境变量覆盖为 tradingagents_test
        db_name = settings.MONGODB_DATABASE
        assert db_name in ("tradingagents", "tradingagents_test")

    def test_jwt_algorithm_default(self, settings):
        """JWT_ALGORITHM 默认为 HS256"""
        assert settings.JWT_ALGORITHM == "HS256"

    def test_access_token_expire_default(self):
        """ACCESS_TOKEN_EXPIRE_MINUTES 的 Field 默认值为 60（不被 .env 覆盖时）"""
        from app.core.config import Settings
        field_info = Settings.model_fields["ACCESS_TOKEN_EXPIRE_MINUTES"]
        assert field_info.default == 60

    def test_refresh_token_expire_default(self, settings):
        """REFRESH_TOKEN_EXPIRE_DAYS 默认为 30"""
        assert settings.REFRESH_TOKEN_EXPIRE_DAYS == 30

    def test_log_level_default(self, settings):
        """LOG_LEVEL 默认为 INFO"""
        assert settings.LOG_LEVEL == "INFO"

    def test_cache_ttl_default(self, settings):
        """CACHE_TTL 默认为 3600（1小时）"""
        assert settings.CACHE_TTL == 3600

    def test_bcrypt_rounds_default(self, settings):
        """BCRYPT_ROUNDS 默认为 12"""
        assert settings.BCRYPT_ROUNDS == 12


class TestMongoURI:
    """测试 MONGO_URI 属性"""

    def test_mongo_uri_with_auth(self):
        """带认证的 MONGO_URI 构建正确"""
        from app.core.config import Settings

        s = Settings(
            MONGODB_HOST="db.example.com",
            MONGODB_PORT=27018,
            MONGODB_USERNAME="admin",
            MONGODB_PASSWORD="secret123",
            MONGODB_DATABASE="mydb",
            MONGODB_AUTH_SOURCE="admin",
        )
        uri = s.MONGO_URI
        expected = (
            "mongodb://admin:secret123@db.example.com:27018"
            "/mydb?authSource=admin"
        )
        assert uri == expected

    def test_mongo_uri_without_auth(self):
        """无认证的 MONGO_URI 构建正确"""
        from app.core.config import Settings

        s = Settings(
            MONGODB_HOST="localhost",
            MONGODB_PORT=27017,
            MONGODB_USERNAME="",
            MONGODB_PASSWORD="",
            MONGODB_DATABASE="tradingagents",
        )
        uri = s.MONGO_URI
        assert uri == "mongodb://localhost:27017/tradingagents"
        # 确保不含认证信息
        assert "@" not in uri

    def test_mongo_uri_only_username(self):
        """仅提供用户名（无密码）时走无认证路径"""
        from app.core.config import Settings

        s = Settings(
            MONGODB_HOST="localhost",
            MONGODB_PORT=27017,
            MONGODB_USERNAME="admin",
            MONGODB_PASSWORD="",
            MONGODB_DATABASE="testdb",
        )
        uri = s.MONGO_URI
        # 只要密码为空就不应带认证
        assert "@" not in uri

    def test_mongo_db_property(self, settings):
        """MONGO_DB 属性返回数据库名"""
        assert settings.MONGO_DB == settings.MONGODB_DATABASE


class TestRedisURL:
    """测试 REDIS_URL 属性"""

    def test_redis_url_with_password(self):
        """带密码的 REDIS_URL 构建正确"""
        from app.core.config import Settings

        s = Settings(
            REDIS_HOST="redis.example.com",
            REDIS_PORT=6380,
            REDIS_PASSWORD="mypassword",
            REDIS_DB=2,
        )
        url = s.REDIS_URL
        assert url == "redis://:mypassword@redis.example.com:6380/2"

    def test_redis_url_without_password(self):
        """无密码的 REDIS_URL 构建正确"""
        from app.core.config import Settings

        s = Settings(
            REDIS_HOST="localhost",
            REDIS_PORT=6379,
            REDIS_PASSWORD="",
            REDIS_DB=0,
        )
        url = s.REDIS_URL
        assert url == "redis://localhost:6379/0"
        assert ":@" not in url


class TestGetSettings:
    """测试 get_settings() 单例行为"""

    def test_get_settings_returns_settings_instance(self):
        """get_settings() 返回 Settings 实例"""
        from app.core.config import Settings, get_settings

        s = get_settings()
        assert isinstance(s, Settings)

    def test_get_settings_returns_consistent_singleton(self):
        """多次调用 get_settings() 返回同一实例"""
        from app.core.config import get_settings

        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2


class TestIsProduction:
    """测试 is_production 属性"""

    def test_is_production_when_debug_false(self):
        """DEBUG=False 时 is_production 为 True"""
        from app.core.config import Settings

        s = Settings(DEBUG=False)
        assert s.is_production is True

    def test_is_production_when_debug_true(self):
        """DEBUG=True 时 is_production 为 False"""
        from app.core.config import Settings

        s = Settings(DEBUG=True)
        assert s.is_production is False


class TestRuntimeDir:
    """测试 runtime_dir 属性"""

    def test_runtime_dir_returns_valid_path(self, settings):
        """runtime_dir 返回有效路径字符串"""
        rd = settings.runtime_dir
        assert isinstance(rd, str)
        assert len(rd) > 0

    def test_runtime_dir_is_absolute(self, settings):
        """runtime_dir 返回绝对路径"""
        rd = settings.runtime_dir
        assert os.path.isabs(rd)

    def test_runtime_dir_ends_with_runtime(self, settings):
        """runtime_dir 以 runtime 结尾（默认值情况）"""
        rd = settings.runtime_dir
        assert rd.endswith("runtime")


class TestSecurityDefaults:
    """测试安全相关的默认值"""

    def test_jwt_secret_is_set(self, settings):
        """JWT_SECRET 应该已设置（非空）"""
        assert settings.JWT_SECRET
        assert len(settings.JWT_SECRET) > 0

    def test_csrf_secret_is_set(self, settings):
        """CSRF_SECRET 应该已设置（非空）"""
        assert settings.CSRF_SECRET
        assert len(settings.CSRF_SECRET) > 0


class TestLegacyEnvAliases:
    """测试旧版环境变量别名"""

    def test_api_port_maps_to_port(self):
        """API_PORT 环境变量映射到 PORT"""
        from app.core.config import Settings

        with env_vars({"API_PORT": "9000"}):
            # 清除已有 PORT 以便测试别名映射
            with env_vars({"PORT": "9000"}):
                s = Settings()
                assert s.PORT == 9000


class TestProductionSecurityChecks:
    """测试生产环境下的导入期安全检查。

    使用 subprocess 隔离执行，避免 sys.modules.pop + importlib.import_module
    污染主测试进程的 settings 单例（曾导致 test_pr2_core_security 状态漂移）。
    """

    def _run_config_import(self, env: dict):
        """在子进程中执行 `import app.core.config`，返回 (returncode, stdout, stderr)。"""
        import subprocess
        result = subprocess.run(
            [sys.executable, "-c", "import app.core.config"],
            env={**os.environ, **env},
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )
        return result.returncode, result.stdout, result.stderr

    def test_docker_production_warns_on_wildcard_allowed_hosts(self):
        """Docker 生产环境下 ALLOWED_HOSTS 含 '*' 时降级为警告（Nginx 反代已保证同源安全）。

        历史：465e9948 把 Docker 环境 '*' 从 RuntimeError 改为 warnings.warn，
        对齐"容器内 Nginx 反代已保证同源安全"的实际部署模型。
        子进程里 warnings 走 stderr，returncode=0 表示未 raise。
        """
        rc, stdout, stderr = self._run_config_import({
            "DEBUG": "false",
            "DOCKER_CONTAINER": "true",
            "ALLOWED_ORIGINS": '["https://example.com"]',
            "ALLOWED_HOSTS": '["*"]',
            "JWT_SECRET": "test-jwt-secret",
            "CSRF_SECRET": "test-csrf-secret",
        })
        assert rc == 0, f"Docker 生产环境不应 raise，但子进程退出码={rc}\nstderr:\n{stderr}"
        assert "ALLOWED_HOSTS" in stderr and "*" in stderr, (
            f"期望 stderr 含 ALLOWED_HOSTS 和 '*' 的警告，实际:\n{stderr}"
        )

    def test_non_docker_production_rejects_wildcard_allowed_hosts(self):
        """非 Docker 生产环境下 ALLOWED_HOSTS 含 '*' 必须抛 RuntimeError。

        Docker 环境降级为警告（见上一测试），裸机生产环境仍严格阻止。
        """
        rc, stdout, stderr = self._run_config_import({
            "DEBUG": "false",
            "DOCKER_CONTAINER": "",
            "ALLOWED_ORIGINS": '["https://example.com"]',
            "ALLOWED_HOSTS": '["*"]',
            "JWT_SECRET": "test-jwt-secret",
            "CSRF_SECRET": "test-csrf-secret",
        })
        assert rc != 0, f"非 Docker 生产环境应 raise RuntimeError，但子进程正常退出\nstderr:\n{stderr}"
        assert "ALLOWED_HOSTS" in stderr, (
            f"期望 stderr 含 ALLOWED_HOSTS 错误，实际:\n{stderr}"
        )
