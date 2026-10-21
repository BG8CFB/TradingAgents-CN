"""QMT 数据源配置解析 — Mongo system_configs 优先、ENV 回退（PRD D-4）。

解析链与 ``app/utils/ds_key_utils.get_datasource_api_key`` 同构：
① Web UI 数据源管理页保存的 qmt 配置（``system_configs.data_source_configs``
   中 ``type=="qmt"`` 项的 ``config_params``，如 ``{"datadir": "...", ...}``）
② ``QMT_*`` 环境变量（经 ``app.core.env.get_env``：os.environ → Settings → 默认值）
③ 均未配置返回空 —— 上层（QmtProvider/健康探针）据此判定「未启用」而非报错
"""

import logging
import time
from typing import Optional

logger = logging.getLogger("sources.CN.qmt.config")

# config_params 键 → 环境变量回退链
_ENV_FALLBACK = {
    "datadir": "QMT_DATADIR",
    "tick_retention_days": "QMT_TICK_RETENTION_DAYS",
}

# Web 配置的进程内短缓存。
# 动机（DD-01）：解析链用的是**同步** pymongo 调用，而 ``get_qmt_datadir()`` 在
# ``QmtProvider.__init__`` / ``QmtHealthProbe.__init__`` 里被 async 路径调用
# （router 每次 fetch 都新建 provider）→ 不缓存等于每次请求都阻塞事件循环一次。
# 30s 与平台「优先级配置 30 秒生效」的既有口径对齐：改配置后最多 30s 生效。
_WEB_CACHE_TTL_SECONDS = 30.0
_web_cache: Optional[tuple] = None


def _web_config_params() -> dict:
    """读取 Web UI 保存的 qmt 数据源配置（system_configs 最新激活版本，30s 缓存）。"""
    global _web_cache
    now = time.monotonic()
    if _web_cache is not None:
        cached, ts = _web_cache
        if now - ts < _WEB_CACHE_TTL_SECONDS:
            return cached
    params = _load_web_config_params()
    _web_cache = (params, now)
    return params


def _load_web_config_params() -> dict:
    """真实读取（未命中缓存时执行）。"""
    try:
        from app.core.database import get_mongo_db_sync

        db = get_mongo_db_sync()
        doc = db.system_configs.find_one({"is_active": True}, sort=[("version", -1)])
        if not doc:
            return {}
        for ds in doc.get("data_source_configs") or []:
            ds_type = ds.get("type", "")
            if isinstance(ds_type, dict):
                ds_type = ds_type.get("value", "")
            if str(ds_type).lower() != "qmt":
                continue
            params = ds.get("config_params") or {}
            return params if isinstance(params, dict) else {}
    except Exception as e:  # DB 不可达时静默回退 ENV（与 ds_key_utils 同策略）
        logger.debug(f"读取 qmt Web 配置失败（回退 ENV）: {e}")
    return {}


def get_qmt_config_param(key: str) -> Optional[str]:
    """单个配置项：Web UI config_params 优先，ENV 回退。"""
    params = _web_config_params()
    val = params.get(key)
    if isinstance(val, str) and val.strip() and not val.startswith("your_"):
        return val.strip()
    try:
        from app.core.env import get_env

        env_val = get_env(_ENV_FALLBACK.get(key, f"QMT_{key.upper()}"))
        if env_val and env_val.strip():
            return env_val.strip()
    except Exception as e:
        logger.debug(f"读取环境变量 {key} 回退失败: {e}")
    return None


def get_qmt_datadir() -> str:
    """datadir 根路径；未配置返回空串（= 数据源未启用）。"""
    return get_qmt_config_param("datadir") or ""


def get_qmt_tick_retention_days() -> Optional[int]:
    """tick 保留天数（M2 清理任务用）；未配置/非法返回 None。"""
    val = get_qmt_config_param("tick_retention_days")
    try:
        return int(val) if val else None
    except ValueError:
        return None
