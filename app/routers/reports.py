"""
分析报告管理API路由
"""
import json
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .auth_db import get_current_user
from ..services.reports_service import get_reports_service
from ..utils.timezone import now_config_tz, format_date_short
from ..core.response import safe_error_message
import logging

logger = logging.getLogger("webapi")

router = APIRouter(prefix="/api/reports", tags=["Reports"])

class ReportFilter(BaseModel):
    """报告筛选参数"""
    search_keyword: Optional[str] = None
    market_filter: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    stock_code: Optional[str] = None
    report_type: Optional[str] = None

class ReportListResponse(BaseModel):
    """报告列表响应"""
    reports: List[Dict[str, Any]]
    total: int
    page: int
    page_size: int

@router.get("/list", response_model=Dict[str, Any])
async def get_reports_list(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    search_keyword: Optional[str] = Query(None, description="搜索关键词"),
    market_filter: Optional[str] = Query(None, description="市场筛选（A股/港股/美股）"),
    start_date: Optional[str] = Query(None, description="开始日期"),
    end_date: Optional[str] = Query(None, description="结束日期"),
    stock_code: Optional[str] = Query(None, description="股票代码"),
    user: dict = Depends(get_current_user)
):
    """获取分析报告列表"""
    try:
        logger.info(f"获取报告列表: 用户={user['id']}, 页码={page}, 每页={page_size}, 市场={market_filter}")

        service = get_reports_service()
        filters = {
            "search_keyword": search_keyword,
            "market_filter": market_filter,
            "start_date": start_date,
            "end_date": end_date,
            "stock_code": stock_code,
        }

        result = await service.list_reports(
            filters=filters,
            page=page,
            page_size=page_size,
            user_id=user["id"],
        )

        logger.info(f"查询完成: 总数={result['total']}, 返回={len(result['reports'])}")

        return {
            "success": True,
            "data": result,
            "message": "报告列表获取成功"
        }

    except Exception as e:
        logger.error(f"获取报告列表失败: {e}")
        raise HTTPException(status_code=500, detail=safe_error_message(e, "操作失败"))

