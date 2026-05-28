"""
数据源 API Key 工具函数

从数据库 data_source_configs 集合读取数据源 API Key/Token，
数据库未配置时回退到 .env 环境变量。
优先级：DB > .env
"""

from typing import Optional

from app.core.env import get_env
from app.utils.logging_init import get_logger

logger = get_logger("app.ds_key_utils")

# 数据源类型到环境变量名的映射
_DS_ENV_MAP = {
    "tushare": "TUSHARE_TOKEN",
    "tushare_hk": "TUSHARE_TOKEN",
    "tushare_us": "TUSHARE_TOKEN",
    "finnhub": "FINNHUB_API_KEY",
    "alpha_vantage": "ALPHA_VANTAGE_API_KEY",
    "polygon": "POLYGON_API_KEY",
}


def get_datasource_api_key(ds_type: str) -> Optional[str]:
    """获取数据源的 API Key/Token

    优先级：DB data_source_configs > .env 环境变量

    Args:
        ds_type: 数据源类型（如 'tushare', 'finnhub', 'alpha_vantage'）

    Returns:
        API Key 字符串，均未找到则返回 None
    """
    # 1. 从数据库读取
    try:
        from app.core.database import get_mongo_db_sync
        db = get_mongo_db_sync()

        doc = db.system_configs.find_one({"is_active": True}, sort=[("version", -1)])
        if doc and "data_source_configs" in doc:
            for ds in doc["data_source_configs"]:
                ds_type_val = ds.get("type", "")
                if isinstance(ds_type_val, dict):
                    ds_type_val = ds_type_val.get("value", "")
                if str(ds_type_val).lower() == ds_type.lower():
                    key = ds.get("api_key", "")
                    if key and key.strip() and not key.startswith("your_"):
                        return key.strip()
    except Exception as e:
        logger.debug(f"从 DB 读取数据源 {ds_type} API Key 失败: {e}")

    # 2. 回退到 .env 环境变量
    env_key = _DS_ENV_MAP.get(ds_type.lower())
    if env_key:
        val = get_env(env_key)
        if val and val.strip() and not val.startswith("your_"):
            return val.strip()

    return None
