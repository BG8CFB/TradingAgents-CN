"""
股票筛选相关数据模型单元测试
覆盖 OperatorType, FieldType, ScreeningCondition, ScreeningRequest, BASIC_FIELDS_INFO 等
"""

import pytest
from pydantic import ValidationError

from app.models.screening import (
    OperatorType,
    FieldType,
    ScreeningCondition,
    ScreeningRequest,
    ScreeningResponse,
    FieldInfo,
    FieldStatistics,
    BASIC_FIELDS_INFO,
)


# ---------------------------------------------------------------------------
# OperatorType 枚举
# ---------------------------------------------------------------------------


class TestOperatorType:
    """筛选操作符类型枚举测试"""

    def test_all_enum_values(self):
        """所有枚举值应正确"""
        assert OperatorType.GT == ">"
        assert OperatorType.LT == "<"
        assert OperatorType.GTE == ">="
        assert OperatorType.LTE == "<="
        assert OperatorType.EQ == "=="
        assert OperatorType.NE == "!="
        assert OperatorType.BETWEEN == "between"
        assert OperatorType.IN == "in"
        assert OperatorType.NOT_IN == "not_in"
        assert OperatorType.CONTAINS == "contains"
        assert OperatorType.CROSS_UP == "cross_up"
        assert OperatorType.CROSS_DOWN == "cross_down"

    def test_enum_is_string(self):
        """枚举应继承 str"""
        assert isinstance(OperatorType.GT, str)

    def test_all_operators_count(self):
        """应有 12 个操作符"""
        assert len(OperatorType) == 12

    def test_from_value(self):
        """从字符串值获取枚举"""
        assert OperatorType(">") == OperatorType.GT
        assert OperatorType("between") == OperatorType.BETWEEN


# ---------------------------------------------------------------------------
# FieldType 枚举
# ---------------------------------------------------------------------------


class TestFieldType:
    """字段类型枚举测试"""

    def test_all_enum_values(self):
        """所有枚举值应正确"""
        assert FieldType.BASIC == "basic"
        assert FieldType.TECHNICAL == "technical"
        assert FieldType.FUNDAMENTAL == "fundamental"

    def test_enum_is_string(self):
        """枚举应继承 str"""
        assert isinstance(FieldType.BASIC, str)

    def test_all_types_count(self):
        """应有 3 个类型"""
        assert len(FieldType) == 3


# ---------------------------------------------------------------------------
# ScreeningCondition
# ---------------------------------------------------------------------------


class TestScreeningCondition:
    """筛选条件模型测试"""

    def test_create_with_string_value(self):
        """字符串值条件"""
        cond = ScreeningCondition(
            field="name",
            operator=OperatorType.CONTAINS,
            value="银行",
        )
        assert cond.field == "name"
        assert cond.operator == "contains"  # use_enum_values=True
        assert cond.value == "银行"

    def test_create_with_numeric_value(self):
        """数值条件"""
        cond = ScreeningCondition(
            field="pe",
            operator=OperatorType.GT,
            value=10.5,
        )
        assert cond.value == 10.5

    def test_create_with_list_value(self):
        """列表值（用于 IN/BETWEEN）"""
        cond = ScreeningCondition(
            field="symbol",
            operator=OperatorType.IN,
            value=["000001", "600519"],
        )
        assert len(cond.value) == 2

    def test_create_between_condition(self):
        """区间条件"""
        cond = ScreeningCondition(
            field="pe",
            operator=OperatorType.BETWEEN,
            value=[5, 30],
            field_type=FieldType.FUNDAMENTAL,
        )
        assert cond.value == [5, 30]

    def test_with_field_type(self):
        """带字段类型的条件"""
        cond = ScreeningCondition(
            field="close",
            operator=OperatorType.GT,
            value=10,
            field_type=FieldType.FUNDAMENTAL,
        )
        assert cond.field_type == "fundamental"  # use_enum_values=True

    def test_missing_required_fields(self):
        """缺少必填字段应报错"""
        with pytest.raises(ValidationError):
            ScreeningCondition(field="pe")
        with pytest.raises(ValidationError):
            ScreeningCondition(operator=OperatorType.GT, value=10)

    def test_enum_values_serialized(self):
        """use_enum_values=True 应序列化为字符串值"""
        cond = ScreeningCondition(
            field="pe",
            operator=OperatorType.GTE,
            value=15.0,
            field_type=FieldType.FUNDAMENTAL,
        )
        data = cond.model_dump()
        assert data["operator"] == ">="
        assert data["field_type"] == "fundamental"


