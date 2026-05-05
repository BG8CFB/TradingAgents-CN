"""
用户数据模型单元测试
覆盖 User, UserCreate, UserUpdate, UserResponse, UserPreferences, PyObjectId 等
"""

import pytest
from datetime import datetime, timezone
from bson import ObjectId
from pydantic import ValidationError

from app.models.user import (
    User,
    UserCreate,
    UserUpdate,
    UserResponse,
    UserPreferences,
    FavoriteStock,
    UserLogin,
    UserSession,
    TokenResponse,
    PyObjectId,
    validate_object_id,
    serialize_object_id,
)


# ---------------------------------------------------------------------------
# PyObjectId 工具函数
# ---------------------------------------------------------------------------


class TestPyObjectIdValidation:
    """ObjectId 验证函数测试"""

    def test_validate_object_id_from_objectid(self):
        """传入 ObjectId 实例应直接返回"""
        oid = ObjectId()
        result = validate_object_id(oid)
        assert result == oid

    def test_validate_object_id_from_valid_str(self):
        """传入有效 ObjectId 字符串应转换成功"""
        oid_str = "507f1f77bcf86cd799439011"
        result = validate_object_id(oid_str)
        assert isinstance(result, ObjectId)
        assert str(result) == oid_str

    def test_validate_object_id_rejects_invalid_str(self):
        """传入无效字符串应抛出 ValueError"""
        with pytest.raises(ValueError, match="Invalid ObjectId"):
            validate_object_id("not_a_valid_id")

    def test_validate_object_id_rejects_non_string(self):
        """传入非字符串非 ObjectId 类型应抛出 ValueError"""
        with pytest.raises(ValueError, match="Invalid ObjectId"):
            validate_object_id(12345)

    def test_serialize_object_id_to_str(self):
        """ObjectId 序列化应为字符串"""
        oid = ObjectId("507f1f77bcf86cd799439011")
        result = serialize_object_id(oid)
        assert isinstance(result, str)
        assert result == "507f1f77bcf86cd799439011"


# ---------------------------------------------------------------------------
# UserPreferences
# ---------------------------------------------------------------------------


class TestUserPreferences:
    """用户偏好设置模型测试"""

    def test_default_values(self):
        """默认值应正确填充"""
        prefs = UserPreferences()
        assert prefs.default_market == "A股"
        assert prefs.default_depth == "3"
        assert prefs.default_analysts == []
        assert prefs.auto_refresh is True
        assert prefs.refresh_interval == 30
        assert prefs.ui_theme == "light"
        assert prefs.sidebar_width == 240
        assert prefs.language == "zh-CN"
        assert prefs.notifications_enabled is True
        assert prefs.email_notifications is False
        assert prefs.desktop_notifications is True
        assert prefs.analysis_complete_notification is True
        assert prefs.system_maintenance_notification is True

    def test_custom_values(self):
        """自定义值应正确设置"""
        prefs = UserPreferences(
            default_market="港股",
            default_depth="5",
            default_analysts=["analyst_a", "analyst_b"],
            auto_refresh=False,
            refresh_interval=60,
            ui_theme="dark",
            language="en-US",
        )
        assert prefs.default_market == "港股"
        assert prefs.default_depth == "5"
        assert len(prefs.default_analysts) == 2
        assert prefs.auto_refresh is False
        assert prefs.refresh_interval == 60
        assert prefs.ui_theme == "dark"
        assert prefs.language == "en-US"

    def test_serialization(self):
        """模型序列化应包含所有字段"""
        prefs = UserPreferences()
        data = prefs.model_dump()
        assert "default_market" in data
        assert "default_depth" in data
        assert "ui_theme" in data
        assert "language" in data
        assert isinstance(data["default_analysts"], list)


# ---------------------------------------------------------------------------
# FavoriteStock
# ---------------------------------------------------------------------------


class TestFavoriteStock:
    """自选股模型测试"""

    def test_create_with_required_fields(self):
        """必填字段创建应成功"""
        fav = FavoriteStock(stock_code="000001", stock_name="平安银行", market="A股")
        assert fav.stock_code == "000001"
        assert fav.stock_name == "平安银行"
        assert fav.market == "A股"
        assert fav.tags == []
        assert fav.notes == ""
        assert fav.alert_price_high is None
        assert fav.alert_price_low is None

    def test_create_with_all_fields(self):
        """所有字段创建应成功"""
        now = datetime.now(timezone.utc)
        fav = FavoriteStock(
            stock_code="600519",
            stock_name="贵州茅台",
            market="A股",
            added_at=now,
            tags=["白酒", "龙头"],
            notes="长线持有",
            alert_price_high=2000.0,
            alert_price_low=1500.0,
        )
        assert fav.stock_code == "600519"
        assert fav.tags == ["白酒", "龙头"]
        assert fav.notes == "长线持有"
        assert fav.alert_price_high == 2000.0
        assert fav.alert_price_low == 1500.0

    def test_missing_required_field_raises(self):
        """缺少必填字段应报错"""
        with pytest.raises(ValidationError):
            FavoriteStock(stock_code="000001")


