"""
分析相关数据模型单元测试
覆盖 AnalysisStatus, BatchStatus, AnalysisParameters, AnalysisTask, AnalysisResult 等
"""

import pytest
from datetime import datetime, timezone
from bson import ObjectId
from pydantic import ValidationError

from app.models.analysis import (
    AnalysisStatus,
    BatchStatus,
    AnalysisParameters,
    AnalysisResult,
    AnalysisTask,
    AnalysisBatch,
    StockInfo,
    SingleAnalysisRequest,
    BatchAnalysisRequest,
    AnalysisTaskResponse,
    AnalysisBatchResponse,
    AnalysisHistoryQuery,
)


# ---------------------------------------------------------------------------
# AnalysisStatus 枚举
# ---------------------------------------------------------------------------


class TestAnalysisStatus:
    """分析状态枚举测试"""

    def test_enum_values(self):
        """所有枚举值应正确"""
        assert AnalysisStatus.PENDING == "pending"
        assert AnalysisStatus.PROCESSING == "processing"
        assert AnalysisStatus.COMPLETED == "completed"
        assert AnalysisStatus.FAILED == "failed"
        assert AnalysisStatus.CANCELLED == "cancelled"

    def test_enum_is_string(self):
        """枚举应继承 str"""
        assert isinstance(AnalysisStatus.PENDING, str)

    def test_all_status_count(self):
        """应有 5 个状态"""
        assert len(AnalysisStatus) == 5

    def test_from_value(self):
        """从字符串值获取枚举"""
        assert AnalysisStatus("pending") == AnalysisStatus.PENDING
        assert AnalysisStatus("completed") == AnalysisStatus.COMPLETED


# ---------------------------------------------------------------------------
# BatchStatus 枚举
# ---------------------------------------------------------------------------


class TestBatchStatus:
    """批次状态枚举测试"""

    def test_enum_values(self):
        """所有枚举值应正确"""
        assert BatchStatus.PENDING == "pending"
        assert BatchStatus.PROCESSING == "processing"
        assert BatchStatus.COMPLETED == "completed"
        assert BatchStatus.PARTIAL_SUCCESS == "partial_success"
        assert BatchStatus.FAILED == "failed"
        assert BatchStatus.CANCELLED == "cancelled"

    def test_enum_is_string(self):
        """枚举应继承 str"""
        assert isinstance(BatchStatus.PENDING, str)

    def test_all_status_count(self):
        """应有 6 个状态"""
        assert len(BatchStatus) == 6

    def test_partial_success_unique(self):
        """PARTIAL_SUCCESS 是 BatchStatus 特有的"""
        assert hasattr(BatchStatus, "PARTIAL_SUCCESS")
        assert not hasattr(AnalysisStatus, "PARTIAL_SUCCESS")


# ---------------------------------------------------------------------------
# AnalysisParameters
# ---------------------------------------------------------------------------


class TestAnalysisParameters:
    """分析参数模型测试"""

    def test_default_values(self):
        """默认值应正确"""
        params = AnalysisParameters()
        assert params.market_type == "A股"
        assert params.analysis_date is None
        assert params.selected_analysts == []
        assert params.custom_prompt is None
        assert params.include_sentiment is True
        assert params.include_risk is True
        assert params.language == "zh-CN"
        assert params.analyst_model == "qwen-turbo"
        assert params.debate_model == "qwen-max"
        assert params.phase2_enabled is False
        assert params.phase2_debate_rounds == 2
        assert params.phase3_enabled is False
        assert params.phase3_debate_rounds == 2
        assert params.phase4_enabled is True
        assert params.phase4_debate_rounds == 1
        assert params.mcp_enabled is False
        assert params.mcp_tools == []
        assert params.mcp_tool_ids == []

    def test_custom_values(self):
        """自定义值应正确设置"""
        params = AnalysisParameters(
            market_type="港股",
            selected_analysts=["market", "news"],
            phase2_enabled=True,
            mcp_enabled=True,
            mcp_tool_ids=["tool_a", "tool_b"],
        )
        assert params.market_type == "港股"
        assert len(params.selected_analysts) == 2
        assert params.phase2_enabled is True
        assert params.mcp_enabled is True
        assert len(params.mcp_tool_ids) == 2


# ---------------------------------------------------------------------------
# AnalysisResult
# ---------------------------------------------------------------------------


class TestAnalysisResult:
    """分析结果模型测试"""

    def test_default_values(self):
        """默认值应正确"""
        result = AnalysisResult()
        assert result.analysis_id is None
        assert result.summary is None
        assert result.recommendation is None
        assert result.confidence_score is None
        assert result.risk_level is None
        assert result.key_points == []
        assert result.detailed_analysis is None
        assert result.charts == []
        assert result.tokens_used == 0
        assert result.execution_time == 0.0
        assert result.error_message is None

    def test_full_result(self):
        """完整结果创建应成功"""
        result = AnalysisResult(
            analysis_id="analysis_123",
            summary="看涨",
            recommendation="买入",
            confidence_score=0.85,
            risk_level="中",
            key_points=["基本面良好", "技术面向好"],
            tokens_used=1500,
            execution_time=12.5,
        )
        assert result.analysis_id == "analysis_123"
        assert result.confidence_score == 0.85
        assert len(result.key_points) == 2


