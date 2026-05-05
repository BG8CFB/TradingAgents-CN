"""
用户服务的单元测试。

测试 app/services/user_service.py 中的 UserService 类。
所有 MongoDB 操作通过 AsyncMock 模拟，确保测试自包含且无外部依赖。
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId

import pytest

from app.models.user import User, UserCreate, UserUpdate, UserResponse
from app.services.user_service import UserService
from app.utils.passwords import hash_password


# ---------------------------------------------------------------------------
# 测试辅助
# ---------------------------------------------------------------------------


def _make_user_doc(
    username="testuser",
    email="test@example.com",
    is_active=True,
    is_admin=False,
    is_verified=False,
    password="password123",
):
    """构造一个模拟的用户文档（对应 MongoDB 中的记录）。"""
    return {
        "_id": ObjectId(),
        "username": username,
        "email": email,
        "hashed_password": hash_password(password),
        "is_active": is_active,
        "is_verified": is_verified,
        "is_admin": is_admin,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "last_login": None,
        "preferences": {
            "default_market": "A股",
            "default_depth": "3",
            "default_analysts": [],
            "auto_refresh": True,
            "refresh_interval": 30,
            "ui_theme": "light",
            "sidebar_width": 240,
            "language": "zh-CN",
            "notifications_enabled": True,
            "email_notifications": False,
            "desktop_notifications": True,
            "analysis_complete_notification": True,
            "system_maintenance_notification": True,
        },
        "daily_quota": 1000,
        "concurrent_limit": 3,
        "total_analyses": 0,
        "successful_analyses": 0,
        "failed_analyses": 0,
        "favorite_stocks": [],
    }


def _mock_update_result(modified_count=1, matched_count=1):
    """构造模拟的 MongoDB update_one 结果。"""
    result = MagicMock()
    result.modified_count = modified_count
    result.matched_count = matched_count
    result.inserted_id = ObjectId()
    return result


def _mock_insert_result():
    """构造模拟的 MongoDB insert_one 结果。"""
    result = MagicMock()
    result.inserted_id = ObjectId()
    return result


def _setup_db_mock():
    """创建一个带 users 集合的 mock 数据库。"""
    db = AsyncMock()
    db.users = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# hash_password / verify_password（静态方法，不依赖数据库）
# ---------------------------------------------------------------------------


class TestHashAndPasswordVerification:
    """UserService 静态密码方法测试组。"""

    def test_hash_password_creates_bcrypt_hash(self):
        """hash_password 应产生 bcrypt 哈希。"""
        result = UserService.hash_password("mypassword")
        assert isinstance(result, str)
        assert result.startswith(("$2a$", "$2b$", "$2y$"))

    def test_verify_password_accepts_correct_password(self):
        """verify_password 应接受正确密码。"""
        hashed = UserService.hash_password("correct")
        assert UserService.verify_password("correct", hashed) is True

    def test_verify_password_rejects_wrong_password(self):
        """verify_password 应拒绝错误密码。"""
        hashed = UserService.hash_password("correct")
        assert UserService.verify_password("wrong", hashed) is False


# ---------------------------------------------------------------------------
# create_user
# ---------------------------------------------------------------------------


class TestCreateUser:
    """UserService.create_user 测试组。"""

    @pytest.mark.asyncio
    async def test_creates_user_successfully(self):
        """正常创建用户应返回 User 对象。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        db.users.find_one = AsyncMock(side_effect=[None, None])  # 用户名不重复、邮箱不重复
        db.users.insert_one = AsyncMock(return_value=_mock_insert_result())

        user_data = UserCreate(
            username="newuser", email="new@example.com", password="password123"
        )
        user = await svc.create_user(user_data)

        assert user is not None
        assert isinstance(user, User)
        assert user.username == "newuser"
        assert user.email == "new@example.com"
        assert user.is_active is True
        assert user.is_admin is False

    @pytest.mark.asyncio
    async def test_returns_none_for_duplicate_username(self):
        """用户名已存在时返回 None。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        existing_doc = _make_user_doc(username="existing_user")
        db.users.find_one = AsyncMock(return_value=existing_doc)

        user_data = UserCreate(
            username="existing_user", email="other@example.com", password="pass123"
        )
        result = await svc.create_user(user_data)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_duplicate_email(self):
        """邮箱已存在时返回 None。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        # 第一次 find_one（用户名）返回 None，第二次（邮箱）返回已有记录
        existing_doc = _make_user_doc(email="dup@example.com")
        db.users.find_one = AsyncMock(side_effect=[None, existing_doc])

        user_data = UserCreate(
            username="newname", email="dup@example.com", password="pass123"
        )
        result = await svc.create_user(user_data)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_db_not_set(self):
        """数据库未设置时返回 None。"""
        svc = UserService()
        # 不调用 set_database

        user_data = UserCreate(
            username="user1", email="a@b.com", password="pass123"
        )
        result = await svc.create_user(user_data)
        assert result is None

    @pytest.mark.asyncio
    async def test_inserted_document_has_correct_fields(self):
        """插入的用户文档应包含所有必需字段。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        db.users.find_one = AsyncMock(side_effect=[None, None])
        db.users.insert_one = AsyncMock(return_value=_mock_insert_result())

        user_data = UserCreate(
            username="fieldcheck", email="fields@example.com", password="pass123"
        )
        await svc.create_user(user_data)

        call_args = db.users.insert_one.call_args[0][0]
        assert call_args["username"] == "fieldcheck"
        assert call_args["email"] == "fields@example.com"
        assert "hashed_password" in call_args
        assert call_args["is_active"] is True
        assert call_args["is_verified"] is False
        assert call_args["is_admin"] is False
        assert "preferences" in call_args
        assert call_args["daily_quota"] == 1000
        assert call_args["concurrent_limit"] == 3


# ---------------------------------------------------------------------------
# authenticate_user
# ---------------------------------------------------------------------------


class TestAuthenticateUser:
    """UserService.authenticate_user 测试组。"""

    @pytest.mark.asyncio
    async def test_returns_user_for_correct_credentials(self):
        """正确凭据应返回 User 对象。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        password = "correct_pass"
        doc = _make_user_doc(username="authuser", password=password)
        db.users.find_one = AsyncMock(return_value=doc)
        db.users.update_one = AsyncMock(return_value=_mock_update_result())

        user = await svc.authenticate_user("authuser", password)
        assert user is not None
        assert isinstance(user, User)
        assert user.username == "authuser"

    @pytest.mark.asyncio
    async def test_returns_none_for_wrong_password(self):
        """错误密码应返回 None。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        doc = _make_user_doc(username="authuser", password="right_pass")
        db.users.find_one = AsyncMock(return_value=doc)

        result = await svc.authenticate_user("authuser", "wrong_pass")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_nonexistent_user(self):
        """不存在的用户应返回 None。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        db.users.find_one = AsyncMock(return_value=None)

        result = await svc.authenticate_user("ghost", "any_pass")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_inactive_user(self):
        """被禁用的用户应返回 None。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        doc = _make_user_doc(username="inactive_user", password="pass", is_active=False)
        db.users.find_one = AsyncMock(return_value=doc)

        result = await svc.authenticate_user("inactive_user", "pass")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_db_not_set(self):
        """数据库未设置时返回 None。"""
        svc = UserService()
        result = await svc.authenticate_user("user", "pass")
        assert result is None

    @pytest.mark.asyncio
    async def test_updates_last_login_on_success(self):
        """认证成功时应更新 last_login。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        doc = _make_user_doc(username="loginuser", password="pass")
        db.users.find_one = AsyncMock(return_value=doc)
        db.users.update_one = AsyncMock(return_value=_mock_update_result())

        await svc.authenticate_user("loginuser", "pass")
        db.users.update_one.assert_called_once()

        update_call = db.users.update_one.call_args
        assert "$set" in update_call[0][1]
        assert "last_login" in update_call[0][1]["$set"]

    @pytest.mark.asyncio
    async def test_rehashes_password_if_needed(self):
        """如果哈希需要升级（SHA256），认证成功后应自动重哈希。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        # 使用 SHA256 哈希（需要重哈希）
        sha_password = "old_password"
        doc = _make_user_doc(username="legacy_user")
        from app.utils.passwords import legacy_sha256_hash
        doc["hashed_password"] = legacy_sha256_hash(sha_password)

        db.users.find_one = AsyncMock(return_value=doc)
        db.users.update_one = AsyncMock(return_value=_mock_update_result())

        user = await svc.authenticate_user("legacy_user", sha_password)
        assert user is not None

        # 验证 update_one 被调用，且更新了 hashed_password
        update_call = db.users.update_one.call_args
        set_data = update_call[0][1]["$set"]
        assert "hashed_password" in set_data


# ---------------------------------------------------------------------------
# get_user_by_username
# ---------------------------------------------------------------------------


class TestGetUserByUsername:
    """UserService.get_user_by_username 测试组。"""

    @pytest.mark.asyncio
    async def test_returns_user_when_found(self):
        """用户存在时应返回 User 对象。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        doc = _make_user_doc(username="findme")
        db.users.find_one = AsyncMock(return_value=doc)

        user = await svc.get_user_by_username("findme")
        assert user is not None
        assert user.username == "findme"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        """用户不存在时应返回 None。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        db.users.find_one = AsyncMock(return_value=None)

        result = await svc.get_user_by_username("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_db_not_set(self):
        """数据库未设置时返回 None。"""
        svc = UserService()
        result = await svc.get_user_by_username("anyone")
        assert result is None


# ---------------------------------------------------------------------------
# update_user
# ---------------------------------------------------------------------------


class TestUpdateUser:
    """UserService.update_user 测试组。"""

    @pytest.mark.asyncio
    async def test_updates_email_successfully(self):
        """应成功更新用户邮箱。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        updated_doc = _make_user_doc(username="upuser", email="new@example.com")
        db.users.find_one = AsyncMock(side_effect=[None, updated_doc])  # 邮箱不重复 + get_user_by_username
        db.users.update_one = AsyncMock(return_value=_mock_update_result(modified_count=1))

        user_data = UserUpdate(email="new@example.com")
        result = await svc.update_user("upuser", user_data)
        assert result is not None
        assert result.email == "new@example.com"

    @pytest.mark.asyncio
    async def test_returns_none_for_duplicate_email(self):
        """更新邮箱为已存在的邮箱时返回 None。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        existing_doc = _make_user_doc(username="other", email="taken@example.com")
        db.users.find_one = AsyncMock(return_value=existing_doc)

        user_data = UserUpdate(email="taken@example.com")
        result = await svc.update_user("upuser", user_data)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_modification(self):
        """没有实际修改时返回 None。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        db.users.update_one = AsyncMock(return_value=_mock_update_result(modified_count=0))

        user_data = UserUpdate(email="same@example.com")
        # 先让邮箱检查通过（find_one 返回 None）
        db.users.find_one = AsyncMock(return_value=None)
        result = await svc.update_user("upuser", user_data)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_db_not_set(self):
        """数据库未设置时返回 None。"""
        svc = UserService()
        result = await svc.update_user("user", UserUpdate(email="a@b.com"))
        assert result is None