# ---------------------------------------------------------------------------
# UserCreate
# ---------------------------------------------------------------------------


class TestUserCreate:
    """创建用户请求模型测试"""

    def test_valid_user_create(self):
        """合法输入应创建成功"""
        user = UserCreate(
            username="testuser",
            email="test@example.com",
            password="secure123",
        )
        assert user.username == "testuser"
        assert user.email == "test@example.com"
        assert user.password == "secure123"

    def test_username_too_short(self):
        """用户名太短应报错"""
        with pytest.raises(ValidationError):
            UserCreate(
                username="ab",
                email="test@example.com",
                password="secure123",
            )

    def test_username_too_long(self):
        """用户名超长应报错"""
        with pytest.raises(ValidationError):
            UserCreate(
                username="a" * 51,
                email="test@example.com",
                password="secure123",
            )

    def test_password_too_short(self):
        """密码太短应报错"""
        with pytest.raises(ValidationError):
            UserCreate(
                username="testuser",
                email="test@example.com",
                password="12345",
            )

    def test_password_too_long(self):
        """密码超长应报错"""
        with pytest.raises(ValidationError):
            UserCreate(
                username="testuser",
                email="test@example.com",
                password="x" * 101,
            )

    def test_invalid_email_no_at(self):
        """无 @ 的邮箱应报错"""
        with pytest.raises(ValidationError):
            UserCreate(
                username="testuser",
                email="invalid-email",
                password="secure123",
            )

    def test_invalid_email_no_domain(self):
        """无域名的邮箱应报错"""
        with pytest.raises(ValidationError):
            UserCreate(
                username="testuser",
                email="user@",
                password="secure123",
            )

    def test_invalid_email_no_tld(self):
        """无顶级域的邮箱应报错"""
        with pytest.raises(ValidationError):
            UserCreate(
                username="testuser",
                email="user@domain",
                password="secure123",
            )

    def test_missing_required_fields(self):
        """缺少必填字段应报错"""
        with pytest.raises(ValidationError):
            UserCreate()
        with pytest.raises(ValidationError):
            UserCreate(username="testuser")
        with pytest.raises(ValidationError):
            UserCreate(username="testuser", email="a@b.com")


# ---------------------------------------------------------------------------
# UserUpdate
# ---------------------------------------------------------------------------


class TestUserUpdate:
    """更新用户请求模型测试"""

    def test_all_fields_optional(self):
        """所有字段都是可选的"""
        update = UserUpdate()
        assert update.email is None
        assert update.preferences is None
        assert update.daily_quota is None
        assert update.concurrent_limit is None

    def test_partial_update(self):
        """部分更新应成功"""
        update = UserUpdate(email="new@example.com")
        assert update.email == "new@example.com"
        assert update.preferences is None

    def test_invalid_email(self):
        """无效邮箱应报错"""
        with pytest.raises(ValidationError):
            UserUpdate(email="not-an-email")

    def test_update_with_preferences(self):
        """包含偏好设置更新应成功"""
        prefs = UserPreferences(ui_theme="dark")
        update = UserUpdate(preferences=prefs, daily_quota=500)
        assert update.preferences.ui_theme == "dark"
        assert update.daily_quota == 500


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------


class TestUser:
    """用户模型测试"""

    def test_create_user_with_required_fields(self):
        """必填字段创建应成功"""
        user = User(
            username="testuser",
            email="test@example.com",
            hashed_password="hashed_value",
        )
        assert user.username == "testuser"
        assert user.email == "test@example.com"
        assert user.hashed_password == "hashed_value"
        assert user.is_active is True
        assert user.is_verified is False
        assert user.is_admin is False
        assert isinstance(user.preferences, UserPreferences)
        assert user.daily_quota == 1000
        assert user.concurrent_limit == 3
        assert user.total_analyses == 0
        assert user.successful_analyses == 0
        assert user.failed_analyses == 0
        assert user.favorite_stocks == []

    def test_user_has_timestamps(self):
        """用户应有创建和更新时间戳"""
        user = User(
            username="testuser",
            email="test@example.com",
            hashed_password="hashed",
        )
        assert user.created_at is not None
        assert user.updated_at is not None

    def test_user_with_all_fields(self):
        """完整字段创建应成功"""
        user = User(
            username="admin",
            email="admin@example.com",
            hashed_password="hashed",
            is_active=True,
            is_verified=True,
            is_admin=True,
            daily_quota=5000,
            concurrent_limit=10,
            total_analyses=100,
            successful_analyses=95,
            failed_analyses=5,
        )
        assert user.is_admin is True
        assert user.daily_quota == 5000
        assert user.total_analyses == 100

    def test_user_populate_by_name(self):
        """通过别名 _id 填充应成功"""
        oid = ObjectId()
        user = User(
            _id=oid,
            username="testuser",
            email="test@example.com",
            hashed_password="hashed",
        )
        assert user.id == oid

    def test_user_serialization(self):
        """模型序列化应包含所有字段"""
        user = User(
            username="testuser",
            email="test@example.com",
            hashed_password="hashed",
        )
        data = user.model_dump()
        assert "username" in data
        assert "email" in data
        assert "hashed_password" in data
        assert "preferences" in data

    def test_user_invalid_email(self):
        """无效邮箱应报错"""
        with pytest.raises(ValidationError):
            User(
                username="testuser",
                email="bad-email",
                hashed_password="hashed",
            )

    def test_user_invalid_username_too_short(self):
        """用户名太短应报错"""
        with pytest.raises(ValidationError):
            User(
                username="ab",
                email="a@b.com",
                hashed_password="hashed",
            )


