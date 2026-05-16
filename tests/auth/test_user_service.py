"""
用户服务的单元测试。

测试 app/services/user_service.py 中的 UserService 类。
所有 MongoDB 操作通过 SimulatedMongoDB 模拟，确保测试自包含且无外部依赖。
"""

from datetime import datetime, timezone
from bson import ObjectId

import pytest

from app.models.user import User, UserCreate, UserUpdate, UserResponse
from app.services.user_service import UserService
from app.utils.passwords import hash_password
from test_infra import SimulatedMongoDB


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
            "default_debate_rounds": 2,
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


def _setup_db():
    """创建一个 SimulatedMongoDB 实例。"""
    return SimulatedMongoDB()


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
        db = _setup_db()
        svc.set_database(db)

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
        db = _setup_db()
        svc.set_database(db)

        # 先插入一个已有用户
        existing_doc = _make_user_doc(username="existing_user")
        await db.users.insert_one(existing_doc)

        user_data = UserCreate(
            username="existing_user", email="other@example.com", password="pass123"
        )
        result = await svc.create_user(user_data)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_duplicate_email(self):
        """邮箱已存在时返回 None。"""
        svc = UserService()
        db = _setup_db()
        svc.set_database(db)

        # 先插入一个已有邮箱的用户
        existing_doc = _make_user_doc(username="other_user", email="dup@example.com")
        await db.users.insert_one(existing_doc)

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
        db = _setup_db()
        svc.set_database(db)

        user_data = UserCreate(
            username="fieldcheck", email="fields@example.com", password="pass123"
        )
        await svc.create_user(user_data)

        # 通过 SimulatedMongoDB 查询验证
        inserted_doc = await db.users.find_one({"username": "fieldcheck"})
        assert inserted_doc is not None
        assert inserted_doc["username"] == "fieldcheck"
        assert inserted_doc["email"] == "fields@example.com"
        assert "hashed_password" in inserted_doc
        assert inserted_doc["is_active"] is True
        assert inserted_doc["is_verified"] is False
        assert inserted_doc["is_admin"] is False
        assert "preferences" in inserted_doc
        assert inserted_doc["daily_quota"] == 1000
        assert inserted_doc["concurrent_limit"] == 3


# ---------------------------------------------------------------------------
# authenticate_user
# ---------------------------------------------------------------------------


class TestAuthenticateUser:
    """UserService.authenticate_user 测试组。"""

    @pytest.mark.asyncio
    async def test_returns_user_for_correct_credentials(self):
        """正确凭据应返回 User 对象。"""
        svc = UserService()
        db = _setup_db()
        svc.set_database(db)

        password = "correct_pass"
        doc = _make_user_doc(username="authuser", password=password)
        await db.users.insert_one(doc)

        user = await svc.authenticate_user("authuser", password)
        assert user is not None
        assert isinstance(user, User)
        assert user.username == "authuser"

    @pytest.mark.asyncio
    async def test_returns_none_for_wrong_password(self):
        """错误密码应返回 None。"""
        svc = UserService()
        db = _setup_db()
        svc.set_database(db)

        doc = _make_user_doc(username="authuser", password="right_pass")
        await db.users.insert_one(doc)

        result = await svc.authenticate_user("authuser", "wrong_pass")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_nonexistent_user(self):
        """不存在的用户应返回 None。"""
        svc = UserService()
        db = _setup_db()
        svc.set_database(db)

        result = await svc.authenticate_user("ghost", "any_pass")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_inactive_user(self):
        """被禁用的用户应返回 None。"""
        svc = UserService()
        db = _setup_db()
        svc.set_database(db)

        doc = _make_user_doc(username="inactive_user", password="pass", is_active=False)
        await db.users.insert_one(doc)

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
        db = _setup_db()
        svc.set_database(db)

        doc = _make_user_doc(username="loginuser", password="pass")
        await db.users.insert_one(doc)

        await svc.authenticate_user("loginuser", "pass")

        # 验证数据库中 last_login 已被更新
        updated_doc = await db.users.find_one({"username": "loginuser"})
        assert updated_doc is not None
        assert updated_doc["last_login"] is not None

    @pytest.mark.asyncio
    async def test_rehashes_password_if_needed(self):
        """如果哈希需要升级（SHA256），认证成功后应自动重哈希。"""
        svc = UserService()
        db = _setup_db()
        svc.set_database(db)

        # 使用 SHA256 哈希（需要重哈希）
        sha_password = "old_password"
        doc = _make_user_doc(username="legacy_user")
        from app.utils.passwords import legacy_sha256_hash
        doc["hashed_password"] = legacy_sha256_hash(sha_password)
        await db.users.insert_one(doc)

        user = await svc.authenticate_user("legacy_user", sha_password)
        assert user is not None

        # 验证数据库中的密码已被更新为 bcrypt 格式
        updated_doc = await db.users.find_one({"username": "legacy_user"})
        assert updated_doc is not None
        assert updated_doc["hashed_password"].startswith(("$2a$", "$2b$", "$2y$"))