# ---------------------------------------------------------------------------
# AnalysisTask
# ---------------------------------------------------------------------------


class TestAnalysisTask:
    """分析任务模型测试"""

    def test_create_minimal_task(self):
        """最小必填字段创建应成功"""
        task = AnalysisTask(
            task_id="task_001",
            user_id=ObjectId(),
            symbol="000001",
        )
        assert task.task_id == "task_001"
        assert task.symbol == "000001"
        assert task.status == AnalysisStatus.PENDING
        assert task.progress == 0
        assert isinstance(task.parameters, AnalysisParameters)
        assert task.result is None
        assert task.retry_count == 0
        assert task.max_retries == 3

    def test_progress_boundary_values(self):
        """进度值应在 0-100 范围内"""
        task = AnalysisTask(
            task_id="task_001",
            user_id=ObjectId(),
            symbol="000001",
            progress=0,
        )
        assert task.progress == 0

        task = AnalysisTask(
            task_id="task_002",
            user_id=ObjectId(),
            symbol="000001",
            progress=100,
        )
        assert task.progress == 100

    def test_progress_out_of_range(self):
        """超出范围的进度应报错"""
        with pytest.raises(ValidationError):
            AnalysisTask(
                task_id="task_001",
                user_id=ObjectId(),
                symbol="000001",
                progress=-1,
            )
        with pytest.raises(ValidationError):
            AnalysisTask(
                task_id="task_001",
                user_id=ObjectId(),
                symbol="000001",
                progress=101,
            )

    def test_task_with_result(self):
        """带结果的任务创建"""
        task = AnalysisTask(
            task_id="task_001",
            user_id=ObjectId(),
            symbol="000001",
            status=AnalysisStatus.COMPLETED,
            progress=100,
            result=AnalysisResult(summary="测试结果"),
        )
        assert task.status == AnalysisStatus.COMPLETED
        assert task.result.summary == "测试结果"

    def test_populate_by_name(self):
        """通过 _id 别名填充应成功"""
        oid = ObjectId()
        task = AnalysisTask(
            _id=oid,
            task_id="task_001",
            user_id=ObjectId(),
            symbol="000001",
        )
        assert task.id == oid


# ---------------------------------------------------------------------------
# AnalysisBatch
# ---------------------------------------------------------------------------


class TestAnalysisBatch:
    """分析批次模型测试"""

    def test_create_batch(self):
        """创建批次应成功"""
        batch = AnalysisBatch(
            batch_id="batch_001",
            user_id=ObjectId(),
            title="测试批次",
        )
        assert batch.batch_id == "batch_001"
        assert batch.title == "测试批次"
        assert batch.status == BatchStatus.PENDING
        assert batch.total_tasks == 0
        assert batch.completed_tasks == 0
        assert batch.failed_tasks == 0
        assert batch.progress == 0

    def test_batch_with_tasks(self):
        """带任务统计的批次"""
        batch = AnalysisBatch(
            batch_id="batch_001",
            user_id=ObjectId(),
            title="测试批次",
            description="描述",
            total_tasks=10,
            completed_tasks=8,
            failed_tasks=2,
            progress=80,
        )
        assert batch.total_tasks == 10
        assert batch.completed_tasks == 8
        assert batch.failed_tasks == 2
        assert batch.progress == 80

    def test_batch_progress_boundary(self):
        """批次进度边界值"""
        with pytest.raises(ValidationError):
            AnalysisBatch(
                batch_id="b1",
                user_id=ObjectId(),
                title="t",
                progress=101,
            )


# ---------------------------------------------------------------------------
# StockInfo
# ---------------------------------------------------------------------------


class TestStockInfo:
    """股票信息模型测试"""

    def test_create_stock_info(self):
        """创建股票信息应成功"""
        info = StockInfo(
            symbol="000001",
            name="平安银行",
            market="A股",
        )
        assert info.symbol == "000001"
        assert info.name == "平安银行"
        assert info.market == "A股"
        assert info.industry is None
        assert info.price is None

    def test_full_stock_info(self):
        """完整股票信息"""
        info = StockInfo(
            symbol="000001",
            name="平安银行",
            market="A股",
            industry="银行",
            sector="金融",
            market_cap=250000.0,
            price=12.5,
            change_percent=1.5,
        )
        assert info.industry == "银行"
        assert info.market_cap == 250000.0
        assert info.change_percent == 1.5


# ---------------------------------------------------------------------------
# SingleAnalysisRequest
# ---------------------------------------------------------------------------