# ---------------------------------------------------------------------------
# ScreeningRequest
# ---------------------------------------------------------------------------


class TestScreeningRequest:
    """筛选请求模型测试"""

    def test_default_values(self):
        """默认值应正确"""
        req = ScreeningRequest()
        assert req.market == "CN"
        assert req.date is None
        assert req.adj == "qfq"
        assert req.conditions == []
        assert req.order_by is None
        assert req.limit == 50
        assert req.offset == 0
        assert req.use_database_optimization is True

    def test_with_conditions(self):
        """带条件的请求"""
        req = ScreeningRequest(
            conditions=[
                ScreeningCondition(field="pe", operator=OperatorType.GT, value=10),
                ScreeningCondition(field="close", operator=OperatorType.LT, value=100),
            ]
        )
        assert len(req.conditions) == 2

    def test_limit_boundary(self):
        """limit 边界值"""
        req = ScreeningRequest(limit=1)
        assert req.limit == 1
        req = ScreeningRequest(limit=500)
        assert req.limit == 500

    def test_limit_out_of_range(self):
        """limit 超出范围应报错"""
        with pytest.raises(ValidationError):
            ScreeningRequest(limit=0)
        with pytest.raises(ValidationError):
            ScreeningRequest(limit=501)

    def test_offset_validation(self):
        """offset 不能为负"""
        with pytest.raises(ValidationError):
            ScreeningRequest(offset=-1)

    def test_custom_request(self):
        """自定义请求"""
        req = ScreeningRequest(
            market="HK",
            date="2024-01-15",
            adj="hfq",
            limit=100,
            offset=20,
            use_database_optimization=False,
        )
        assert req.market == "HK"
        assert req.date == "2024-01-15"
        assert req.adj == "hfq"
        assert req.limit == 100
        assert req.offset == 20
        assert req.use_database_optimization is False


# ---------------------------------------------------------------------------
# ScreeningResponse
# ---------------------------------------------------------------------------


class TestScreeningResponse:
    """筛选响应模型测试"""

    def test_create_response(self):
        """创建响应应成功"""
        resp = ScreeningResponse(
            total=100,
            items=[{"symbol": "000001", "name": "平安银行"}],
        )
        assert resp.total == 100
        assert len(resp.items) == 1
        assert resp.took_ms is None
        assert resp.optimization_used is None
        assert resp.source is None

    def test_response_with_metadata(self):
        """带元数据的响应"""
        resp = ScreeningResponse(
            total=50,
            items=[],
            took_ms=150,
            optimization_used="database",
            source="tushare",
        )
        assert resp.took_ms == 150
        assert resp.optimization_used == "database"
        assert resp.source == "tushare"


# ---------------------------------------------------------------------------
# FieldInfo
# ---------------------------------------------------------------------------


class TestFieldInfo:
    """字段信息模型测试"""

    def test_create_field_info(self):
        """创建字段信息"""
        fi = FieldInfo(
            name="pe",
            display_name="市盈率",
            field_type=FieldType.FUNDAMENTAL,
            data_type="number",
            description="市盈率(PE)",
            unit="倍",
            supported_operators=[OperatorType.GT, OperatorType.LT, OperatorType.BETWEEN],
        )
        assert fi.name == "pe"
        assert fi.display_name == "市盈率"
        assert fi.unit == "倍"
        assert len(fi.supported_operators) == 3

    def test_field_info_with_statistics(self):
        """带统计信息的字段"""
        fi = FieldInfo(
            name="pe",
            display_name="市盈率",
            field_type=FieldType.FUNDAMENTAL,
            data_type="number",
            min_value=1.5,
            max_value=500.0,
            avg_value=35.2,
        )
        assert fi.min_value == 1.5
        assert fi.max_value == 500.0
        assert fi.avg_value == 35.2

    def test_field_info_with_available_values(self):
        """带可选值的字段"""
        fi = FieldInfo(
            name="industry",
            display_name="行业",
            field_type=FieldType.BASIC,
            data_type="string",
            available_values=["银行", "房地产", "医药"],
        )
        assert len(fi.available_values) == 3


