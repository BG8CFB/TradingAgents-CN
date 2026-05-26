"""统一环境变量读取入口。

非白名单模块应使用 get_env() 而非 os.getenv()，
确保所有配置读取都经过 Pydantic Settings 优先级管理。
"""

import os
from typing import Any


def get_env(key: str, default: Any = None) -> Any:
    """统一环境变量读取。

    优先级：os.environ > Pydantic Settings 缓存 > default。

    os.environ 优先确保运行时动态修改（如测试中的 env_vars）能立即生效，
    不被 settings 启动时加载的 .env 缓存覆盖。

    Args:
        key: 环境变量名（也是 settings 属性名）
        default: 找不到时的默认值

    Returns:
        按 os.environ → settings → default 顺序返回首个非空值。
    """
    # 1. os.environ 最高优先——运行时动态设置立即可见
    os_val = os.environ.get(key)
    if os_val is not None and os_val != "":
        return os_val

    # 2. 回退到 Pydantic Settings 缓存（启动时从 .env 加载）
    try:
        from app.core.config import settings

        val = getattr(settings, key, None)
        if val is not None and val != "":
            return val
    except Exception as e:
        pass

    return default