# ---------------------------------------------------------------------------
# get_user_by_username
# ---------------------------------------------------------------------------


class TestGetUserByUsername:
    """UserService.get_user_by_username 测试组。"""

    @pytest.mark.asyncio
    async def test_returns_user_when_found(self):
        """用户存在时应返回 User 对象。"""
        svc = UserService()
        db = _setup_db()
        svc.set_database(db)

        doc = _make_user_doc(username="findme")
        await db.users.insert_one(doc)

        user = await svc.get_user_by_username("findme")
        assert user is not None
        assert user.username == "findme"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        """用户不存在时应返回 None。"""
        svc = UserService()
        db = _setup_db()
        svc.set_database(db)

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
        db = _setup_db()
        svc.set_database(db)

        doc = _make_user_doc(username="upuser", email="old@example.com")
        await db.users.insert_one(doc)

        user_data = UserUpdate(email="new@example.com")
        result = await svc.update_user("upuser", user_data)
        assert result is not None
        assert result.email == "new@example.com"

    @pytest.mark.asyncio
    async def test_returns_none_for_duplicate_email(self):
        """更新邮箱为已存在的邮箱时返回 None。"""
        svc = UserService()
        db = _setup_db()
        svc.set_database(db)

        # 插入两个用户
        doc1 = _make_user_doc(username="other", email="taken@example.com")
        doc2 = _make_user_doc(username="upuser", email="upuser@example.com")
        await db.users.insert_one(doc1)
        await db.users.insert_one(doc2)

        user_data = UserUpdate(email="taken@example.com")
        result = await svc.update_user("upuser", user_data)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_modification(self):
        """没有实际修改（用户不存在）时返回 None。"""
        svc = UserService()
        db = _setup_db()
        svc.set_database(db)

        user_data = UserUpdate(email="same@example.com")
        result = await svc.update_user("upuser", user_data)
        # 用户不存在，update_one 的 modified_count 为 0
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
        db = _setup_db()
        svc.set_database(db)

        old_password = "old_pass123"
        doc = _make_user_doc(username="pwuser", password=old_password)
        await db.users.insert_one(doc)

        result = await svc.change_password("pwuser", old_password, "new_pass456")
        assert result is True

    @pytest.mark.asyncio
    async def test_fails_with_wrong_old_password(self):
        """旧密码错误时应失败。"""
        svc = UserService()
        db = _setup_db()
        svc.set_database(db)

        doc = _make_user_doc(username="pwuser", password="real_pass")
        await db.users.insert_one(doc)

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
        db = _setup_db()
        svc.set_database(db)

        doc = _make_user_doc(username="someuser")
        await db.users.insert_one(doc)

        result = await svc.reset_password("someuser", "new_reset_pass")
        assert result is True

        # 验证密码确实被更新（可以用新密码认证）
        user = await svc.authenticate_user("someuser", "new_reset_pass")
        assert user is not None

    @pytest.mark.asyncio
    async def test_returns_false_when_user_not_found(self):
        """用户不存在时应返回 False。"""
        svc = UserService()
        db = _setup_db()
        svc.set_database(db)

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
        db = _setup_db()
        svc.set_database(db)

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
        db = _setup_db()
        svc.set_database(db)

        existing_doc = _make_user_doc(username="admin", is_admin=True)
        await db.users.insert_one(existing_doc)

        admin = await svc.create_admin_user(
            username="admin", password="admin_pass"
        )
        assert admin is not None
        assert admin.username == "admin"

        # 验证数据库中只有一条记录（没有新增）
        count = await db.users.count_documents({"username": "admin"})
        assert count == 1

    @pytest.mark.asyncio
    async def test_returns_none_when_no_password(self):
        """未提供密码时应返回 None。"""
        svc = UserService()
        db = _setup_db()
        svc.set_database(db)

        result = await svc.create_admin_user(username="admin", password=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_empty_password(self):
        """空密码应返回 None。"""
        svc = UserService()
        db = _setup_db()
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
        db = _setup_db()
        svc.set_database(db)

        doc1 = _make_user_doc(username="user1")
        doc2 = _make_user_doc(username="user2", email="user2@example.com")
        await db.users.insert_one(doc1)
        await db.users.insert_one(doc2)

        result = await svc.list_users()
        assert len(result) == 2
        assert all(isinstance(u, UserResponse) for u in result)
        usernames = {u.username for u in result}
        assert "user1" in usernames
        assert "user2" in usernames

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_users(self):
        """没有用户时应返回空列表。"""
        svc = UserService()
        db = _setup_db()
        svc.set_database(db)

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
        db = _setup_db()
        svc.set_database(db)

        # 插入 5 个用户
        for i in range(5):
            await db.users.insert_one(
                _make_user_doc(username=f"user_{i}", email=f"user{i}@example.com")
            )

        # skip=2, limit=2 应返回第 3、4 个
        result = await svc.list_users(skip=2, limit=2)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# deactivate_user
# ---------------------------------------------------------------------------


class TestDeactivateUser:
    """UserService.deactivate_user 测试组。"""

    @pytest.mark.asyncio
    async def test_deactivates_successfully(self):
        """应成功禁用用户。"""
        svc = UserService()
        db = _setup_db()
        svc.set_database(db)

        doc = _make_user_doc(username="targetuser")
        await db.users.insert_one(doc)

        result = await svc.deactivate_user("targetuser")
        assert result is True

        # 验证数据库中用户已被禁用
        updated_doc = await db.users.find_one({"username": "targetuser"})
        assert updated_doc["is_active"] is False

    @pytest.mark.asyncio
    async def test_returns_false_when_user_not_found(self):
        """用户不存在时返回 False。"""
        svc = UserService()
        db = _setup_db()
        svc.set_database(db)

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
        db = _setup_db()
        svc.set_database(db)

        doc = _make_user_doc(username="disableduser", is_active=False)
        await db.users.insert_one(doc)

        result = await svc.activate_user("disableduser")
        assert result is True

        # 验证数据库中用户已被激活
        updated_doc = await db.users.find_one({"username": "disableduser"})
        assert updated_doc["is_active"] is True

    @pytest.mark.asyncio
    async def test_returns_false_when_user_not_found(self):
        """用户不存在时返回 False。"""
        svc = UserService()
        db = _setup_db()
        svc.set_database(db)

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
        db = _setup_db()
        svc.set_database(db)

        doc = _make_user_doc(username="targetuser")
        await db.users.insert_one(doc)

        result = await svc.set_admin_status("targetuser", True)
        assert result is True

        # 验证数据库中 is_admin 已更新
        updated_doc = await db.users.find_one({"username": "targetuser"})
        assert updated_doc["is_admin"] is True

    @pytest.mark.asyncio
    async def test_sets_admin_false(self):
        """应成功移除用户管理员权限。"""
        svc = UserService()
        db = _setup_db()
        svc.set_database(db)

        doc = _make_user_doc(username="targetuser", is_admin=True)
        await db.users.insert_one(doc)

        result = await svc.set_admin_status("targetuser", False)
        assert result is True

        # 验证数据库中 is_admin 已更新
        updated_doc = await db.users.find_one({"username": "targetuser"})
        assert updated_doc["is_admin"] is False

    @pytest.mark.asyncio
    async def test_returns_false_when_user_not_found(self):
        """用户不存在时返回 False。"""
        svc = UserService()
        db = _setup_db()
        svc.set_database(db)

        result = await svc.set_admin_status("ghost", True)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_db_not_set(self):
        """数据库未设置时返回 False。"""
        svc = UserService()
        result = await svc.set_admin_status("user", True)
        assert result is False
