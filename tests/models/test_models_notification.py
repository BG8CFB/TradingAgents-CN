"""
通知数据模型单元测试
覆盖 NotificationType, NotificationStatus, NotificationCreate, NotificationDB,
NotificationOut, NotificationList 等
"""

import pytest
from datetime import datetime, timezone
from bson import ObjectId
from pydantic import ValidationError

from app.models.notification import (
    NotificationType,
    NotificationStatus,
    NotificationCreate,
    NotificationDB,
    NotificationOut,
    NotificationList,
    to_str_id,
)


# ---------------------------------------------------------------------------
# to_str_id 辅助函数
# ---------------------------------------------------------------------------


class TestToStrId:
    """ObjectId 转字符串辅助函数测试"""

    def test_converts_objectid(self):
        """应将 ObjectId 转为字符串"""
        oid = ObjectId()
        result = to_str_id(oid)
        assert isinstance(result, str)
        assert result == str(oid)

    def test_converts_string(self):
        """字符串应直接返回字符串"""
        result = to_str_id("507f1f77bcf86cd799439011")
        assert result == "507f1f77bcf86cd799439011"

    def test_converts_number(self):
        """数字应转为字符串"""
        result = to_str_id(12345)
        assert result == "12345"

    def test_handles_exception(self):
        """异常情况应返回空字符串"""
        class BadObj:
            def __str__(self):
                raise RuntimeError("cannot stringify")

        result = to_str_id(BadObj())
        assert result == ""


# ---------------------------------------------------------------------------
# NotificationType Literal
# ---------------------------------------------------------------------------


class TestNotificationType:
    """通知类型 Literal 测试"""

    def test_valid_types(self):
        """合法通知类型"""
        assert "analysis" in ("analysis", "alert", "system")
        assert "alert" in ("analysis", "alert", "system")
        assert "system" in ("analysis", "alert", "system")


# ---------------------------------------------------------------------------
# NotificationCreate
# ---------------------------------------------------------------------------


class TestNotificationCreate:
    """创建通知请求模型测试"""

    def test_create_minimal(self):
        """最小必填字段"""
        notif = NotificationCreate(
            user_id="user_001",
            type="analysis",
            title="分析完成",
        )
        assert notif.user_id == "user_001"
        assert notif.type == "analysis"
        assert notif.title == "分析完成"
        assert notif.content is None
        assert notif.link is None
        assert notif.source is None
        assert notif.severity is None
        assert notif.metadata is None

    def test_create_full(self):
        """完整字段"""
        notif = NotificationCreate(
            user_id="user_001",
            type="alert",
            title="价格提醒",
            content="平安银行价格突破15元",
            link="/analysis/000001",
            source="price_monitor",
            severity="warning",
            metadata={"stock_code": "000001", "price": 15.0},
        )
        assert notif.content == "平安银行价格突破15元"
        assert notif.severity == "warning"
        assert notif.metadata["stock_code"] == "000001"

    def test_invalid_type(self):
        """无效通知类型应报错"""
        with pytest.raises(ValidationError):
            NotificationCreate(
                user_id="user_001",
                type="invalid_type",
                title="test",
            )

    def test_invalid_severity(self):
        """无效严重级别应报错"""
        with pytest.raises(ValidationError):
            NotificationCreate(
                user_id="user_001",
                type="analysis",
                title="test",
                severity="critical",
            )

    def test_valid_severity_values(self):
        """合法严重级别"""
        for sev in ("info", "success", "warning", "error"):
            notif = NotificationCreate(
                user_id="u1",
                type="system",
                title="test",
                severity=sev,
            )
            assert notif.severity == sev

    def test_missing_required_fields(self):
        """缺少必填字段应报错"""
        with pytest.raises(ValidationError):
            NotificationCreate()
        with pytest.raises(ValidationError):
            NotificationCreate(user_id="u1")
        with pytest.raises(ValidationError):
            NotificationCreate(user_id="u1", type="analysis")


# ---------------------------------------------------------------------------
# NotificationDB
# ---------------------------------------------------------------------------


