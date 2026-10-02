
import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from app.routers.auth_db import get_current_user
from app.core.response import ok, safe_error_message

from app.services.enhanced_screening_service import get_enhanced_screening_service
from app.services.screening.strategy_service import StrategyService
from app.services.screening.insight_service import (
    ScreeningInsightService, QuotaExceededError,
)
from app.data.schema.domains.factor_scores import FACTOR_FIELDS
from app.models.screening import (
    ScreeningCondition, FieldInfo, BASIC_FIELDS_INFO
)

router = APIRouter(prefix="/api/screening", tags=["Screening"])
logger = logging.getLogger(__name__)

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
    strategy_id: Optional[str] = Field(None, description="策略模板 id；传入时走 L0 因子策略路径")
    conditions: Dict[str, Any] = Field(default_factory=dict)
    order_by: Optional[List[OrderByItem]] = None
    limit: int = Field(50, ge=1, le=500)
    offset: int = Field(0, ge=0)

class ScreeningResponse(BaseModel):
    total: int
    items: List[dict]

class InsightRequest(BaseModel):
    """L1 手动研判请求：只传 symbols，因子由服务端从 factor_scores 重取。"""
    symbols: List[str] = Field(..., min_length=1, max_length=30)
    strategy_id: Optional[str] = None
    conditions_digest: Optional[str] = Field(None, max_length=200,
                                             description="触发筛选条件摘要，仅审计用")


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
        # 策略路径：L0 因子策略模板（0 token，读 stock_factor_scores 过滤+排序）
        if req.strategy_id:
            svc = StrategyService()
            extra = _convert_legacy_conditions_to_new_format(req.conditions)
            extra = [{"field": c.field, "op": c.operator, "value": c.value}
                     for c in extra]
            # 叠加条件白名单：只允许因子字段 + industry，防任意字段过滤
            allowed = set(FACTOR_FIELDS) | {"industry"}
            extra = [c for c in extra if c["field"] in allowed]
            result = await svc.run_strategy(req.strategy_id,
                                            extra_conditions=extra or None,
                                            limit=req.limit)
            return ok({
                "total": result["total"],
                "items": result["items"],
                "as_of": result["as_of"],
                "strategy": result["strategy"],
                "style": result["style"],
            })

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


@router.get("/strategies")
async def list_strategies(user: dict = Depends(get_current_user)):
    """策略模板列表（YAML 驱动，0 token）。"""
    try:
        return ok({"strategies": await StrategyService().list_strategies()})
    except Exception as e:
        logger.error(f"[list_strategies] 获取策略列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=safe_error_message(e, "获取策略列表失败"))


@router.get("/daily")
async def get_daily_recommendations(
    strategy_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    """每日推荐（读落库结果，0 token）。返回最新交易日全部/指定策略。"""
    try:
        return ok(await StrategyService().get_daily(strategy_id))
    except Exception as e:
        logger.error(f"[get_daily_recommendations] 获取每日推荐失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=safe_error_message(e, "获取每日推荐失败"))


@router.post("/insights")
async def generate_insights(req: InsightRequest, user: dict = Depends(get_current_user)):
    """L1 手动快速研判（单次 LLM 调用，按用户日配额限制）。

    429=配额用完；400=入参/因子数据问题；500=LLM 调用等内部失败（已落失败审计）。
    """
    svc = ScreeningInsightService()
    try:
        result = await svc.generate_manual(
            symbols=req.symbols, user_id=str(user["id"]),
            strategy_id=req.strategy_id,
            conditions_digest=req.conditions_digest)
        return ok(result)
    except QuotaExceededError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[generate_insights] 研判失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=safe_error_message(e, "研判生成失败"))


@router.get("/insights/quota")
async def get_insight_quota(user: dict = Depends(get_current_user)):
    """当前用户今日手动研判剩余配额（0 token，供前端按钮态展示）。"""
    try:
        return ok({"quota_remaining":
                   await ScreeningInsightService().quota_remaining(str(user["id"]))})
    except Exception as e:
        logger.error(f"[get_insight_quota] 查询配额失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=safe_error_message(e, "查询配额失败"))


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
