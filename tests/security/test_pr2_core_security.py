"""
PR2 核心安全测试

覆盖 4 项修复：
- S2 SecretService 持久化（DB + 文件兜底 + os.environ 三层）
- S3 默认密钥生产模式拒绝启动
- S10 限流中间件 Redis 故障 fail-closed + 自愈协程
- S11 操作日志中间件不再二次 decode JWT
"""

import asyncio
import os
import tempfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# 工具：把 SimulatedMongoDB 同时注入到 database.mongo_db（与 mongo.client._motor_db）
# ---------------------------------------------------------------------------


async def _inject_mongo_db(sim_db):
    """同时 patch 两处 mongo_db，让 get_mongo_db() 可用。"""
    from app.core import database as db_mod

    original = db_mod.mongo_db
    db_mod.mongo_db = sim_db
    return original, db_mod


# ---------------------------------------------------------------------------
# S2 SecretService 持久化
# ---------------------------------------------------------------------------


class TestSecretServicePersistence:
    """S2：密钥三重持久化（DB + 文件兜底 + os.environ）。"""

    @pytest.mark.asyncio
    async def test_secrets_written_to_env_and_fallback(self, sim_db):
        """ensure_secrets 后 os.environ 应被设置；文件兜底应存在。"""
        from app.services import secret_service as ss
        from app.core import database as db_mod

        original_db = db_mod.mongo_db
        original_file = ss._FALLBACK_FILE
        try:
            db_mod.mongo_db = sim_db
            ss._FALLBACK_FILE = Path(tempfile.mkdtemp()) / ".secrets.json"

            for k in ("JWT_SECRET", "CSRF_SECRET"):
                os.environ.pop(k, None)

            result = await ss.SecretService.ensure_secrets()

            assert os.environ.get("JWT_SECRET") == result["jwt_secret"]
            assert os.environ.get("CSRF_SECRET") == result["csrf_secret"]

            assert ss._FALLBACK_FILE.exists()
            import json
            data = json.loads(ss._FALLBACK_FILE.read_text(encoding="utf-8"))
            assert data["jwt_secret"] == result["jwt_secret"]
            assert data["csrf_secret"] == result["csrf_secret"]
        finally:
            db_mod.mongo_db = original_db
            ss._FALLBACK_FILE = original_file

    @pytest.mark.asyncio
    async def test_secrets_reused_from_db(self, sim_db):
        """重复调用 ensure_secrets 应复用 DB 中已存在的密钥。"""
        from app.services.secret_service import SecretService
        from app.core import database as db_mod
        from app.services import secret_service as ss

        original_db = db_mod.mongo_db
        original_file = ss._FALLBACK_FILE
        try:
            db_mod.mongo_db = sim_db
            ss._FALLBACK_FILE = Path(tempfile.mkdtemp()) / ".secrets.json"
            # 清空 system_secrets
            for name in ("jwt_secret", "csrf_secret"):
                await sim_db["system_secrets"].delete_one({"name": name})

            first = await SecretService.ensure_secrets()
            # 第二次不再生成新值
            second = await SecretService.ensure_secrets()

            assert first["jwt_secret"] == second["jwt_secret"]
            assert first["csrf_secret"] == second["csrf_secret"]
        finally:
            db_mod.mongo_db = original_db
            ss._FALLBACK_FILE = original_file

    @pytest.mark.asyncio
    async def test_secrets_recovered_from_fallback_when_db_empty(self, sim_db):
        """DB 中无密钥但文件兜底存在时，应从文件兜底恢复。"""
        from app.services import secret_service as ss
        from app.core import database as db_mod

        original_db = db_mod.mongo_db
        original_file = ss._FALLBACK_FILE
        try:
            db_mod.mongo_db = sim_db
            ss._FALLBACK_FILE = Path(tempfile.mkdtemp()) / ".secrets.json"
            # 清空 system_secrets
            for name in ("jwt_secret", "csrf_secret"):
                await sim_db["system_secrets"].delete_one({"name": name})
            ss._save_fallback_file({
                "jwt_secret": "from_file_jwt",
                "csrf_secret": "from_file_csrf",
            })

            result = await ss.SecretService.ensure_secrets()

            assert result["jwt_secret"] == "from_file_jwt"
            assert result["csrf_secret"] == "from_file_csrf"
        finally:
            db_mod.mongo_db = original_db
            ss._FALLBACK_FILE = original_file

    def test_persist_to_env_loads_from_fallback(self, tmp_path):
        """persist_to_env 应从兜底文件加载到 os.environ。"""
        from app.services import secret_service as ss

        original_file = ss._FALLBACK_FILE
        original_jwt = os.environ.get("JWT_SECRET")
        original_csrf = os.environ.get("CSRF_SECRET")
        try:
            ss._FALLBACK_FILE = tmp_path / ".secrets.json"
            ss._save_fallback_file({
                "jwt_secret": "fallback_persist_jwt",
                "csrf_secret": "fallback_persist_csrf",
            })
            os.environ.pop("JWT_SECRET", None)
            os.environ.pop("CSRF_SECRET", None)

            ss.SecretService.persist_to_env()

            assert os.environ["JWT_SECRET"] == "fallback_persist_jwt"
            assert os.environ["CSRF_SECRET"] == "fallback_persist_csrf"
        finally:
            ss._FALLBACK_FILE = original_file
            for k, v in (("JWT_SECRET", original_jwt), ("CSRF_SECRET", original_csrf)):
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    @pytest.mark.asyncio
    async def test_rotate_secret_updates_all_three_layers(self, sim_db):
        """rotate_secret 应同时更新 DB / 文件兜底 / os.environ。"""
        from app.services import secret_service as ss
        from app.core import database as db_mod

        original_db = db_mod.mongo_db
        original_file = ss._FALLBACK_FILE
        try:
            db_mod.mongo_db = sim_db
            ss._FALLBACK_FILE = Path(tempfile.mkdtemp()) / ".secrets.json"
            for name in ("jwt_secret", "csrf_secret"):
                await sim_db["system_secrets"].delete_one({"name": name})

            original = await ss.SecretService.ensure_secrets()
            new_value = await ss.SecretService.rotate_secret("jwt_secret")

            assert new_value != original["jwt_secret"]
            assert os.environ["JWT_SECRET"] == new_value

            import json
            data = json.loads(ss._FALLBACK_FILE.read_text(encoding="utf-8"))
            assert data["jwt_secret"] == new_value
            assert "csrf_secret" in data
        finally:
            db_mod.mongo_db = original_db
            ss._FALLBACK_FILE = original_file