# ---------------------------------------------------------------------------
# UserResponse
# ---------------------------------------------------------------------------


class TestUserResponse:
    """用户响应模型测试"""

    def test_create_user_response(self):
        """创建响应应成功"""
        now = datetime.now(timezone.utc)
        resp = UserResponse(
            id="507f1f77bcf86cd799439011",
            username="testuser",
            email="test@example.com",
            is_active=True,
            is_verified=False,
            created_at=now,
            last_login=None,
            preferences=UserPreferences(),
            daily_quota=1000,
            concurrent_limit=3,
            total_analyses=0,
            successful_analyses=0,
            failed_analyses=0,
        )
        assert resp.id == "507f1f77bcf86cd799439011"
        assert resp.username == "testuser"
        assert resp.is_active is True
        assert resp.last_login is None

    def test_datetime_serialization(self):
        """datetime 应序列化为 ISO 格式"""
        now = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        resp = UserResponse(
            id="abc123",
            username="testuser",
            email="test@example.com",
            is_active=True,
            is_verified=False,
            created_at=now,
            last_login=now,
            preferences=UserPreferences(),
            daily_quota=1000,
            concurrent_limit=3,
            total_analyses=0,
            successful_analyses=0,
            failed_analyses=0,
        )
        data = resp.model_dump()
        # field_serializer 将 datetime 转为 ISO 字符串
        assert isinstance(data["created_at"], str)
        assert "2024-01-15" in data["created_at"]

    def test_missing_required_field_raises(self):
        """缺少必填字段应报错"""
        with pytest.raises(ValidationError):
            UserResponse(id="abc123", username="testuser")


# ---------------------------------------------------------------------------
# UserLogin
# ---------------------------------------------------------------------------


class TestUserLogin:
    """用户登录请求模型测试"""

    def test_valid_login(self):
        """合法登录数据"""
        login = UserLogin(username="testuser", password="pass123")
        assert login.username == "testuser"
        assert login.password == "pass123"

    def test_missing_fields(self):
        """缺少字段应报错"""
        with pytest.raises(ValidationError):
            UserLogin()


# ---------------------------------------------------------------------------
# UserSession
# ---------------------------------------------------------------------------


class TestUserSession:
    """用户会话模型测试"""

    def test_create_session(self):
        """创建会话应成功"""
        now = datetime.now(timezone.utc)
        session = UserSession(
            session_id="sess_123",
            user_id="user_456",
            created_at=now,
            expires_at=now,
            last_activity=now,
        )
        assert session.session_id == "sess_123"
        assert session.ip_address is None
        assert session.user_agent is None

    def test_session_with_optional_fields(self):
        """带可选字段的会话"""
        now = datetime.now(timezone.utc)
        session = UserSession(
            session_id="sess_123",
            user_id="user_456",
            created_at=now,
            expires_at=now,
            last_activity=now,
            ip_address="127.0.0.1",
            user_agent="Mozilla/5.0",
        )
        assert session.ip_address == "127.0.0.1"
        assert session.user_agent == "Mozilla/5.0"


# ---------------------------------------------------------------------------
# TokenResponse
# ---------------------------------------------------------------------------


class TestTokenResponse:
    """Token 响应模型测试"""

    def test_create_token_response(self):
        """创建 Token 响应应成功"""
        now = datetime.now(timezone.utc)
        user_resp = UserResponse(
            id="abc",
            username="testuser",
            email="test@example.com",
            is_active=True,
            is_verified=False,
            created_at=now,
            last_login=None,
            preferences=UserPreferences(),
            daily_quota=1000,
            concurrent_limit=3,
            total_analyses=0,
            successful_analyses=0,
            failed_analyses=0,
        )
        token = TokenResponse(
            access_token="jwt_token_value",
            expires_in=3600,
            user=user_resp,
        )
        assert token.access_token == "jwt_token_value"
        assert token.token_type == "bearer"
        assert token.expires_in == 3600
        assert token.refresh_token is None
        assert isinstance(token.user, UserResponse)

    def test_token_with_refresh(self):
        """带 refresh_token 的响应"""
        now = datetime.now(timezone.utc)
        user_resp = UserResponse(
            id="abc",
            username="testuser",
            email="test@example.com",
            is_active=True,
            is_verified=False,
            created_at=now,
            last_login=None,
            preferences=UserPreferences(),
            daily_quota=1000,
            concurrent_limit=3,
            total_analyses=0,
            successful_analyses=0,
            failed_analyses=0,
        )
        token = TokenResponse(
            access_token="jwt_token",
            refresh_token="refresh_token_value",
            expires_in=3600,
            user=user_resp,
        )
        assert token.refresh_token == "refresh_token_value"
