"""兼容转发 shim：实现已迁移至 app/services/analysis/ 包（services 拆分 3.7）。

对外 API 面不变，下列符号仍可从本模块导入；新代码请直接
`from app.services.analysis import ...`。本文件保留一个版本后删除。
"""

from app.services.analysis import (
    AnalysisService,
    _DEPRECATED_MODELS,
    _MODEL_API_KEY_PLACEHOLDER,
    _TASK_STATUS_MESSAGES,
    _get_default_backend_url,
    _get_default_provider_by_model,
    _resolve_api_key_sync,
    analysis_service,
    create_analysis_config,
    get_analysis_service,
    get_provider_and_url_by_model_sync,
    get_provider_by_model_name,
    get_provider_by_model_name_sync,
)

__all__ = [
    "AnalysisService",
    "analysis_service",
    "create_analysis_config",
    "get_analysis_service",
    "get_provider_and_url_by_model_sync",
    "get_provider_by_model_name",
    "get_provider_by_model_name_sync",
    "_DEPRECATED_MODELS",
    "_MODEL_API_KEY_PLACEHOLDER",
    "_TASK_STATUS_MESSAGES",
    "_get_default_backend_url",
    "_get_default_provider_by_model",
    "_resolve_api_key_sync",
]