# ---------------------------------------------------------------------------
# S3 默认密钥拒绝启动
# ---------------------------------------------------------------------------


class TestDefaultSecretRejection:
    """S3：生产模式 + 默认占位符 → 拒绝启动。"""

    def _run_check(self, debug: bool, env_values: dict):
        """构造 validator 并执行 _check_security_configs。"""
        from app.core import startup_validator as sv
        from app.core import config as cfg

        original_env = {k: os.environ.get(k) for k in env_values}
        original_debug = cfg.settings.DEBUG

        for k, v in env_values.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        cfg.settings.DEBUG = debug

        try:
            validator = sv.StartupValidator()
            validator._check_security_configs()
            return validator
        finally:
            for k, v in original_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            cfg.settings.DEBUG = original_debug

    @pytest.mark.asyncio
    async def test_production_rejects_default_jwt_secret(self, inject_sim_db):
        validator = self._run_check(
            debug=False,
            env_values={
                "JWT_SECRET": "docker-jwt-secret-key-change-in-production-abc",
                "CSRF_SECRET": "strong-csrf-secret-not-default-xyz",
            },
        )
        assert validator.result.invalid_configs

    @pytest.mark.asyncio
    async def test_production_rejects_default_csrf_secret(self, inject_sim_db):
        validator = self._run_check(
            debug=False,
            env_values={
                "JWT_SECRET": "strong-jwt-secret-not-default-xyz",
                "CSRF_SECRET": "docker-csrf-secret-key-change-in-production-abc",
            },
        )
        assert validator.result.invalid_configs

    @pytest.mark.asyncio
    async def test_production_rejects_change_me_prefix(self, inject_sim_db):
        validator = self._run_check(
            debug=False,
            env_values={
                "JWT_SECRET": "change-me-please-anything",
                "CSRF_SECRET": "strong-csrf-secret-not-default",
            },
        )
        assert validator.result.invalid_configs

    @pytest.mark.asyncio
    async def test_dev_mode_allows_default_secret(self, inject_sim_db):
        validator = self._run_check(
            debug=True,
            env_values={
                "JWT_SECRET": "docker-jwt-secret-key-change-in-production-abc",
                "CSRF_SECRET": "strong-csrf-secret-not-default",
            },
        )
        assert not validator.result.invalid_configs
        joined = " ".join(validator.result.warnings)
        assert "JWT_SECRET" in joined and "默认值" in joined

    @pytest.mark.asyncio
    async def test_production_allows_strong_secret(self, inject_sim_db):
        validator = self._run_check(
            debug=False,
            env_values={
                "JWT_SECRET": "9sfK3jsdF7sL2k9sdKf3LKsd9f8KJ234LKJDF9skdfL",
                "CSRF_SECRET": "9sdfKJ3lksd9f8KJ2L4KLKJDF9skdfL9sfK3js",
            },
        )
        assert not validator.result.invalid_configs