# ---------------------------------------------------------------------------
# change_password
# ---------------------------------------------------------------------------


class TestChangePassword:
    """UserService.change_password 测试组。"""

    @pytest.mark.asyncio
    async def test_succeeds_with_correct_old_password(self):
        """旧密码正确时应成功修改密码。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        old_password = "old_pass123"
        doc = _make_user_doc(username="pwuser", password=old_password)

        # authenticate_user 会调用 find_one 和 update_one
        db.users.find_one = AsyncMock(return_value=doc)
        db.users.update_one = AsyncMock(return_value=_mock_update_result(modified_count=1))

        result = await svc.change_password("pwuser", old_password, "new_pass456")
        assert result is True

    @pytest.mark.asyncio
    async def test_fails_with_wrong_old_password(self):
        """旧密码错误时应失败。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        doc = _make_user_doc(username="pwuser", password="real_pass")
        db.users.find_one = AsyncMock(return_value=doc)

        result = await svc.change_password("pwuser", "wrong_pass", "new_pass")
        assert result is False


# ---------------------------------------------------------------------------
# reset_password
# ---------------------------------------------------------------------------


class TestResetPassword:
    """UserService.reset_password 测试组。"""

    @pytest.mark.asyncio
    async def test_resets_password_successfully(self):
        """应成功重置密码。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        db.users.update_one = AsyncMock(return_value=_mock_update_result(modified_count=1))

        result = await svc.reset_password("someuser", "new_reset_pass")
        assert result is True

        # 验证 update_one 被调用
        update_call = db.users.update_one.call_args
        assert update_call[0][0] == {"username": "someuser"}
        assert "hashed_password" in update_call[0][1]["$set"]

    @pytest.mark.asyncio
    async def test_returns_false_when_user_not_found(self):
        """用户不存在时应返回 False。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        db.users.update_one = AsyncMock(return_value=_mock_update_result(modified_count=0))

        result = await svc.reset_password("ghost", "new_pass")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_db_not_set(self):
        """数据库未设置时返回 False。"""
        svc = UserService()
        result = await svc.reset_password("user", "pass")
        assert result is False


