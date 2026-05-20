"""
数据层统一错误码定义

错误码范围 1001-1099，命名规则 DATA_{DOMAIN}_{REASON}。
与 HTTP status code（存在 response.code 中）独立，
通过 response.data_code 字段传递给前端。
"""

from enum import IntEnum
from typing import Dict, Optional


class DataErrorCode(IntEnum):
    """数据层业务错误码"""

    # ── 按需刷新相关 ──
    REFRESH_COOLDOWN = 1001       # 冷却期内，跳过刷新
    REFRESH_TIMEOUT = 1002        # 刷新超时（默认 30 秒）
    REFRESH_LOCK_FAILED = 1003    # 获取分布式锁失败

    # ── 数据源相关 ──
    SOURCE_ALL_FAILED = 1010      # 所有候选数据源不可用
    CIRCUIT_OPEN = 1011           # 数据源+域 熔断器处于 Open 状态
    SOURCE_UNAVAILABLE = 1012     # 数据源未配置或已禁用
    SOURCE_RATE_LIMITED = 1013    # 数据源返回 429 限流
    SOURCE_AUTH_FAILED = 1014     # 数据源认证失败（403 / Token 过期）
    SOURCE_SERVER_ERROR = 1015    # 数据源返回 5xx 服务器错误
    SOURCE_DATA_INVALID = 1016    # 数据源返回数据格式异常

    # ── 校验相关 ──
    VALIDATION_FAILED = 1020      # 写入前校验不通过
    VALIDATION_MISSING_FIELD = 1021  # 必填字段缺失
    VALIDATION_TYPE_ERROR = 1022    # 字段类型错误
    VALIDATION_RANGE_ERROR = 1023   # 字段值超范围

    # ── 同步相关 ──
    SYNC_CHECKPOINT_ERR = 1030    # 检查点不一致
    SYNC_ALREADY_RUNNING = 1031   # 同步任务已在运行
    SYNC_DOMAIN_NOT_FOUND = 1032  # 未知数据域
    SYNC_NO_TRADEDAY = 1033       # 非交易日，跳过

    # ── 迁移相关 ──
    MIGRATION_REQUIRED = 1040     # 集合 Schema 版本不匹配


# 错误码 → 中文消息映射
_DATA_ERROR_MESSAGES: Dict[int, str] = {
    DataErrorCode.REFRESH_COOLDOWN: "数据冷却期内，跳过刷新",
    DataErrorCode.REFRESH_TIMEOUT: "数据刷新超时",
    DataErrorCode.REFRESH_LOCK_FAILED: "获取刷新锁失败",
    DataErrorCode.SOURCE_ALL_FAILED: "所有数据源不可用",
    DataErrorCode.CIRCUIT_OPEN: "熔断器已打开，该数据源暂不可用",
    DataErrorCode.SOURCE_UNAVAILABLE: "数据源未配置或已禁用",
    DataErrorCode.SOURCE_RATE_LIMITED: "数据源请求被限流",
    DataErrorCode.SOURCE_AUTH_FAILED: "数据源认证失败",
    DataErrorCode.SOURCE_SERVER_ERROR: "数据源服务器错误",
    DataErrorCode.SOURCE_DATA_INVALID: "数据源返回数据格式异常",
    DataErrorCode.VALIDATION_FAILED: "数据校验失败",
    DataErrorCode.VALIDATION_MISSING_FIELD: "必填字段缺失",
    DataErrorCode.VALIDATION_TYPE_ERROR: "字段类型错误",
    DataErrorCode.VALIDATION_RANGE_ERROR: "字段值超范围",
    DataErrorCode.SYNC_CHECKPOINT_ERR: "同步检查点不一致",
    DataErrorCode.SYNC_ALREADY_RUNNING: "同步任务已在运行中",
    DataErrorCode.SYNC_DOMAIN_NOT_FOUND: "指定的数据域不存在",
    DataErrorCode.SYNC_NO_TRADEDAY: "非交易日，跳过同步",
    DataErrorCode.MIGRATION_REQUIRED: "集合需要数据迁移",
}


def data_error_message(code: DataErrorCode) -> str:
    """获取错误码的中文消息"""
    return _DATA_ERROR_MESSAGES.get(code, f"未知数据错误 ({code})")


def data_fail(
    data_code: DataErrorCode,
    message: Optional[str] = None,
    data: object = None,
    http_code: int = 200,
) -> dict:
    """
    构造带 data_code 的失败响应。

    与 app.core.response.fail() 兼容，额外增加 data_code 字段。
    http_code 默认 200，因为业务错误不等于 HTTP 错误。
    """
    from app.core.response import fail

    resp = fail(
        message=message or data_error_message(data_code),
        code=http_code,
        data=data,
    )
    resp["data_code"] = int(data_code)
    return resp