class TestCheckDefaultSecretsMain:
    """main._check_default_secrets 函数测试。"""

    def test_production_raises_on_default_secret(self):
        import logging
        from app.core import config as cfg
        from app.main import _check_default_secrets

        original_debug = cfg.settings.DEBUG
        original_jwt = os.environ.get("JWT_SECRET")
        original_csrf = os.environ.get("CSRF_SECRET")
        cfg.settings.DEBUG = False
        os.environ["JWT_SECRET"] = "docker-jwt-secret-key-change-in-production-abc"
        os.environ["CSRF_SECRET"] = "strong-csrf-xyz"

        try:
            with pytest.raises(RuntimeError):
                _check_default_secrets(logging.getLogger("test"))
        finally:
            cfg.settings.DEBUG = original_debug
            for k, v in (("JWT_SECRET", original_jwt), ("CSRF_SECRET", original_csrf)):
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_dev_mode_warns_but_does_not_raise(self):
        import logging
        from app.core import config as cfg
        from app.main import _check_default_secrets

        original_debug = cfg.settings.DEBUG
        original_jwt = os.environ.get("JWT_SECRET")
        original_csrf = os.environ.get("CSRF_SECRET")
        cfg.settings.DEBUG = True
        os.environ["JWT_SECRET"] = "docker-jwt-secret-key-change-in-production-abc"
        os.environ["CSRF_SECRET"] = "strong-csrf-xyz"

        try:
            _check_default_secrets(logging.getLogger("test"))
        finally:
            cfg.settings.DEBUG = original_debug
            for k, v in (("JWT_SECRET", original_jwt), ("CSRF_SECRET", original_csrf)):
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


# ---------------------------------------------------------------------------
# S10 限流中间件 Redis 故障自愈
# ---------------------------------------------------------------------------


class TestRateLimitFailClosed:
    """S10：Redis 故障时敏感路径 fail-closed。"""

    def test_is_sensitive_path_login(self):
        from app.middleware.rate_limit import _is_sensitive_path
        assert _is_sensitive_path("/api/auth/login")
        assert _is_sensitive_path("/api/auth/login/")
        assert _is_sensitive_path("/api/auth/login/sub")

    def test_is_sensitive_path_register(self):
        from app.middleware.rate_limit import _is_sensitive_path
        assert _is_sensitive_path("/api/auth/register")
        assert _is_sensitive_path("/api/auth/refresh")

    def test_is_not_sensitive_path_analysis(self):
        from app.middleware.rate_limit import _is_sensitive_path
        assert not _is_sensitive_path("/api/analysis/single")
        assert not _is_sensitive_path("/api/cn/data/dashboard")

    def test_redis_unavailable_response_returns_503(self):
        from app.middleware.rate_limit import _redis_unavailable_response
        resp = _redis_unavailable_response("/api/auth/login")
        assert resp.status_code == 503
        body = resp.body
        import json
        data = json.loads(body)
        assert data["error"]["code"] == "RATE_LIMIT_UNAVAILABLE"


# ---------------------------------------------------------------------------
# S11 操作日志中间件
# ---------------------------------------------------------------------------


class TestOperationLogUserState:
    """S11：操作日志中间件走 JWT 解析作为唯一路径（state 注入已移除）。"""

    def _make_request(self, auth_header=""):
        """构造一个最小可用的 Starlette Request scope。"""
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/test",
            "headers": [(b"authorization", auth_header.encode())] if auth_header else [],
            "query_string": b"",
            "client": ("127.0.0.1", 8000),
            "app": None,
        }
        return Request(scope)

    @pytest.mark.asyncio
    async def test_get_user_info_no_auth_returns_none(self):
        """无 Authorization header 时返回 None。"""
        from app.middleware.operation_log_middleware import OperationLogMiddleware

        mw = OperationLogMiddleware.__new__(OperationLogMiddleware)
        request = self._make_request()

        info = await mw._get_user_info(request)
        assert info is None

    @pytest.mark.asyncio
    async def test_parse_jwt_user_no_token(self):
        """_parse_jwt_user 是 JWT 解析的主路径（无 token 返回 None）。"""
        from app.middleware.operation_log_middleware import OperationLogMiddleware

        mw = OperationLogMiddleware.__new__(OperationLogMiddleware)
        request = self._make_request()
        info = await mw._parse_jwt_user(request)
        assert info is None
