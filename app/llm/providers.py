"""
模型配置 → 客户端解析（后端"添加模型"配置驱动，双协议通用端点）

- 请求协议（anthropic | openai）在厂家配置（llm_providers.protocol）上填写；
  厂家未填时按厂家名推断（infer_protocol）
- API Key / base_url 解析优先级（与 test_llm_config 语义一致）：
  模型配置自身 > 厂家配置（llm_providers 集合的 api_key / default_base_url）> .env 回退
- providers.py 把启用的模型配置解析为 EngineClientBundle：
  primary（priority 最高）+ fallback（次高，限流连续 3 次时切换，对齐 claude-code
  query.ts 的 fallbackModel 模式）+ 每模型参数（max_tokens/temperature/timeout/retry）
- .env ARK_* 作为回退（数据库不可用/未配置时）
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.utils.logging_init import get_logger

from .config import load_config
from .core.base import BaseLLMClient
from .core.factory import create_client

logger = get_logger("app.llm.providers")

# provider → 默认协议推断（仅 anthropic 原生走 anthropic 协议，其余全部 openai 兼容）
_PROVIDER_PROTOCOL = {
    "anthropic": "anthropic",
    "claude": "anthropic",
    "ark": "anthropic",
    "volcengine": "anthropic",
}
DEFAULT_PROTOCOL = "openai"


@dataclass
class ResolvedProvider:
    protocol: str
    model: str
    api_key: str
    base_url: Optional[str]
    source: str  # "db" | "env"
    # 每模型参数（来自"添加模型"表单，缺省回退协议客户端默认值）
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    timeout: Optional[int] = None
    retry_times: Optional[int] = None
    context_window: Optional[int] = None


@dataclass
class EngineClientBundle:
    """引擎用客户端束：primary + fallback（可选）+ 每模型参数。

    __getattr__ 转发 primary，鸭子类型兼容一切按 BaseLLMClient 使用的地方
    （.model / .chat / .chat_stream / .count_tokens 等）。
    """

    primary: BaseLLMClient
    fallback: Optional[BaseLLMClient] = None
    retry_times: Optional[int] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    context_window: Optional[int] = None
    _meta: Dict[str, Any] = field(default_factory=dict)

    def __getattr__(self, name: str) -> Any:
        # dataclass 字段未命中时转发 primary（仅 __getattr__ 兜底，不影响已有属性）
        return getattr(self.primary, name)

    @classmethod
    def from_client(cls, client: BaseLLMClient) -> "EngineClientBundle":
        """裸 client（任务级 config 覆盖路径）→ 无 fallback 的 bundle"""
        return cls(primary=client)


def infer_protocol(provider: str, protocol: Optional[str] = None) -> str:
    """协议解析：厂家显式 protocol 优先，否则按厂家名推断"""
    if protocol:
        p = protocol.strip().lower()
        if p in ("anthropic", "openai"):
            return p
        logger.warning(f"⚠️ [providers] 未知 protocol '{protocol}'，按厂家名推断")
    return _PROVIDER_PROTOCOL.get((provider or "").strip().lower(), DEFAULT_PROTOCOL)


def _pick_candidates(configs: List[Dict[str, Any]], role: str = "both") -> List[Dict[str, Any]]:
    """角色匹配的启用配置，按 priority 降序（首位为 primary，次位为 fallback）"""
    candidates = [
        c
        for c in configs
        if c.get("enabled", True) and (c.get("suitable_roles") or ["both"])
        and (role in (c.get("suitable_roles") or ["both"]) or "both" in (c.get("suitable_roles") or []))
    ]
    return sorted(candidates, key=lambda c: c.get("priority", 0), reverse=True)


def resolve_provider(
    configs: List[Dict[str, Any]],
    role: str = "both",
    provider_defaults: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Optional[ResolvedProvider]:
    """数据库配置 → ResolvedProvider；无可用配置返回 None。

    provider_defaults：{provider_name: {"api_key":…, "default_base_url":…, "protocol":…}}（厂家配置），
    模型配置缺 key/base_url 时按 provider 回退，协议取厂家级 protocol（与 llm_service.test_llm_config 同语义）。
    """
    candidates = _pick_candidates(configs, role)
    if not candidates:
        return None
    cfg = candidates[0]
    defaults = (provider_defaults or {}).get((cfg.get("provider") or "").strip().lower()) or {}
    api_key = cfg.get("api_key") or defaults.get("api_key") or ""
    base_url = cfg.get("api_base") or cfg.get("custom_endpoint") or defaults.get("default_base_url") or None
    return ResolvedProvider(
        protocol=infer_protocol(cfg.get("provider", ""), defaults.get("protocol")),
        model=cfg["model_name"],
        api_key=api_key,
        base_url=base_url,
        source="db",
        max_tokens=cfg.get("max_tokens"),
        temperature=cfg.get("temperature"),
        timeout=cfg.get("timeout"),
        retry_times=cfg.get("retry_times"),
        context_window=cfg.get("context_window"),
    )


def _resolve_fallback(
    configs: List[Dict[str, Any]],
    role: str,
    primary_model: str,
    provider_defaults: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Optional[ResolvedProvider]:
    """次高优先级且与 primary 不同的配置 → fallback 候选；无则 None"""
    candidates = _pick_candidates(configs, role)
    for cfg in candidates[1:]:
        if cfg["model_name"] != primary_model:
            defaults = (provider_defaults or {}).get((cfg.get("provider") or "").strip().lower()) or {}
            return ResolvedProvider(
                protocol=infer_protocol(cfg.get("provider", ""), defaults.get("protocol")),
                model=cfg["model_name"],
                api_key=cfg.get("api_key") or defaults.get("api_key") or "",
                base_url=(
                    cfg.get("api_base") or cfg.get("custom_endpoint")
                    or defaults.get("default_base_url") or None
                ),
                source="db",
            )
    return None


def resolve_from_env(protocol_hint: str = "anthropic") -> ResolvedProvider:
    """.env 回退（ARK_*）"""
    env_cfg = load_config()
    return ResolvedProvider(
        protocol=protocol_hint,
        model=env_cfg.default_model,
        api_key=env_cfg.api_key,
        base_url=(
            env_cfg.anthropic_base_url if protocol_hint == "anthropic" else env_cfg.openai_base_url
        ),
        source="env",
    )


def build_client(resolved: ResolvedProvider) -> BaseLLMClient:
    """ResolvedProvider → 协议客户端（每模型参数随实例化烙入）"""
    return create_client(
        resolved.protocol,
        model=resolved.model,
        api_key=resolved.api_key,
        base_url=resolved.base_url,
        max_tokens=resolved.max_tokens,
        timeout=resolved.timeout,
        temperature=resolved.temperature,
    )


# ── 数据库读取（motor 异步 + pymongo 同步双路径） ──────────────────────────
# 分析在工作线程 asyncio.run 新循环执行，motor 客户端绑定主事件循环会抛
# "attached to a different loop"，因此提供 pymongo 同步回退。

_CONFIG_FIELDS = (
    "provider", "model_name", "api_key", "api_base", "custom_endpoint",
    "enabled", "suitable_roles", "priority",
    # 每模型参数（表单采集，此前未消费）
    "max_tokens", "temperature", "timeout", "retry_times",
)


def _normalize_llm_configs(raw_configs: Any) -> List[Dict[str, Any]]:
    """llm_configs 原始数据 → 可序列化白名单字段列表"""
    configs: List[Dict[str, Any]] = []
    for c in raw_configs or []:
        if not isinstance(c, dict) or not c.get("model_name"):
            continue
        item = {k: c.get(k) for k in _CONFIG_FIELDS}
        item["api_base"] = c.get("api_base") or c.get("custom_endpoint")
        item["enabled"] = c.get("enabled", True)
        item["suitable_roles"] = c.get("suitable_roles") or ["both"]
        item["priority"] = c.get("priority", 0)
        configs.append(item)
    return configs


def _normalize_provider_defaults(provider_docs: Any) -> Dict[str, Dict[str, Any]]:
    """llm_providers 文档 → {provider_name(lower): {api_key, default_base_url, protocol}}"""
    defaults: Dict[str, Dict[str, Any]] = {}
    for p in provider_docs or []:
        if not isinstance(p, dict) or not p.get("name"):
            continue
        defaults[str(p["name"]).strip().lower()] = {
            "api_key": p.get("api_key") or "",
            "default_base_url": p.get("default_base_url") or None,
            "protocol": p.get("protocol") or None,
        }
    return defaults


def _build_context_length_index(catalog_docs: Any) -> Dict[str, int]:
    """model_catalog 文档 → {(provider, model_name): context_length}"""
    index: Dict[str, int] = {}
    for doc in catalog_docs or []:
        if not isinstance(doc, dict):
            continue
        provider = (doc.get("provider") or "").strip().lower()
        for m in doc.get("models") or []:
            name = m.get("name")
            length = m.get("context_length")
            if name and isinstance(length, int) and length > 0:
                index[f"{provider}|{name}"] = length
    return index


async def _load_provider_defaults_async() -> Dict[str, Dict[str, Any]]:
    """motor 读取 llm_providers（主循环内调用）"""
    try:
        from app.core.database import get_mongo_db

        db = get_mongo_db()
        docs = await db.llm_providers.find(
            {}, {"name": 1, "api_key": 1, "default_base_url": 1, "protocol": 1}
        ).to_list(200)
        return _normalize_provider_defaults(docs)
    except Exception as e:  # noqa: BLE001
        logger.info(f"[providers] 异步读取厂家配置失败: {e}")
        return {}


def _load_all_sync() -> tuple:
    """pymongo 同步读取（llm_configs + llm_providers + model_catalog）"""
    try:
        from app.core.database import get_mongo_db_sync

        db = get_mongo_db_sync()
        doc = db.system_configs.find_one({"is_active": True}, sort=[("version", -1)])
        configs = _normalize_llm_configs((doc or {}).get("llm_configs"))
        provider_docs = list(
            db.llm_providers.find(
                {}, {"name": 1, "api_key": 1, "default_base_url": 1, "protocol": 1}
            ).limit(200)
        )
        catalog_docs = list(db.model_catalog.find({}, {"provider": 1, "models": 1}).limit(200))
        return configs, _normalize_provider_defaults(provider_docs), _build_context_length_index(catalog_docs)
    except Exception as e:  # noqa: BLE001 - 数据库不可用（独立测试场景）
        logger.info(f"[providers] 同步读取数据库配置失败: {e}")
        return [], {}, {}


async def _resolve_role_bundle(
    role: str,
    configs: List[Dict[str, Any]],
    provider_defaults: Dict[str, Dict[str, Any]],
    context_index: Dict[str, int],
) -> EngineClientBundle:
    """单角色解析：primary + fallback + 参数；DB 无配置时 .env 回退"""
    resolved = resolve_provider(configs, role, provider_defaults)
    if resolved is None:
        resolved = resolve_from_env()
        logger.info(f"[providers] role={role} 无数据库配置，使用 .env 回退 ({resolved.model})")
    else:
        if not resolved.context_window:
            provider = next(
                (c.get("provider", "") for c in configs if c.get("model_name") == resolved.model), ""
            ).strip().lower()
            resolved.context_window = context_index.get(f"{provider}|{resolved.model}")
        logger.info(
            f"[providers] role={role} → {resolved.protocol}:{resolved.model} "
            f"(数据库配置, base_url={resolved.base_url or '默认'}, "
            f"max_tokens={resolved.max_tokens or '默认'}, context_window={resolved.context_window or '未知'})"
        )

    fallback_resolved = _resolve_fallback(configs, role, resolved.model, provider_defaults)
    fallback_client = None
    if fallback_resolved is not None and fallback_resolved.api_key:
        try:
            fallback_client = build_client(fallback_resolved)
            logger.info(
                f"[providers] role={role} fallback → {fallback_resolved.protocol}:{fallback_resolved.model}"
            )
        except Exception as e:  # noqa: BLE001 - fallback 构建失败不阻断主链路
            logger.warning(f"⚠️ [providers] role={role} fallback 客户端构建失败: {e}")

    return EngineClientBundle(
        primary=build_client(resolved),
        fallback=fallback_client,
        retry_times=resolved.retry_times,
        max_tokens=resolved.max_tokens,
        temperature=resolved.temperature,
        context_window=resolved.context_window,
    )


async def resolve_task_override_bundle(
    model: str,
    *,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Optional[EngineClientBundle]:
    """任务级模型覆盖 → bundle；从数据库同 model_name 配置继承每模型参数。

    背景：覆盖路径此前只传 model/api_key/base_url，导致 DB 配置的
    max_tokens（如 128000）丢失、回落 .env 默认 4096——推理模型输出
    全部耗在思考阶段即截断，正文为空（2026-08-19 000001 分析事故）。
    """
    configs: List[Dict[str, Any]] = []
    provider_defaults: Dict[str, Dict[str, Any]] = {}
    context_index: Dict[str, int] = {}
    try:
        from app.services.config import config_service

        system_config = await config_service.get_system_config()
        configs = _normalize_llm_configs(
            [c.model_dump() for c in (system_config.llm_configs or [])]
        )
        if configs:
            provider_defaults = await _load_provider_defaults_async()
    except Exception as e:  # noqa: BLE001 - 数据库不可用时仅用入参
        logger.info(f"[providers] 任务覆盖读取数据库配置失败: {e}")
    if not configs:
        configs, provider_defaults, context_index = _load_all_sync()

    # 同名模型配置继承每模型参数（覆盖路径不应丢失 DB 参数）
    inherit = next((c for c in configs if c.get("model_name") == model), None) or {}
    prov = provider or inherit.get("provider") or "openai"
    defaults = provider_defaults.get(prov.strip().lower()) or {}
    resolved = ResolvedProvider(
        protocol=infer_protocol(prov, defaults.get("protocol")),
        model=model,
        api_key=api_key or inherit.get("api_key") or defaults.get("api_key") or "",
        base_url=base_url or inherit.get("api_base") or defaults.get("default_base_url") or None,
        source="engine-config",
        max_tokens=inherit.get("max_tokens"),
        temperature=inherit.get("temperature"),
        timeout=inherit.get("timeout"),
        retry_times=inherit.get("retry_times"),
        context_window=None,
    )
    provider_l = prov.strip().lower()
    resolved.context_window = inherit.get("context_window") or context_index.get(
        f"{provider_l}|{model}"
    )
    if not resolved.api_key:
        return None
    bundle = EngineClientBundle(
        primary=build_client(resolved),
        fallback=None,
        retry_times=resolved.retry_times,
        max_tokens=resolved.max_tokens,
        temperature=resolved.temperature,
        context_window=resolved.context_window,
    )
    logger.info(
        f"[providers] 任务覆盖 → {resolved.protocol}:{model} "
        f"(max_tokens={resolved.max_tokens or '默认'}, "
        f"context_window={resolved.context_window or '未知'})"
    )
    return bundle


async def get_engine_clients() -> Dict[str, EngineClientBundle]:
    """引擎入口：数据库配置优先，.env 回退。返回 {"analyst": bundle, "debate": bundle}。

    数据库不可用（如独立测试场景）不抛异常，静默回退 env。
    """
    configs: List[Dict[str, Any]] = []
    provider_defaults: Dict[str, Dict[str, Any]] = {}
    context_index: Dict[str, int] = {}
    try:
        from app.services.config import config_service

        system_config = await config_service.get_system_config()
        configs = _normalize_llm_configs(
            [c.model_dump() for c in (system_config.llm_configs or [])]
        )
    except Exception as e:  # noqa: BLE001 - 独立使用 app/llm 时无数据库
        logger.info(f"[providers] 数据库配置不可用: {e}")
    if configs:
        provider_defaults = await _load_provider_defaults_async()
    else:
        # motor 读取失败（常见于分析工作线程跨事件循环）→ pymongo 同步回退
        configs, provider_defaults, context_index = _load_all_sync()
        if configs:
            logger.info("[providers] motor 不可用，已通过 pymongo 同步读取数据库配置")

    bundles: Dict[str, EngineClientBundle] = {}
    for role in ("analyst", "debate"):
        bundles[role] = await _resolve_role_bundle(role, configs, provider_defaults, context_index)
    return bundles