class TestSingleAnalysisRequest:
    """单股分析请求测试"""

    def test_empty_request(self):
        """空请求（全部可选）"""
        req = SingleAnalysisRequest()
        assert req.symbol is None
        assert req.stock_code is None
        assert req.parameters is None
        assert req.get_symbol() == ""

    def test_with_symbol(self):
        """带 symbol 的请求"""
        req = SingleAnalysisRequest(symbol="000001")
        assert req.get_symbol() == "000001"

    def test_with_stock_code_legacy(self):
        """兼容旧字段 stock_code"""
        req = SingleAnalysisRequest(stock_code="600519")
        assert req.get_symbol() == "600519"

    def test_symbol_priority_over_stock_code(self):
        """symbol 优先于 stock_code"""
        req = SingleAnalysisRequest(symbol="000001", stock_code="600519")
        assert req.get_symbol() == "000001"

    def test_with_parameters(self):
        """带参数的请求"""
        params = AnalysisParameters(market_type="港股")
        req = SingleAnalysisRequest(symbol="00700", parameters=params)
        assert req.parameters.market_type == "港股"


# ---------------------------------------------------------------------------
# BatchAnalysisRequest
# ---------------------------------------------------------------------------


class TestBatchAnalysisRequest:
    """批量分析请求测试"""

    def test_minimal_request(self):
        """最小批量请求"""
        req = BatchAnalysisRequest(title="测试批次")
        assert req.title == "测试批次"
        assert req.description is None
        assert req.symbols is None
        assert req.stock_codes is None
        assert req.get_symbols() == []

    def test_with_symbols(self):
        """带 symbols 的请求"""
        req = BatchAnalysisRequest(
            title="测试批次",
            symbols=["000001", "600519", "000858"],
        )
        assert req.get_symbols() == ["000001", "600519", "000858"]

    def test_with_stock_codes_legacy(self):
        """兼容旧字段"""
        req = BatchAnalysisRequest(
            title="测试批次",
            stock_codes=["000001"],
        )
        assert req.get_symbols() == ["000001"]

    def test_symbols_priority(self):
        """symbols 优先于 stock_codes"""
        req = BatchAnalysisRequest(
            title="测试",
            symbols=["000001"],
            stock_codes=["600519"],
        )
        assert req.get_symbols() == ["000001"]

    def test_title_required(self):
        """title 为必填"""
        with pytest.raises(ValidationError):
            BatchAnalysisRequest(symbols=["000001"])


# ---------------------------------------------------------------------------
# AnalysisTaskResponse
# ---------------------------------------------------------------------------


class TestAnalysisTaskResponse:
    """分析任务响应测试"""

    def test_create_response(self):
        """创建响应应成功"""
        now = datetime.now(timezone.utc)
        resp = AnalysisTaskResponse(
            task_id="task_001",
            batch_id=None,
            symbol="000001",
            stock_name="平安银行",
            status=AnalysisStatus.COMPLETED,
            progress=100,
            created_at=now,
            started_at=now,
            completed_at=now,
            result=AnalysisResult(summary="完成"),
        )
        assert resp.task_id == "task_001"
        assert resp.status == AnalysisStatus.COMPLETED

    def test_datetime_serialization(self):
        """datetime 应序列化为 ISO 格式"""
        now = datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc)
        resp = AnalysisTaskResponse(
            task_id="task_001",
            batch_id=None,
            symbol="000001",
            stock_name="平安银行",
            status=AnalysisStatus.PENDING,
            progress=0,
            created_at=now,
            started_at=None,
            completed_at=None,
            result=None,
        )
        data = resp.model_dump()
        assert isinstance(data["created_at"], str)
        assert data["started_at"] is None


# ---------------------------------------------------------------------------
# AnalysisBatchResponse
# ---------------------------------------------------------------------------


class TestAnalysisBatchResponse:
    """分析批次响应测试"""

    def test_create_response(self):
        """创建响应"""
        now = datetime.now(timezone.utc)
        resp = AnalysisBatchResponse(
            batch_id="batch_001",
            title="测试",
            description="测试批次描述",
            status=BatchStatus.COMPLETED,
            total_tasks=5,
            completed_tasks=5,
            failed_tasks=0,
            progress=100,
            created_at=now,
            completed_at=now,
        )
        assert resp.batch_id == "batch_001"
        assert resp.total_tasks == 5


# ---------------------------------------------------------------------------
# AnalysisHistoryQuery
# ---------------------------------------------------------------------------


class TestAnalysisHistoryQuery:
    """分析历史查询参数测试"""

    def test_default_values(self):
        """默认分页参数"""
        query = AnalysisHistoryQuery()
        assert query.page == 1
        assert query.page_size == 10
        assert query.symbol is None
        assert query.status is None
        assert query.start_date is None
        assert query.end_date is None

    def test_page_validation(self):
        """page 必须 >= 1"""
        with pytest.raises(ValidationError):
            AnalysisHistoryQuery(page=0)

    def test_page_size_validation(self):
        """page_size 在 1-100 之间"""
        with pytest.raises(ValidationError):
            AnalysisHistoryQuery(page_size=0)
        with pytest.raises(ValidationError):
            AnalysisHistoryQuery(page_size=101)

    def test_custom_query(self):
        """自定义查询参数"""
        query = AnalysisHistoryQuery(
            page=2,
            page_size=20,
            symbol="000001",
            status="completed",
        )
        assert query.page == 2
        assert query.page_size == 20
        assert query.symbol == "000001"
