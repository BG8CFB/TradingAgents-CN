"""
MCP 配置（参考 claude-code 的 mcpServers 配置格式）

config/llm_mcp.json:
{
  "mcpServers": {
    "server-name": {
      "type": "stdio",          // 缺省按有无 command 推断
      "command": "python",
      "args": ["-m", "some_mcp_server"],
      "env": {"KEY": "${ENV_VAR}"}   // ${VAR} 环境变量展开
    },
    "remote-server": {
      "type": "http",
      "url": "https://...",
      "headers": {"Authorization": "Bearer ${TOKEN}"}
    }
  }
}
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from app.utils.logging_init import get_logger

from ..config import project_root

logger = get_logger("app.llm.mcp")

DEFAULT_MCP_CONFIG = "config/llm_mcp.json"

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
    type: str = "stdio"  # stdio | http
    command: Optional[str] = None
    args: list = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    url: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)

    @property
    def cache_key(self) -> str:
        return f"{self.name}:{json.dumps(self.__dict__, sort_keys=True, ensure_ascii=False)}"


def load_mcp_config(config_path: Optional[str] = None) -> Dict[str, MCPServerConfig]:
    """加载 mcpServers 配置；文件不存在时返回空 dict（MCP 为可选能力）"""
    path = Path(config_path) if config_path else project_root() / DEFAULT_MCP_CONFIG
    if not path.is_file():
        logger.info(f"[mcp] 配置不存在，跳过: {path}")
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"⚠️ [mcp] 配置解析失败 {path}: {e}")
        return {}

    servers: Dict[str, MCPServerConfig] = {}
    for name, spec in (raw.get("mcpServers") or {}).items():
        if not isinstance(spec, dict):
            continue
        stype = spec.get("type") or ("http" if "url" in spec else "stdio")
        cfg = MCPServerConfig(
            name=name,
            type=stype,
            command=spec.get("command"),
            args=list(spec.get("args") or []),
            env={k: expand_env(str(v)) for k, v in (spec.get("env") or {}).items()},
            url=spec.get("url"),
            headers={k: expand_env(str(v)) for k, v in (spec.get("headers") or {}).items()},
        )
        if cfg.type == "stdio" and not cfg.command:
            logger.warning(f"⚠️ [mcp] server '{name}' 缺少 command，跳过")
            continue
        if cfg.type == "http" and not cfg.url:
            logger.warning(f"⚠️ [mcp] server '{name}' 缺少 url，跳过")
            continue
        servers[name] = cfg
    if servers:
        logger.info(f"[mcp] 加载 {len(servers)} 个 server 配置: {sorted(servers)}")
    return servers