@router.get("/{report_id}/detail")
async def get_report_detail(
    report_id: str,
    user: dict = Depends(get_current_user)
):
    """获取报告详情"""
    try:
        logger.info(f"获取报告详情: {report_id}")

        service = get_reports_service()
        report = await service.get_report(report_id)

        if not report:
            raise HTTPException(status_code=404, detail="报告不存在")

        report_user_id = str(report.get("user_id", ""))
        if report_user_id and str(user.get("id", "")) != report_user_id:
            raise HTTPException(status_code=403, detail="无权访问该报告")

        return {
            "success": True,
            "data": report,
            "message": "报告详情获取成功"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取报告详情失败: {e}")
        raise HTTPException(status_code=500, detail=safe_error_message(e, "操作失败"))

@router.delete("/{report_id}")
async def delete_report(
    report_id: str,
    user: dict = Depends(get_current_user)
):
    """删除报告"""
    try:
        logger.info(f"删除报告: {report_id}")

        service = get_reports_service()
        deleted = await service.delete_report(report_id, user_id=user["id"])

        if not deleted:
            raise HTTPException(status_code=404, detail="报告不存在")

        logger.info(f"报告删除成功: {report_id}")

        return {
            "success": True,
            "message": "报告删除成功"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除报告失败: {e}")
        raise HTTPException(status_code=500, detail=safe_error_message(e, "操作失败"))

@router.get("/{report_id}/download")
async def download_report(
    report_id: str,
    format: str = Query("markdown", description="下载格式: markdown, json, pdf, docx"),
    user: dict = Depends(get_current_user)
):
    """下载报告

    支持的格式:
    - markdown: Markdown 格式（默认）
    - json: JSON 格式（包含完整数据）
    - docx: Word 文档格式（需要 pandoc）
    - pdf: PDF 格式（需要 pandoc 和 PDF 引擎）
    """
    try:
        logger.info(f"下载报告: {report_id}, 格式: {format}")

        service = get_reports_service()
        doc = await service.download_report(report_id)

        if not doc:
            raise HTTPException(status_code=404, detail="报告不存在")

        report_user_id = str(doc.get("user_id", ""))
        if report_user_id and str(user.get("id", "")) != report_user_id:
            raise HTTPException(status_code=403, detail="无权访问该报告")

        stock_symbol = doc.get("stock_symbol", "unknown")
        analysis_date = doc.get("analysis_date", format_date_short(now_config_tz()))

        if format == "json":
            # JSON格式下载
            content = json.dumps(doc, ensure_ascii=False, indent=2, default=str)
            filename = f"{stock_symbol}_{analysis_date}_report.json"
            media_type = "application/json"

            # 返回文件流
            def generate():
                yield content.encode('utf-8')

            return StreamingResponse(
                generate(),
                media_type=media_type,
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )

        elif format == "markdown":
            # Markdown格式下载
            reports = doc.get("reports", {})
            content_parts = []

            # 添加标题
            content_parts.append(f"# {stock_symbol} 分析报告")
            content_parts.append(f"**分析日期**: {analysis_date}")
            content_parts.append(f"**分析师**: {', '.join(doc.get('analysts', []))}")
            content_parts.append("")

            # 添加摘要
            if doc.get("summary"):
                content_parts.append("## 执行摘要")
                content_parts.append(doc["summary"])
                content_parts.append("")

            # 添加各模块内容
            for module_name, module_content in reports.items():
                if isinstance(module_content, str) and module_content.strip():
                    content_parts.append(f"## {module_name}")
                    content_parts.append(module_content)
                    content_parts.append("")

            content = "\n".join(content_parts)
            filename = f"{stock_symbol}_{analysis_date}_report.md"
            media_type = "text/markdown"

            # 返回文件流
            def generate():
                yield content.encode('utf-8')

            return StreamingResponse(
                generate(),
                media_type=media_type,
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )

        elif format == "docx":
            # Word 文档格式下载
            from app.utils.report_exporter import report_exporter

            if not report_exporter.pandoc_available:
                raise HTTPException(
                    status_code=400,
                    detail="Word 导出功能不可用。请安装 pandoc: pip install pypandoc"
                )

            try:
                # 生成 Word 文档
                docx_content = report_exporter.generate_docx_report(doc)
                filename = f"{stock_symbol}_{analysis_date}_report.docx"

                # 返回文件流
                def generate():
                    yield docx_content

                return StreamingResponse(
                    generate(),
                    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f"attachment; filename={filename}"}
                )
            except Exception as e:
                logger.error(f"Word 文档生成失败: {e}")
                raise HTTPException(status_code=500, detail=safe_error_message(e, "Word 文档生成失败"))

        elif format == "pdf":
            # PDF 格式下载
            from app.utils.report_exporter import report_exporter

            if not report_exporter.pandoc_available:
                raise HTTPException(
                    status_code=400,
                    detail="PDF 导出功能不可用。请安装 pandoc 和 PDF 引擎（wkhtmltopdf 或 LaTeX）"
                )

            try:
                # 生成 PDF 文档
                pdf_content = report_exporter.generate_pdf_report(doc)
                filename = f"{stock_symbol}_{analysis_date}_report.pdf"

                # 返回文件流
                def generate():
                    yield pdf_content

                return StreamingResponse(
                    generate(),
                    media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename={filename}"}
                )
            except Exception as e:
                logger.error(f"PDF 文档生成失败: {e}")
                raise HTTPException(status_code=500, detail=safe_error_message(e, "PDF 文档生成失败"))

        else:
            raise HTTPException(status_code=400, detail=f"不支持的下载格式: {format}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"下载报告失败: {e}")
        raise HTTPException(status_code=500, detail=safe_error_message(e, "操作失败"))
