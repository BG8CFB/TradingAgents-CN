"""
操作日志数据模型单元测试
覆盖 OperationLogCreate, OperationLogResponse, ActionType, ClearLogsRequest 等
"""

import pytest
from datetime import datetime, timezone
from bson import ObjectId
from pydantic import ValidationError

from app.models.operation_log import (
    OperationLogCreate,
    OperationLogResponse,
    OperationLogQuery,
    OperationLogListResponse,
    OperationLogStats,
    OperationLogStatsResponse,
    ClearLogsRequest,
    ClearLogsResponse,
    ActionType,
    ACTION_TYPE_NAMES,
    convert_objectid_to_str,
)


# ---------------------------------------------------------------------------
# ActionType 常量
# ---------------------------------------------------------------------------


class TestActionType:
    """操作类型常量测试"""

    def test_all_action_types_exist(self):
        """所有操作类型常量应存在"""
        assert ActionType.STOCK_ANALYSIS == "stock_analysis"
        assert ActionType.CONFIG_MANAGEMENT == "config_management"
        assert ActionType.CACHE_OPERATION == "cache_operation"
        assert ActionType.DATA_IMPORT == "data_import"
        assert ActionType.DATA_EXPORT == "data_export"
        assert ActionType.SYSTEM_SETTINGS == "system_settings"
        assert ActionType.USER_LOGIN == "user_login"
        assert ActionType.USER_LOGOUT == "user_logout"
        assert ActionType.USER_MANAGEMENT == "user_management"
        assert ActionType.DATABASE_OPERATION == "database_operation"
        assert ActionType.SCREENING == "screening"
        assert ActionType.REPORT_GENERATION == "report_generation"

    def test_action_type_names_mapping(self):
        """每个操作类型都应有对应的中文名称"""
        for attr_name in [
            "STOCK_ANALYSIS", "CONFIG_MANAGEMENT", "CACHE_OPERATION",
            "DATA_IMPORT", "DATA_EXPORT", "SYSTEM_SETTINGS",
            "USER_LOGIN", "USER_LOGOUT", "USER_MANAGEMENT",
            "DATABASE_OPERATION", "SCREENING", "REPORT_GENERATION",
        ]:
            action_value = getattr(ActionType, attr_name)
            assert action_value in ACTION_TYPE_NAMES, f"{attr_name} not in ACTION_TYPE_NAMES"

    def test_action_type_names_are_chinese(self):
        """操作类型名称应为中文"""
        assert ACTION_TYPE_NAMES[ActionType.STOCK_ANALYSIS] == "股票分析"
        assert ACTION_TYPE_NAMES[ActionType.USER_LOGIN] == "用户登录"
        assert ACTION_TYPE_NAMES[ActionType.USER_LOGOUT] == "用户登出"
        assert ACTION_TYPE_NAMES[ActionType.USER_MANAGEMENT] == "用户管理"


# ---------------------------------------------------------------------------
# OperationLogCreate
# ---------------------------------------------------------------------------


class TestOperationLogCreate:
    """创建操作日志请求模型测试"""

    def test_create_minimal(self):
        """最小必填字段创建"""
        log = OperationLogCreate(
            action_type="stock_analysis",
            action="执行了股票分析",
        )
        assert log.action_type == "stock_analysis"
        assert log.action == "执行了股票分析"
        assert log.details is None
        assert log.success is True
        assert log.error_message is None
        assert log.duration_ms is None
        assert log.ip_address is None
        assert log.user_agent is None
        assert log.session_id is None

    def test_create_full(self):
        """完整字段创建"""
        log = OperationLogCreate(
            action_type="stock_analysis",
            action="执行了股票分析",
            details={"stock_code": "000001", "market": "A股"},
            success=True,
            duration_ms=1500,
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
            session_id="sess_123",
        )
        assert log.details["stock_code"] == "000001"
        assert log.duration_ms == 1500
        assert log.ip_address == "192.168.1.1"

    def test_failed_operation(self):
        """失败操作日志"""
        log = OperationLogCreate(
            action_type="data_import",
            action="导入数据失败",
            success=False,
            error_message="网络超时",
        )
        assert log.success is False
        assert log.error_message == "网络超时"

    def test_missing_required_fields(self):
        """缺少必填字段应报错"""
        with pytest.raises(ValidationError):
            OperationLogCreate()
        with pytest.raises(ValidationError):
            OperationLogCreate(action_type="test")
        with pytest.raises(ValidationError):
            OperationLogCreate(action="test")


# ---------------------------------------------------------------------------
# OperationLogResponse
# ---------------------------------------------------------------------------


class TestOperationLogResponse:
    """操作日志响应模型测试"""

    def test_create_response(self):
        """创建日志响应"""
        now = datetime.now(timezone.utc)
        resp = OperationLogResponse(
            id=str(ObjectId()),
            user_id=str(ObjectId()),
            username="testuser",
            action_type="stock_analysis",
            action="执行了股票分析",
            success=True,
            timestamp=now,
            created_at=now,
        )
        assert resp.username == "testuser"
        assert resp.success is True
        assert resp.details is None

    def test_datetime_serialization(self):
        """datetime 应序列化为 ISO 格式"""
        now = datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
        resp = OperationLogResponse(
            id="abc",
            user_id="user1",
            username="testuser",
            action_type="test",
            action="test action",
            success=True,
            timestamp=now,
            created_at=now,
        )
        data = resp.model_dump()
        assert isinstance(data["timestamp"], str)
        assert isinstance(data["created_at"], str)

    def test_missing_required_fields(self):
        """缺少必填字段应报错"""
        with pytest.raises(ValidationError):
            OperationLogResponse(id="abc", username="test")


