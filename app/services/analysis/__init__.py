"""分析服务包（原 app/services/analysis_service.py 单文件拆分，services 拆分 3.7）。

对外 API 面不变：全部公共符号经本包 __init__ re-export，旧模块保留为
转发 shim（一个版本后删除）。模块布局：
- providers   LLM 模型配置与 provider 解析 + create_analysis_config
- tasks       任务 CRUD/查询/统计搜索（TasksMixin）
- reports     报告抽取与持久化（ReportsMixin）
- prefetch    数据预取（PrefetchMixin）
- executor    后台执行编排（ExecutorMixin）
- service     AnalysisService 核心类与全局单例
"""

from app.services.analysis.providers import (
    _DEPRECATED_MODELS,
    _MODEL_API_KEY_PLACEHOLDER,
    _get_default_backend_url,
    _get_default_provider_by_model,
    _resolve_api_key_sync,
    create_analysis_config,
    get_provider_and_url_by_model_sync,
    get_provider_by_model_name,
    get_provider_by_model_name_sync,
)
from app.services.analysis.service import (
    AnalysisService,
    analysis_service,
    get_analysis_service,
)
from app.services.analysis.tasks import _TASK_STATUS_MESSAGES

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
