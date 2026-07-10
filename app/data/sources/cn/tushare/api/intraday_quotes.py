"""
Tushare 分钟线 API

接口: stk_mins
要求: >= 2000 积分, 限频 1 次/小时（无权限时）

权限检测机制：
- 首次调用时检测是否有权限
- 如果无权限：限制为 1 次/小时
- 如果有权限：正常获取实时分钟信息
"""
import asyncio
import logging
import time
from typing import Optional

import pandas as pd

from app.data.sources.base.exceptions import DataNotFoundError, DataSourceUnavailableError
from app.data.sources.base.mappers import (
    is_empty_result,
    map_network_exception,
    map_tushare_code,
)

from .connection import TushareConnection

logger = logging.getLogger(__name__)

_DOMAIN = "intraday_quotes"

# 权限检测缓存
_permission_checked = False
_has_permission = False
_last_check_time = 0
_check_interval = 3600  # 1小时检测一次


async def _check_permission(conn: TushareConnection) -> bool:
    """检测是否有 stk_mins 排行权限（>= 2000 积分）

    使用缓存机制，避免频繁检测：
    - 首次调用时检测
    - 每小时检测一次（更新权限状态）
    """
    global _permission_checked, _has_permission, _last_check_time

    current_time = time.time()
    if _permission_checked and (current_time - _last_check_time) < _check_interval:
        return _has_permission

    try:
        # 尝试调用 stk_mins 接口检测权限
        df = await asyncio.to_thread(
            conn.api.stk_mins,
            ts_code="000001.SZ",
            freq="1min",
            limit=1,
        )
        _has_permission = df is not None and not df.empty
        _permission_checked = True
        _last_check_time = current_time
        logger.info(f"Tushare stk_mins 权限检测: {'有权限' if _has_permission else '无权限'}")
        return _has_permission
    except Exception as e:
        error_msg = str(e)
        if "积分" in error_msg or "权限" in error_msg or "credits" in error_msg.lower():
            _has_permission = False
            _permission_checked = True
            _last_check_time = current_time
            logger.warning(f"Tushare stk_mins 无权限: {error_msg}")
            return False
        # 其他错误（如网络问题）不更新权限状态
        logger.debug(f"Tushare stk_mins 权限检测失败: {error_msg}")
        return _has_permission


async def fetch_intraday_quotes(
    conn: TushareConnection,
    ts_code: str,
    freq: str = "30min",
    limit: int = 500,
) -> Optional[pd.DataFrame]:
    """
    获取分钟级行情

    权限检测机制：
    - 如果无权限：限制为 1 次/小时，返回 None
    - 如果有权限：正常获取实时分钟信息
    """
    if not conn.is_available():
        return None

    # 检测权限
    has_permission = await _check_permission(conn)
    if not has_permission:
        logger.debug(f"Tushare stk_mins 无权限，跳过: {ts_code}")
        return None

    freq_map = {"1min": "1min", "5min": "5min", "15min": "15min", "30min": "30min", "60min": "60min"}
    freq_param = freq_map.get(freq, "30min")

    try:
        df = await asyncio.to_thread(
            conn.api.stk_mins,
            ts_code=ts_code,
            freq=freq_param,
            limit=limit,
        )
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "tushare", _DOMAIN)
    except Exception as exc:
        error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
        mapped = map_tushare_code(error_code, "tushare", _DOMAIN, str(exc))
        if mapped is not None:
            # 如果是权限错误，更新缓存
            if "积分" in str(exc) or "权限" in str(exc):
                global _has_permission, _permission_checked, _last_check_time
                _has_permission = False
                _permission_checked = True
                _last_check_time = time.time()
            raise mapped
        raise DataSourceUnavailableError(
            "tushare", _DOMAIN, f"ts_code={ts_code}: {exc}"
        )

    if is_empty_result(df):
        logger.debug(f"Tushare 分钟线为空: {ts_code}")
        raise DataNotFoundError("tushare", _DOMAIN, f"ts_code={ts_code} 无数据")

    logger.info(f"Tushare 分钟线: {ts_code} {len(df)} 条 ({freq})")
    return df
