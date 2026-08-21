"""
MCP 运行时轻量配置（参考 claude-code 的 mcpServers 配置格式）

服务器配置的实际存储与校验在 app/llm/mcp/management/config_store.py（config/mcp.json）；
本模块只提供运行时 dataclass 与 ${VAR} 环境变量展开工具。
"""

import json
import re
from dataclasses import dataclass, field
from typing import Dict, Optional

import logging

logger = logging.getLogger("app.llm.mcp")

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def expand_env(value: str) -> str:
    """${VAR} 环境变量展开（未定义的变量保留原样并告警）"""
    import os

    def _sub(m: "re.Match[str]") -> str:
        var = m.group(1)
        val = os.environ.get(var)
        if val is None:
            logger.warning(f"⚠️ [mcp] 环境变量 {var} 未定义，占位符保留原样")
            return m.group(0)
        return val

    return _ENV_PATTERN.sub(_sub, value)


@dataclass
class MCPServerConfig:
    name: str
    type: str = "stdio"  # stdio | http | streamable-http | sse
    command: Optional[str] = None
    args: list = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    url: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)

    @property
    def cache_key(self) -> str:
        return f"{self.name}:{json.dumps(self.__dict__, sort_keys=True, ensure_ascii=False)}"
