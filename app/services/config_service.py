"""
向后兼容模块 — 委托到 app.services.config 包

原有的 ConfigService 类已被拆分为 5 个子服务文件：
- app/services/config/market_service.py
- app/services/config/data_source_service.py
- app/services/config/system_service.py
- app/services/config/database_service.py
- app/services/config/llm_service.py

本文件仅做 re-export，保持 `from app.services.config_service import config_service` 不变。
"""

from app.services.config import config_service, ConfigServiceFacade  # noqa: F401

__all__ = ['config_service', 'ConfigServiceFacade']