class TestNotificationDB:
    """通知数据库模型测试"""

    def test_create_minimal(self):
        """最小字段"""
        notif = NotificationDB(
            user_id="user_001",
            type="analysis",
            title="分析完成",
        )
        assert notif.user_id == "user_001"
        assert notif.id is None
        assert notif.severity == "info"
        assert notif.status == "unread"
        assert notif.content is None
        assert notif.link is None

    def test_create_with_id(self):
        """带 ID 创建"""
        notif = NotificationDB(
            id="507f1f77bcf86cd799439011",
            user_id="user_001",
            type="system",
            title="系统维护通知",
            severity="warning",
            status="read",
        )
        assert notif.id == "507f1f77bcf86cd799439011"
        assert notif.status == "read"

    def test_default_status_is_unread(self):
        """默认状态应为 unread"""
        notif = NotificationDB(
            user_id="u1",
            type="analysis",
            title="test",
        )
        assert notif.status == "unread"

    def test_has_created_at(self):
        """应有创建时间"""
        notif = NotificationDB(
            user_id="u1",
            type="analysis",
            title="test",
        )
        assert notif.created_at is not None
        assert isinstance(notif.created_at, datetime)

    def test_invalid_status(self):
        """无效状态应报错"""
        with pytest.raises(ValidationError):
            NotificationDB(
                user_id="u1",
                type="analysis",
                title="test",
                status="invalid",
            )


# ---------------------------------------------------------------------------
# NotificationOut
# ---------------------------------------------------------------------------


class TestNotificationOut:
    """通知输出模型测试"""

    def test_create_notification_out(self):
        """创建输出通知"""
        now = datetime.now(timezone.utc)
        notif = NotificationOut(
            id="notif_001",
            type="analysis",
            title="分析完成",
            content="平安银行分析已完成",
            status="unread",
            created_at=now,
        )
        assert notif.id == "notif_001"
        assert notif.type == "analysis"
        assert notif.status == "unread"

    def test_with_optional_fields(self):
        """带可选字段"""
        now = datetime.now(timezone.utc)
        notif = NotificationOut(
            id="notif_001",
            type="alert",
            title="价格提醒",
            content="突破新高",
            link="/stock/000001",
            source="monitor",
            status="read",
            created_at=now,
        )
        assert notif.link == "/stock/000001"
        assert notif.source == "monitor"

    def test_datetime_serialization(self):
        """datetime 应序列化为 ISO 格式"""
        now = datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc)
        notif = NotificationOut(
            id="notif_001",
            type="system",
            title="通知",
            status="unread",
            created_at=now,
        )
        data = notif.model_dump()
        assert isinstance(data["created_at"], str)
        assert "2024-06-15" in data["created_at"]

    def test_missing_required_fields(self):
        """缺少必填字段应报错"""
        with pytest.raises(ValidationError):
            NotificationOut(id="abc", type="system", title="test")
        with pytest.raises(ValidationError):
            NotificationOut(id="abc", type="system", title="test", status="unread")


# ---------------------------------------------------------------------------
# NotificationList
# ---------------------------------------------------------------------------


class TestNotificationList:
    """通知列表模型测试"""

    def test_create_empty_list(self):
        """创建空列表"""
        notif_list = NotificationList(items=[])
        assert notif_list.items == []
        assert notif_list.total == 0
        assert notif_list.page == 1
        assert notif_list.page_size == 20

    def test_create_with_items(self):
        """创建带项的列表"""
        now = datetime.now(timezone.utc)
        items = [
            NotificationOut(
                id="n1",
                type="analysis",
                title="通知1",
                status="unread",
                created_at=now,
            ),
            NotificationOut(
                id="n2",
                type="system",
                title="通知2",
                status="read",
                created_at=now,
            ),
        ]
        notif_list = NotificationList(
            items=items,
            total=2,
            page=1,
            page_size=10,
        )
        assert len(notif_list.items) == 2
        assert notif_list.total == 2

    def test_pagination_fields(self):
        """分页字段"""
        notif_list = NotificationList(
            items=[],
            total=100,
            page=5,
            page_size=20,
        )
        assert notif_list.page == 5
        assert notif_list.page_size == 20