# ---------------------------------------------------------------------------
# FieldStatistics
# ---------------------------------------------------------------------------


class TestFieldStatistics:
    """字段统计信息模型测试"""

    def test_create_statistics(self):
        """创建统计信息"""
        stats = FieldStatistics(
            field="pe",
            count=4500,
            min_value=2.1,
            max_value=300.5,
            avg_value=35.8,
            median_value=28.0,
            std_value=25.3,
        )
        assert stats.field == "pe"
        assert stats.count == 4500
        assert stats.median_value == 28.0


# ---------------------------------------------------------------------------
# BASIC_FIELDS_INFO 预定义字段
# ---------------------------------------------------------------------------


class TestBasicFieldsInfo:
    """预定义字段信息完整性测试"""

    def test_contains_core_fields(self):
        """应包含核心字段"""
        assert "symbol" in BASIC_FIELDS_INFO
        assert "name" in BASIC_FIELDS_INFO
        assert "industry" in BASIC_FIELDS_INFO
        assert "area" in BASIC_FIELDS_INFO

    def test_contains_fundamental_fields(self):
        """应包含基本面字段"""
        assert "total_mv" in BASIC_FIELDS_INFO
        assert "circ_mv" in BASIC_FIELDS_INFO
        assert "pe" in BASIC_FIELDS_INFO
        assert "pb" in BASIC_FIELDS_INFO
        assert "pe_ttm" in BASIC_FIELDS_INFO
        assert "pb_mrq" in BASIC_FIELDS_INFO
        assert "roe" in BASIC_FIELDS_INFO

    def test_contains_technical_fields(self):
        """应包含技术指标字段"""
        assert "turnover_rate" in BASIC_FIELDS_INFO
        assert "volume_ratio" in BASIC_FIELDS_INFO
        assert "ma20" in BASIC_FIELDS_INFO
        assert "rsi14" in BASIC_FIELDS_INFO

    def test_contains_price_fields(self):
        """应包含价格数据字段"""
        assert "close" in BASIC_FIELDS_INFO
        assert "pct_chg" in BASIC_FIELDS_INFO
        assert "amount" in BASIC_FIELDS_INFO
        assert "volume" in BASIC_FIELDS_INFO

    def test_contains_kdj_fields(self):
        """应包含 KDJ 字段"""
        assert "kdj_k" in BASIC_FIELDS_INFO
        assert "kdj_d" in BASIC_FIELDS_INFO
        assert "kdj_j" in BASIC_FIELDS_INFO

    def test_contains_macd_fields(self):
        """应包含 MACD 字段"""
        assert "dif" in BASIC_FIELDS_INFO
        assert "dea" in BASIC_FIELDS_INFO
        assert "macd_hist" in BASIC_FIELDS_INFO

    def test_contains_compatibility_fields(self):
        """应包含兼容字段"""
        assert "code" in BASIC_FIELDS_INFO

    def test_all_fields_are_field_info_instances(self):
        """所有值都应是 FieldInfo 实例"""
        for key, value in BASIC_FIELDS_INFO.items():
            assert isinstance(value, FieldInfo), f"{key} is not a FieldInfo instance"

    def test_all_fields_have_operators(self):
        """所有字段都应有支持的操作符"""
        for key, value in BASIC_FIELDS_INFO.items():
            assert len(value.supported_operators) > 0, f"{key} has no operators"

    def test_all_fields_have_required_attributes(self):
        """所有字段应有必填属性"""
        for key, value in BASIC_FIELDS_INFO.items():
            assert value.name, f"{key} missing name"
            assert value.display_name, f"{key} missing display_name"
            assert value.field_type, f"{key} missing field_type"
            assert value.data_type, f"{key} missing data_type"

    def test_total_field_count(self):
        """字段总数应合理（>= 20）"""
        assert len(BASIC_FIELDS_INFO) >= 20
