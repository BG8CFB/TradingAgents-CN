
import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from app.routers.auth_db import get_current_user
from app.core.response import ok, safe_error_message

from app.services.enhanced_screening_service import get_enhanced_screening_service
from app.models.screening import (
    ScreeningCondition, ScreeningRequest as NewScreeningRequest,
    ScreeningResponse as NewScreeningResponse, FieldInfo, BASIC_FIELDS_INFO
)

router = APIRouter(prefix="/api/screening", tags=["Screening"])
logger = logging.getLogger("webapi")

# 筛选字段配置响应模型
class FieldConfigResponse(BaseModel):
    """筛选字段配置响应"""
    fields: Dict[str, FieldInfo]
    categories: Dict[str, List[str]]

# 传统的请求/响应模型（保持向后兼容）
class OrderByItem(BaseModel):
    field: str
    direction: str = Field("desc", pattern=r"^(?i)(asc|desc)$")

class ScreeningRequest(BaseModel):
    market: str = Field("CN", description="市场：CN")
    date: Optional[str] = Field(None, description="交易日YYYY-MM-DD，缺省为最新")
    adj: str = Field("qfq", description="复权口径：qfq/hfq/none（P0占位）")
    conditions: Dict[str, Any] = Field(default_factory=dict)
    order_by: Optional[List[OrderByItem]] = None
    limit: int = Field(50, ge=1, le=500)
    offset: int = Field(0, ge=0)

class ScreeningResponse(BaseModel):
    total: int
    items: List[dict]


def get_enhanced_service():
    """延迟获取增强筛选服务，避免模块导入时实例化。"""
    return get_enhanced_screening_service()


