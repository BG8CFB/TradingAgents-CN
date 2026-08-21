"""
MCP 配置多格式导入归一化

支持识别并归一化多种客户端的 MCP 配置 JSON：
- claude-desktop：标准 {"mcpServers": {...}} 格式
- cline：mcpServers + Cline 特有字段（fromGalleryId / alwaysAllow / autoApprove / disabled）
- kilo：type:"sse"、cwd 等变体
- bare-server：顶层即单服务器对象（含 command 或 url），自动包装命名

归一化结果过 MCPServerConfig Pydantic 校验；导入为 dry-run，不落盘。
丢弃的非标字段以 warnings 回显前端（区别于 sanitized() 的静默丢弃）。
"""

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import logging

from app.llm.mcp.config import expand_env
from app.llm.mcp.management.config_store import MCPServerConfig

logger = logging.getLogger(__name__)

# 已知包装键（mcpServers 标准键 + 各客户端变体）
_WRAPPER_KEYS = ("mcpServers", "servers")

# 各客户端特有字段 → 丢弃说明
_CLINE_DROP_FIELDS = {
    "fromGalleryId": "Cline 内部标识",
    "alwaysAllow": "工具免确认白名单（本项目 MCP 工具执行无确认环节，语义不适用）",
    "autoApprove": "工具自动批准策略（本项目 MCP 工具执行无确认环节，语义不适用）",
}
_KILO_DROP_FIELDS = {
    "cwd": "工作目录（stdio 传输不支持，且安全上不允许任意 cwd；请用 args 传绝对路径替代）",
}

# 归一化时直接映射的标准字段
_STANDARD_FIELDS = ("type", "command", "args", "env", "url", "headers", "description", "healthCheck", "deps")


class ImportFormat(str, Enum):
    CLAUDE_DESKTOP = "claude-desktop"
    CLINE = "cline"
    KILO = "kilo"
    BARE_SERVER = "bare-server"


@dataclass
class ImportInsight:
    format: ImportFormat
    servers: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # 已过校验的归一化配置
    warnings: List[str] = field(default_factory=list)                  # 丢弃字段回显
    errors: Dict[str, str] = field(default_factory=dict)               # name → 失败原因（不阻断整体）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "format": self.format.value,
            "servers": self.servers,
            "warnings": self.warnings,
            "errors": self.errors,
        }


def _looks_like_server_spec(obj: Any) -> bool:
    """判断对象是否是单服务器配置特征（含 command 或 url）"""
    return isinstance(obj, dict) and ("command" in obj or "url" in obj)


def _detect_sub_format(servers: Dict[str, Any]) -> ImportFormat:
    """按服务器字段特征细分 cline / kilo / claude-desktop"""
    has_cline = any(
        isinstance(spec, dict) and any(k in spec for k in _CLINE_DROP_FIELDS)
        for spec in servers.values()
    )
    if has_cline:
        return ImportFormat.CLINE
    has_kilo = any(
        isinstance(spec, dict) and (spec.get("type") == "sse" or "cwd" in spec)
        for spec in servers.values()
    )
    if has_kilo:
        return ImportFormat.KILO
    return ImportFormat.CLAUDE_DESKTOP


def detect_format(raw: Dict[str, Any]) -> ImportFormat:
    """识别顶层 JSON 的配置格式"""
    for key in _WRAPPER_KEYS:
        if isinstance(raw.get(key), dict) and raw[key]:
            return _detect_sub_format(raw[key])
    if _looks_like_server_spec(raw):
        return ImportFormat.BARE_SERVER
    raise ValueError("无法识别的配置格式：需要 mcpServers 包装或含 command/url 的单服务器对象")


def _normalize_type(spec: Dict[str, Any]) -> Optional[str]:
    """推导归一化服务器类型；无法推导返回 None"""
    stype = spec.get("type")
    if isinstance(stype, str) and stype.strip():
        return stype.strip()
    if spec.get("command"):
        return "stdio"
    if spec.get("url"):
        return "streamable-http"
    return None


