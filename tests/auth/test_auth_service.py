"""
认证服务的单元测试。

测试 app/services/auth_service.py 中的 AuthService 类：
- create_access_token（默认过期、自定义过期分钟、自定义过期秒数）
- verify_token（有效令牌、过期令牌、无效令牌、畸形令牌）
- TokenData 数据提取
"""

import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.config import settings
from app.services.auth_service import AuthService, TokenData


# ---------------------------------------------------------------------------
# create_access_token
# ---------------------------------------------------------------------------


class TestCreateAccessToken:
    """AuthService.create_access_token 测试组。"""

    def test_creates_valid_jwt_token(self):
        """create_access_token 应返回有效的 JWT 字符串。"""
        token = AuthService.create_access_token(sub="user123")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_contains_correct_subject(self):
        """令牌 payload 中应包含正确的 sub 字段。"""
        subject = "test_user_abc"
        token = AuthService.create_access_token(sub=subject)
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        assert payload["sub"] == subject

    def test_token_contains_exp_field(self):
        """令牌 payload 中应包含 exp 字段，且为整数。"""
        token = AuthService.create_access_token(sub="user1")
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        assert "exp" in payload
        assert isinstance(payload["exp"], (int, float))

    def test_default_expiry_is_near_configured_minutes(self):
        """不指定过期时间时，过期时间应接近 settings.ACCESS_TOKEN_EXPIRE_MINUTES。"""
        before = datetime.now(timezone.utc).replace(microsecond=0)
        token = AuthService.create_access_token(sub="user1")
        after = datetime.now(timezone.utc)

        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)

        expected_min = before + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        expected_max = after + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        assert expected_min <= exp <= expected_max

    def test_custom_expiry_minutes(self):
        """使用自定义 expires_minutes 参数。"""
        custom_minutes = 5
        before = datetime.now(timezone.utc).replace(microsecond=0)
        token = AuthService.create_access_token(sub="user1", expires_minutes=custom_minutes)
        after = datetime.now(timezone.utc)

        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)

        expected_min = before + timedelta(minutes=custom_minutes)
        expected_max = after + timedelta(minutes=custom_minutes)
        assert expected_min <= exp <= expected_max

    def test_custom_expiry_delta_seconds(self):
        """使用 expires_delta（秒）参数。"""
        custom_seconds = 30
        before = datetime.now(timezone.utc).replace(microsecond=0)
        token = AuthService.create_access_token(sub="user1", expires_delta=custom_seconds)
        after = datetime.now(timezone.utc)

        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)

        expected_min = before + timedelta(seconds=custom_seconds)
        expected_max = after + timedelta(seconds=custom_seconds)
        assert expected_min <= exp <= expected_max

    def test_delta_seconds_takes_precedence_over_minutes(self):
        """当同时提供 expires_delta 和 expires_minutes 时，expires_delta 应优先生效。"""
        token = AuthService.create_access_token(
            sub="user1", expires_minutes=60, expires_delta=10
        )
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)

        # 过期时间应接近 10 秒后，而不是 60 分钟后
        now = datetime.now(timezone.utc)
        diff = (exp - now).total_seconds()
        # 允许 ±5 秒误差
        assert 5 < diff < 20, f"Expected ~10s expiry, got {diff}s"

    def test_different_subjects_produce_different_tokens(self):
        """不同 sub 应产生不同令牌。"""
        token1 = AuthService.create_access_token(sub="user_a")
        token2 = AuthService.create_access_token(sub="user_b")
        assert token1 != token2

    def test_same_subject_at_different_times(self):
        """相同 sub 在不同时间产生的令牌不同（exp 不同）。"""
        token1 = AuthService.create_access_token(sub="same_user")
        time.sleep(1)
        token2 = AuthService.create_access_token(sub="same_user")
        assert token1 != token2


# ---------------------------------------------------------------------------
# verify_token
# ---------------------------------------------------------------------------


class TestVerifyToken:
    """AuthService.verify_token 测试组。"""

    def test_valid_token_returns_token_data(self):
        """有效令牌应返回 TokenData 对象。"""
        token = AuthService.create_access_token(sub="user123")
        result = AuthService.verify_token(token)
        assert result is not None
        assert isinstance(result, TokenData)

    def test_valid_token_extracts_subject(self):
        """有效令牌应正确提取 sub。"""
        subject = "test_subject"
        token = AuthService.create_access_token(sub=subject)
        result = AuthService.verify_token(token)
        assert result is not None
        assert result.sub == subject

    def test_valid_token_extracts_expiry(self):
        """有效令牌应正确提取 exp。"""
        token = AuthService.create_access_token(sub="user1", expires_minutes=10)
        result = AuthService.verify_token(token)
        assert result is not None
        assert result.exp > 0

    def test_expired_token_returns_none(self):
        """过期令牌应返回 None。"""
        # 创建一个已过期的令牌（-1 秒前过期）
        token = AuthService.create_access_token(sub="user1", expires_delta=-1)
        result = AuthService.verify_token(token)
        assert result is None

    def test_invalid_token_returns_none(self):
        """使用错误密钥签名的令牌应返回 None。"""
        payload = {"sub": "user1", "exp": datetime.now(timezone.utc) + timedelta(hours=1)}
        fake_token = jwt.encode(payload, "wrong_secret_key", algorithm="HS256")
        result = AuthService.verify_token(fake_token)
        assert result is None

    def test_malformed_token_returns_none(self):
        """畸形令牌应返回 None。"""
        result = AuthService.verify_token("this.is.not.a.valid.token")
        assert result is None

    def test_empty_string_returns_none(self):
        """空字符串令牌应返回 None。"""
        result = AuthService.verify_token("")
        assert result is None

    def test_random_string_returns_none(self):
        """随机字符串应返回 None。"""
        result = AuthService.verify_token("random_gibberish_string")
        assert result is None

    def test_none_token_returns_none(self):
        """None 输入应返回 None（防御性）。"""
        result = AuthService.verify_token(None)  # type: ignore[arg-type]
        assert result is None

    def test_token_with_wrong_algorithm_returns_none(self):
        """使用错误算法签名的令牌应返回 None。"""
        # 用 HS384 签名
        payload = {"sub": "user1", "exp": datetime.now(timezone.utc) + timedelta(hours=1)}
        wrong_algo_token = jwt.encode(payload, settings.JWT_SECRET, algorithm="HS384")
        result = AuthService.verify_token(wrong_algo_token)
        assert result is None

    def test_roundtrip_create_and_verify(self):
        """创建令牌后立即验证应成功。"""
        subject = "roundtrip_user"
        token = AuthService.create_access_token(sub=subject, expires_minutes=30)
        result = AuthService.verify_token(token)
        assert result is not None
        assert result.sub == subject
        # exp 应在未来
        assert result.exp > int(datetime.now(timezone.utc).timestamp())


# ---------------------------------------------------------------------------
# TokenData
# ---------------------------------------------------------------------------


class TestTokenData:
    """TokenData 模型测试组。"""

    def test_create_token_data(self):
        """应能正常创建 TokenData。"""
        td = TokenData(sub="user1", exp=1700000000)
        assert td.sub == "user1"
        assert td.exp == 1700000000

    def test_token_data_is_pydantic_model(self):
        """TokenData 应为 Pydantic BaseModel 实例。"""
        from pydantic import BaseModel

        td = TokenData(sub="user1", exp=100)
        assert isinstance(td, BaseModel)