@router.get("/fields")
async def get_screening_fields(user: dict = Depends(get_current_user)):
    """
    获取筛选字段配置
    返回所有可用的筛选字段及其配置信息
    """
    try:
        # 字段分类
        categories = {
            "basic": ["symbol", "name", "industry", "area", "market"],
            "market_value": ["total_mv", "circ_mv"],
            "financial": ["pe", "pb", "pe_ttm", "pb_mrq", "roe"],
            "trading": ["turnover_rate", "volume_ratio"],
            "price": ["close", "pct_chg", "amount"],
            "technical": ["ma20", "rsi14", "kdj_k", "kdj_d", "kdj_j", "dif", "dea", "macd_hist"]
        }

        return ok(FieldConfigResponse(
            fields=BASIC_FIELDS_INFO,
            categories=categories
        ).model_dump(mode='json'))

    except Exception as e:
        logger.error(f"[get_screening_fields] 获取字段配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=safe_error_message(e, "获取字段配置失败"))


def _convert_legacy_conditions_to_new_format(legacy_conditions: Dict[str, Any]) -> List[ScreeningCondition]:
    """
    将传统格式的筛选条件转换为新格式

    传统格式示例:
    {
        "logic": "AND",
        "children": [
            {"field": "market_cap", "op": "between", "value": [5000000, 9007199254740991]}
        ]
    }

    新格式:
    [
        ScreeningCondition(field="total_mv", operator="between", value=[50, 90071992547])
    ]
    """
    conditions = []

    # 字段名映射（前端可能使用的旧字段名 -> 统一的后端字段名）
    field_mapping = {
        "market_cap": "total_mv",      # 市值（兼容旧字段名）
        "pe_ratio": "pe",              # 市盈率（兼容旧字段名）
        "pb_ratio": "pb",              # 市净率（兼容旧字段名）
        "turnover": "turnover_rate",   # 换手率（兼容旧字段名）
        "change_percent": "pct_chg",   # 涨跌幅（兼容旧字段名）
        "price": "close",              # 价格（兼容旧字段名）
    }

    # 操作符映射
    operator_mapping = {
        "between": "between",
        "gt": ">",
        "lt": "<",
        "gte": ">=",
        "lte": "<=",
        "eq": "==",
        "ne": "!=",
        "in": "in",
        "contains": "contains"
    }

    if isinstance(legacy_conditions, dict):
        children = legacy_conditions.get("children", [])

        for child in children:
            if isinstance(child, dict):
                field = child.get("field")
                op = child.get("op")
                value = child.get("value")

                if field and op and value is not None:
                    # 映射字段名
                    mapped_field = field_mapping.get(field, field)

                    # 映射操作符
                    mapped_op = operator_mapping.get(op, op)

                    # 市值单位转换：前端协议约定传入万元，后端数据库存储亿元
                    # 若前端协议变更，此处需同步调整
                    if mapped_field == "total_mv" and isinstance(value, list):
                        # 将万元转换为亿元
                        converted_value = [v / 10000 for v in value if isinstance(v, (int, float))]
                        logger.info(f"[screening] 市值单位转换: {value} 万元 -> {converted_value} 亿元")
                        value = converted_value
                    elif mapped_field == "total_mv" and isinstance(value, (int, float)):
                        value = value / 10000
                        logger.info(f"[screening] 市值单位转换: {child.get('value')} 万元 -> {value} 亿元")

                    # 创建筛选条件
                    condition = ScreeningCondition(
                        field=mapped_field,
                        operator=mapped_op,
                        value=value
                    )
                    conditions.append(condition)

                    logger.info(f"[screening] 转换条件: {field}({op}) -> {mapped_field}({mapped_op}), 值: {value}")

    return conditions


# 传统筛选接口（保持向后兼容，但使用增强服务）
@router.post("/run")
async def run_screening(req: ScreeningRequest, user: dict = Depends(get_current_user)):
    try:
        logger.info(f"[screening] 请求条件: {req.conditions}")
        logger.info(f"[screening] 排序与分页: order_by={req.order_by}, limit={req.limit}, offset={req.offset}")

        # 转换传统格式的条件为新格式
        conditions = _convert_legacy_conditions_to_new_format(req.conditions)
        logger.info(f"[screening] 转换后的条件: {conditions}")

        # 使用增强筛选服务
        enhanced_svc = get_enhanced_service()
        result = await enhanced_svc.screen_stocks(
            conditions=conditions,
            market=req.market,
            date=req.date,
            adj=req.adj,
            limit=req.limit,
            offset=req.offset,
            order_by=[{"field": o.field, "direction": o.direction} for o in (req.order_by or [])],
            use_database_optimization=True
        )

        logger.info(f"[screening] 筛选完成: total={result.get('total')}, "
                   f"took={result.get('took_ms')}ms, optimization={result.get('optimization_used')}")

        if result.get('items'):
            sample = result['items'][:3]
            logger.info(f"[screening] 返回样例(前3条): {sample}")

        return ok(ScreeningResponse(total=result["total"], items=result["items"]).model_dump(mode='json'))

    except Exception as e:
        logger.error(f"[screening] 处理失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=safe_error_message(e, "筛选处理失败"))


# 新的优化筛选接口
@router.post("/enhanced")
async def enhanced_screening(req: NewScreeningRequest, user: dict = Depends(get_current_user)):
    """
    增强的股票筛选接口
    - 支持更丰富的筛选条件格式
    - 自动选择最优的筛选策略（数据库优化 vs 传统方法）
    - 提供详细的性能统计信息
    """
    try:
        logger.info(f"[enhanced_screening] 筛选条件: {len(req.conditions)}个")
        logger.info(f"[enhanced_screening] 排序与分页: order_by={req.order_by}, limit={req.limit}, offset={req.offset}")

        # 执行增强筛选
        enhanced_svc = get_enhanced_service()
        result = await enhanced_svc.screen_stocks(
            conditions=req.conditions,
            market=req.market,
            date=req.date,
            adj=req.adj,
            limit=req.limit,
            offset=req.offset,
            order_by=req.order_by,
            use_database_optimization=req.use_database_optimization
        )

        logger.info(f"[enhanced_screening] 筛选完成: total={result.get('total')}, "
                   f"took={result.get('took_ms')}ms, optimization={result.get('optimization_used')}")

        return ok(NewScreeningResponse(
            total=result["total"],
            items=result["items"],
            took_ms=result.get("took_ms"),
            optimization_used=result.get("optimization_used"),
            source=result.get("source")
        ).model_dump(mode='json'))

    except Exception as e:
        logger.error(f"[enhanced_screening] 筛选失败: {e}")
        raise HTTPException(status_code=500, detail=safe_error_message(e, "增强筛选失败"))



# 获取单个字段的详细信息
@router.get("/fields/{field_name}")
async def get_field_info(field_name: str, user: dict = Depends(get_current_user)):
    """获取指定字段的详细信息"""
    try:
        enhanced_svc = get_enhanced_service()
        field_info = await enhanced_svc.get_field_info(field_name)
        if not field_info:
            raise HTTPException(status_code=404, detail=f"字段 '{field_name}' 不存在")
        return ok(field_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[screening] 获取字段信息失败: {e}")
        raise HTTPException(status_code=500, detail=safe_error_message(e, "获取字段信息失败"))


# 验证筛选条件
@router.post("/validate")
async def validate_conditions(conditions: List[ScreeningCondition], user: dict = Depends(get_current_user)):
    """验证筛选条件的有效性"""
    try:
        enhanced_svc = get_enhanced_service()
        validation_result = await enhanced_svc.validate_conditions(conditions)
        return ok(validation_result)
    except Exception as e:
        logger.error(f"[screening] 验证条件失败: {e}")
        raise HTTPException(status_code=500, detail=safe_error_message(e, "验证条件失败"))


@router.get("/industries")
async def get_industries(user: dict = Depends(get_current_user)):
    """
    获取数据库中所有可用的行业列表
    根据系统配置的数据源优先级，从优先级最高的数据源获取行业分类数据
    返回按股票数量排序的行业列表
    """
    try:
        enhanced_svc = get_enhanced_service()
        industry_data = await enhanced_svc.get_industries()

        return ok(industry_data)

    except Exception as e:
        logger.error(f"[get_industries] 获取行业列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=safe_error_message(e, "获取行业列表失败"))
