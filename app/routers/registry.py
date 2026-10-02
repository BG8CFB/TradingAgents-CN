"""智能体身份注册表接口（显示名单单一来源）。

前端 agentDisplayNames.ts 经本接口获取全部展示键 → 中文名映射，
不得在前端本地构建别名表或写死智能体名称。
"""

from fastapi import APIRouter, Depends

from app.engine.orchestrator.registry import all_display_keys
from app.routers.auth_db import get_current_user

router = APIRouter(prefix="/api/registry", tags=["Registry"])


@router.get("/display-names")
async def get_display_names(user: dict = Depends(get_current_user)) -> dict:
    """全部展示键 → 中文名（slug / internal_key / 报告键含历史别名 / event_key）。

    键集合 = 前端各页面消费的全部形态（slug、内部键、{base}_report、{base}_analyst、
    trader 3 别名与 judge 2 别名等），值为 YAML 配置中文名。
    """
    return {"success": True, "data": all_display_keys()}
