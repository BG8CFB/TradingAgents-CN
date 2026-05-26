"""统一环境变量读取入口。

非白名单模块应使用 get_env() 而非 os.getenv()，
确保所有配置读取都经过 Pydantic Settings 优先级管理。
"""

import os
from typing import Any


def get_env(key: str, default: Any = None) -> Any:
    """统一环境变量读取，优先从 settings 获取。

    Pydantic Settings 中值为空字符串时，视为"未配置"，回退到 os.getenv()。
    这确保通过 os.environ 设置的值能被正确读取，即使 Settings 有空字符串默认值。

    Args:
        key: 环境变量名（也是 settings 属性名）
        default: 找不到时的默认值

    Returns:
        优先返回 settings 中的非空值，否则返回 os.getenv()，最后返回 default。
    """
    try:
        from app.core.config import settings

        val = getattr(settings, key, None)
        if val is not None and val != "":
            return val
    except Exception:
        pass
    return os.getenv(key, default)