# ---------------------------------------------------------------------------
# OperationLogQuery
# ---------------------------------------------------------------------------


class TestOperationLogQuery:
    """操作日志查询参数测试"""

    def test_default_values(self):
        """默认分页参数"""
        query = OperationLogQuery()
        assert query.page == 1
        assert query.page_size == 20
        assert query.start_date is None
        assert query.end_date is None
        assert query.action_type is None
        assert query.success is None
        assert query.keyword is None
        assert query.user_id is None

    def test_page_validation(self):
        """page 必须 >= 1"""
        with pytest.raises(ValidationError):
            OperationLogQuery(page=0)

    def test_page_size_validation(self):
        """page_size 在 1-100 之间"""
        with pytest.raises(ValidationError):
            OperationLogQuery(page_size=0)
        with pytest.raises(ValidationError):
            OperationLogQuery(page_size=101)

    def test_custom_query(self):
        """自定义查询"""
        query = OperationLogQuery(
            page=2,
            page_size=50,
            start_date="2024-01-01",
            end_date="2024-12-31",
            action_type="stock_analysis",
            success=True,
            keyword="平安",
            user_id="507f1f77bcf86cd799439011",
        )
        assert query.page == 2
        assert query.keyword == "平安"


# ---------------------------------------------------------------------------
# OperationLogListResponse
# ---------------------------------------------------------------------------


class TestOperationLogListResponse:
    """操作日志列表响应测试"""

    def test_create_list_response(self):
        """创建列表响应"""
        resp = OperationLogListResponse(
            data={"items": [], "total": 0},
        )
        assert resp.success is True
        assert resp.message == "操作成功"

    def test_custom_message(self):
        """自定义消息"""
        resp = OperationLogListResponse(
            data={"items": []},
            message="查询完成",
        )
        assert resp.message == "查询完成"


# ---------------------------------------------------------------------------
# OperationLogStats
# ---------------------------------------------------------------------------


class TestOperationLogStats:
    """操作日志统计模型测试"""

    def test_create_stats(self):
        """创建统计"""
        stats = OperationLogStats(
            total_logs=100,
            success_logs=95,
            failed_logs=5,
            success_rate=95.0,
            action_type_distribution={"stock_analysis": 50, "config_management": 30},
            hourly_distribution=[{"hour": 10, "count": 15}],
        )
        assert stats.total_logs == 100
        assert stats.success_rate == 95.0
        assert stats.action_type_distribution["stock_analysis"] == 50

    def test_missing_required_fields(self):
        """缺少必填字段应报错"""
        with pytest.raises(ValidationError):
            OperationLogStats(total_logs=100)


# ---------------------------------------------------------------------------
# ClearLogsRequest
# ---------------------------------------------------------------------------


class TestClearLogsRequest:
    """清空日志请求模型测试"""

    def test_all_optional(self):
        """所有字段都是可选的"""
        req = ClearLogsRequest()
        assert req.days is None
        assert req.action_type is None

    def test_with_days(self):
        """指定保留天数"""
        req = ClearLogsRequest(days=30)
        assert req.days == 30

    def test_with_action_type(self):
        """指定操作类型"""
        req = ClearLogsRequest(action_type="stock_analysis")
        assert req.action_type == "stock_analysis"

    def test_both_fields(self):
        """同时指定两个字段"""
        req = ClearLogsRequest(days=7, action_type="cache_operation")
        assert req.days == 7
        assert req.action_type == "cache_operation"


# ---------------------------------------------------------------------------
# ClearLogsResponse
# ---------------------------------------------------------------------------


class TestClearLogsResponse:
    """清空日志响应测试"""

    def test_create_response(self):
        """创建清空响应"""
        resp = ClearLogsResponse(
            data={"deleted_count": 50},
        )
        assert resp.success is True
        assert resp.data["deleted_count"] == 50
        assert resp.message == "清空日志成功"


# ---------------------------------------------------------------------------
# convert_objectid_to_str 辅助函数
# ---------------------------------------------------------------------------


class TestConvertObjectIdToStr:
    """ObjectId 转字符串辅助函数测试"""

    def test_converts_objectid(self):
        """应将 _id 转为 id 字符串"""
        oid = ObjectId()
        doc = {"_id": oid, "name": "test"}
        result = convert_objectid_to_str(doc)
        assert "id" in result
        assert "_id" not in result
        assert result["id"] == str(oid)
        assert result["name"] == "test"

    def test_none_doc(self):
        """None 文档应安全返回"""
        result = convert_objectid_to_str(None)
        assert result is None

    def test_doc_without_id(self):
        """没有 _id 的文档应保持不变"""
        doc = {"name": "test", "value": 42}
        result = convert_objectid_to_str(doc)
        assert result == {"name": "test", "value": 42}

    def test_empty_doc(self):
        """空文档应安全处理"""
        result = convert_objectid_to_str({})
        assert result == {}