# ---------------------------------------------------------------------------
# create_admin_user
# ---------------------------------------------------------------------------


class TestCreateAdminUser:
    """UserService.create_admin_user 测试组。"""

    @pytest.mark.asyncio
    async def test_creates_admin_user(self):
        """应成功创建管理员用户。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        db.users.find_one = AsyncMock(return_value=None)  # 不存在
        db.users.insert_one = AsyncMock(return_value=_mock_insert_result())

        admin = await svc.create_admin_user(
            username="admin", password="admin_pass", email="admin@example.com"
        )
        assert admin is not None
        assert isinstance(admin, User)
        assert admin.username == "admin"
        assert admin.is_admin is True
        assert admin.is_verified is True

    @pytest.mark.asyncio
    async def test_returns_existing_admin_if_already_exists(self):
        """管理员已存在时应返回现有用户。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        existing_doc = _make_user_doc(username="admin", is_admin=True)
        db.users.find_one = AsyncMock(return_value=existing_doc)

        admin = await svc.create_admin_user(
            username="admin", password="admin_pass"
        )
        assert admin is not None
        assert admin.username == "admin"

        # 不应调用 insert_one
        db.users.insert_one.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_none_when_no_password(self):
        """未提供密码时应返回 None。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        result = await svc.create_admin_user(username="admin", password=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_empty_password(self):
        """空密码应返回 None。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        result = await svc.create_admin_user(username="admin", password="")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_db_not_set(self):
        """数据库未设置时返回 None。"""
        svc = UserService()
        result = await svc.create_admin_user(password="pass")
        assert result is None


