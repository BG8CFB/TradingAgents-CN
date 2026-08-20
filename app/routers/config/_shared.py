"""
配置路由共享辅助函数

提取 llm.py 和 system.py 中重复的辅助逻辑，避免独立维护两份。
"""

import logging

logger = logging.getLogger(__name__)


def sanitize_llm_configs(items):
    """脱敏 LLM 配置中的 API Key（置 None）。"""
    try:
        from app.models.config import LLMConfig
        return [LLMConfig(**{**i.model_dump(), "api_key": None}) for i in items]
    except Exception as e:
        logger.debug(f"LLM 配置脱敏失败: {e}")
        return items


def sanitize_datasource_configs(items):
    """
    脱敏数据源配置，返回缩略的 API Key / API Secret。

    API Key 和 API Secret 仅从数据库读取，此处对返回给前端的数据进行缩略处理。
    """
    try:
        from app.utils.api_key_utils import truncate_api_key
        from app.models.config import DataSourceConfig

        result = []
        for item in items:
            data = item.model_dump()

            db_key = data.get("api_key")
            data["api_key"] = truncate_api_key(db_key) if db_key else None

            db_secret = data.get("api_secret")
            data["api_secret"] = truncate_api_key(db_secret) if db_secret else None

            result.append(DataSourceConfig(**data))

        return result
    except Exception as e:
        logger.warning(f"脱敏数据源配置失败: {e}")
        return items
