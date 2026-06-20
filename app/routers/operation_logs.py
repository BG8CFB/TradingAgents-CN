"""
操作日志API路由
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse

from app.routers.auth_db import get_current_user, require_admin
from app.services.operation_log_service import get_operation_log_service
from app.utils.timezone import now_config_tz, format_date_compact
from app.core.response import safe_error_message
from app.models.operation_log import (
    OperationLogQuery,
    OperationLogListResponse,
    OperationLogStatsResponse,
    ClearLogsRequest,
    ClearLogsResponse
)

router = APIRouter(prefix="/api/operation-logs", tags=["Operation Logs"])
logger = logging.getLogger("webapi")


@router.get("/list", response_model=OperationLogListResponse)
async def get_operation_logs(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    start_date: str = Query(None, description="开始日期"),
    end_date: str = Query(None, description="结束日期"),
    action_type: str = Query(None, description="操作类型"),
    success: bool = Query(None, description="是否成功"),
    keyword: str = Query(None, description="关键词搜索"),
    current_user: dict = Depends(get_current_user)
):
    """获取操作日志列表"""
    try:
        logger.info(f"🔍 用户 {current_user['username']} 获取操作日志列表")

        service = get_operation_log_service()
        # 非 admin 用户只能查看自己的日志
        is_admin = bool(current_user.get("is_admin"))
        user_id_filter = None if is_admin else str(current_user.get("id", ""))
        query = OperationLogQuery(
            page=page,
            page_size=page_size,
            start_date=start_date,
            end_date=end_date,
            action_type=action_type,
            success=success,
            keyword=keyword,
            user_id=user_id_filter,
        )
        
        logs, total = await service.get_logs(query)
        
        return OperationLogListResponse(
            success=True,
            data={
                "logs": [log.dict() for log in logs],
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size
            },
            message="获取操作日志列表成功"
        )
        
    except Exception as e:
        logger.error(f"获取操作日志列表失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=safe_error_message(e, "获取操作日志列表失败")
        )


@router.get("/stats", response_model=OperationLogStatsResponse)
async def get_operation_log_stats(
    days: int = Query(30, ge=1, le=365, description="统计天数"),
    current_user: dict = Depends(get_current_user)
):
    """获取操作日志统计"""
    try:
        logger.info(f"📊 用户 {current_user['username']} 获取操作日志统计")
        
        service = get_operation_log_service()
        stats = await service.get_stats(days)
        
        return OperationLogStatsResponse(
            success=True,
            data=stats,
            message="获取操作日志统计成功"
        )
        
    except Exception as e:
        logger.error(f"获取操作日志统计失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=safe_error_message(e, "获取操作日志统计失败")
        )


@router.post("/clear", response_model=ClearLogsResponse)
async def clear_operation_logs(
    request: ClearLogsRequest,
    current_user: dict = Depends(require_admin)
):
    """清空操作日志"""
    try:
        logger.info(f"🗑️ 用户 {current_user['username']} 清空操作日志")

        service = get_operation_log_service()
        result = await service.clear_logs(
            days=request.days,
            action_type=request.action_type
        )

        message = f"清空操作日志成功，删除了 {result['deleted_count']} 条记录"
        if request.days:
            message += f"（{request.days}天前的日志）"
        if request.action_type:
            message += f"（类型: {request.action_type}）"

        return ClearLogsResponse(
            success=True,
            data=result,
            message=message
        )

    except Exception as e:
        logger.error(f"清空操作日志失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=safe_error_message(e, "清空操作日志失败")
        )


@router.get("/export/csv")
async def export_logs_csv(
    start_date: str = Query(None, description="开始日期"),
    end_date: str = Query(None, description="结束日期"),
    action_type: str = Query(None, description="操作类型"),
    current_user: dict = Depends(get_current_user)
):
    """导出操作日志为CSV"""
    try:
        logger.info(f"📤 用户 {current_user['username']} 导出操作日志CSV")
        
        service = get_operation_log_service()
        logs = await service.get_all_for_export(
            start_date=start_date,
            end_date=end_date,
            action_type=action_type,
        )
        
        # 生成CSV内容
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # 写入表头
        writer.writerow([
            "时间", "用户", "操作类型", "操作内容", "状态", "耗时(ms)", "IP地址", "错误信息"
        ])
        
        # 写入数据
        for log in logs:
            writer.writerow([
                log.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                log.username,
                log.action_type,
                log.action,
                "成功" if log.success else "失败",
                log.duration_ms or "",
                log.ip_address or "",
                log.error_message or ""
            ])
        
        output.seek(0)
        
        # 返回CSV文件
        filename = f"operation_logs_{format_date_compact(now_config_tz())}_{now_config_tz().strftime('%H%M%S')}.csv"
        
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode('utf-8-sig')),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except Exception as e:
        logger.error(f"导出操作日志CSV失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=safe_error_message(e, "导出操作日志CSV失败")
        )