# ---------------------------------------------------------------------------
# list_users
# ---------------------------------------------------------------------------


class TestListUsers:
    """UserService.list_users 测试组。"""

    @pytest.mark.asyncio
    async def test_returns_list_of_user_response(self):
        """应返回 UserResponse 列表。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        doc1 = _make_user_doc(username="user1")
        doc2 = _make_user_doc(username="user2", email="user2@example.com")

        # 模拟 async for cursor
        async def mock_cursor_iter():
            yield doc1
            yield doc2

        mock_cursor = MagicMock()
        mock_cursor.skip = MagicMock(return_value=mock_cursor)
        mock_cursor.limit = MagicMock(return_value=mock_cursor)
        mock_cursor.__aiter__ = MagicMock(return_value=mock_cursor_iter())
        db.users.find = MagicMock(return_value=mock_cursor)

        result = await svc.list_users()
        assert len(result) == 2
        assert all(isinstance(u, UserResponse) for u in result)
        assert result[0].username == "user1"
        assert result[1].username == "user2"

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_users(self):
        """没有用户时应返回空列表。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        async def mock_empty_cursor():
            return
            yield  # 使其成为 async generator

        mock_cursor = MagicMock()
        mock_cursor.skip = MagicMock(return_value=mock_cursor)
        mock_cursor.limit = MagicMock(return_value=mock_cursor)
        mock_cursor.__aiter__ = MagicMock(return_value=mock_empty_cursor())
        db.users.find = MagicMock(return_value=mock_cursor)

        result = await svc.list_users()
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_db_not_set(self):
        """数据库未设置时返回空列表。"""
        svc = UserService()
        result = await svc.list_users()
        assert result == []

    @pytest.mark.asyncio
    async def test_respects_skip_and_limit(self):
        """应传递 skip 和 limit 参数。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        async def mock_empty_cursor():
            return
            yield

        mock_cursor = MagicMock()
        mock_cursor.skip = MagicMock(return_value=mock_cursor)
        mock_cursor.limit = MagicMock(return_value=mock_cursor)
        mock_cursor.__aiter__ = MagicMock(return_value=mock_empty_cursor())
        db.users.find = MagicMock(return_value=mock_cursor)

        await svc.list_users(skip=10, limit=5)
        mock_cursor.skip.assert_called_once_with(10)
        mock_cursor.limit.assert_called_once_with(5)


# ---------------------------------------------------------------------------
# deactivate_user
# ---------------------------------------------------------------------------


class TestDeactivateUser:
    """UserService.deactivate_user 测试组。"""

    @pytest.mark.asyncio
    async def test_deactivates_successfully(self):
        """应成功禁用用户。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        db.users.update_one = AsyncMock(return_value=_mock_update_result(modified_count=1))

        result = await svc.deactivate_user("targetuser")
        assert result is True

        update_call = db.users.update_one.call_args
        assert update_call[0][0] == {"username": "targetuser"}
        assert update_call[0][1]["$set"]["is_active"] is False

    @pytest.mark.asyncio
    async def test_returns_false_when_user_not_found(self):
        """用户不存在时返回 False。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        db.users.update_one = AsyncMock(return_value=_mock_update_result(modified_count=0))

        result = await svc.deactivate_user("ghost")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_db_not_set(self):
        """数据库未设置时返回 False。"""
        svc = UserService()
        result = await svc.deactivate_user("user")
        assert result is False


# ---------------------------------------------------------------------------
# activate_user
# ---------------------------------------------------------------------------


class TestActivateUser:
    """UserService.activate_user 测试组。"""

    @pytest.mark.asyncio
    async def test_activates_successfully(self):
        """应成功激活用户。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        db.users.update_one = AsyncMock(return_value=_mock_update_result(modified_count=1))

        result = await svc.activate_user("disableduser")
        assert result is True

        update_call = db.users.update_one.call_args
        assert update_call[0][1]["$set"]["is_active"] is True

    @pytest.mark.asyncio
    async def test_returns_false_when_user_not_found(self):
        """用户不存在时返回 False。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        db.users.update_one = AsyncMock(return_value=_mock_update_result(modified_count=0))

        result = await svc.activate_user("ghost")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_db_not_set(self):
        """数据库未设置时返回 False。"""
        svc = UserService()
        result = await svc.activate_user("user")
        assert result is False


# ---------------------------------------------------------------------------
# set_admin_status
# ---------------------------------------------------------------------------


class TestSetAdminStatus:
    """UserService.set_admin_status 测试组。"""

    @pytest.mark.asyncio
    async def test_sets_admin_true(self):
        """应成功设置用户为管理员。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        db.users.update_one = AsyncMock(return_value=_mock_update_result(matched_count=1))

        result = await svc.set_admin_status("targetuser", True)
        assert result is True

        update_call = db.users.update_one.call_args
        assert update_call[0][1]["$set"]["is_admin"] is True

    @pytest.mark.asyncio
    async def test_sets_admin_false(self):
        """应成功移除用户管理员权限。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        db.users.update_one = AsyncMock(return_value=_mock_update_result(matched_count=1))

        result = await svc.set_admin_status("targetuser", False)
        assert result is True

        update_call = db.users.update_one.call_args
        assert update_call[0][1]["$set"]["is_admin"] is False

    @pytest.mark.asyncio
    async def test_returns_false_when_user_not_found(self):
        """用户不存在（matched_count=0）时返回 False。"""
        svc = UserService()
        db = _setup_db_mock()
        svc.set_database(db)

        db.users.update_one = AsyncMock(return_value=_mock_update_result(matched_count=0))

        result = await svc.set_admin_status("ghost", True)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_db_not_set(self):
        """数据库未设置时返回 False。"""
        svc = UserService()
        result = await svc.set_admin_status("user", True)
        assert result is False