def _bare_server_name(spec: Dict[str, Any], raw_keys: List[str]) -> str:
    """为裸服务器对象生成名字：优先 command 尾段，其次 url host，最后 fallback"""
    command = spec.get("command")
    if isinstance(command, str) and command.strip():
        name = command.strip().rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        # python -m xxx 场景取模块名
        args = spec.get("args") or []
        if name.startswith("python") and args:
            for i, a in enumerate(args):
                if a == "-m" and i + 1 < len(args):
                    name = args[i + 1].rsplit(".", 1)[-1]
                    break
        if name:
            return name
    url = spec.get("url")
    if isinstance(url, str):
        host = urlparse(url).hostname
        if host:
            return host
    return raw_keys[0] if raw_keys else "mcp-server"


def normalize_server(name: str, spec: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """
    归一化单个服务器配置为 MCPServerConfig 兼容 dict。

    Returns:
        (normalized_dict, warnings)；校验失败时 normalized_dict 为 None（由调用方收集 errors）
    """
    warnings: List[str] = []

    stype = _normalize_type(spec)
    if stype is None:
        raise ValueError("缺少 command/url，无法推导服务器类型")

    normalized: Dict[str, Any] = {"type": stype}
    for key in _STANDARD_FIELDS:
        if key == "type":
            continue
        if key in spec and spec[key] is not None:
            normalized[key] = spec[key]

    # env/headers 值过 ${VAR} 展开
    for key in ("env", "headers"):
        if key in normalized and isinstance(normalized[key], dict):
            normalized[key] = {k: expand_env(str(v)) for k, v in normalized[key].items()}

    # Cline disabled → _enabled
    if spec.get("disabled"):
        normalized["_enabled"] = False

    # 显式回显丢弃字段
    for field_name, reason in {**_CLINE_DROP_FIELDS, **_KILO_DROP_FIELDS}.items():
        if field_name in spec:
            warnings.append(f"[{name}] 已丢弃字段 '{field_name}'：{reason}")

    # 未知字段（非标准、非已知丢弃项）也提示
    known = set(_STANDARD_FIELDS) | set(_CLINE_DROP_FIELDS) | set(_KILO_DROP_FIELDS) | {"disabled"}
    for key in spec:
        if key not in known:
            warnings.append(f"[{name}] 已丢弃未知字段 '{key}'（不支持的配置项）")

    # 过 Pydantic 校验（不合法即抛 ValueError）
    try:
        model = MCPServerConfig(**normalized)
    except Exception as exc:
        raise ValueError(str(exc)) from exc
    return model.sanitized(), warnings


def normalize_import(raw: Dict[str, Any]) -> ImportInsight:
    """
    识别格式并归一化全部服务器。单个服务器失败不阻断整体（收集到 errors）。
    """
    fmt = detect_format(raw)

    if fmt == ImportFormat.BARE_SERVER:
        servers_map = {_bare_server_name(raw, list(raw.keys())): raw}
    else:
        for key in _WRAPPER_KEYS:
            if isinstance(raw.get(key), dict) and raw[key]:
                servers_map = raw[key]
                break

    insight = ImportInsight(format=fmt)
    for name, spec in servers_map.items():
        if not isinstance(spec, dict):
            insight.errors[str(name)] = "服务器配置必须是对象"
            continue
        try:
            normalized, warns = normalize_server(str(name), spec)
            insight.servers[str(name)] = normalized
            insight.warnings.extend(warns)
        except ValueError as exc:
            insight.errors[str(name)] = str(exc)
            logger.warning("[MCP][import] 服务器 '%s' 归一化失败: %s", name, exc)

    if not insight.servers and not insight.errors:
        raise ValueError("导入内容不含任何服务器配置")
    return insight


def normalize_import_raw(raw_text: str) -> ImportInsight:
    """解析 JSON 字符串并归一化；JSON 错误抛 ValueError 带定位信息"""
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败（第 {exc.lineno} 行第 {exc.colno} 列）: {exc.msg}") from exc
    if not isinstance(raw, dict):
        raise ValueError("顶层必须是 JSON 对象")
    return normalize_import(raw)
