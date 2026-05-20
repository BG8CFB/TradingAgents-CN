"""
Stock basics synchronization service（兼容层）

已迁移到 app.services.multi_source_basics_sync_service，本文件保留 re-export。
新代码请直接使用: from app.services.multi_source_basics_sync_service import get_multi_source_sync_service
"""

from app.services.multi_source_basics_sync_service import (  # noqa: F401
    get_multi_source_sync_service as get_basics_sync_service,
    MultiSourceBasicsSyncService as BasicsSyncService,
)
