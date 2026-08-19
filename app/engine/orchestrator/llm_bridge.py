"""
引擎节点 → app/llm 新层桥接

纯 LLM 节点（Stage 2-4）统一经此处调用新客户端：
- with_retry 包裹（指数退避，鉴权失败不重试；重试上限取每模型配置）
- 消息形态为 app/llm core.types.Message（system 走独立参数）
- 支持传入 EngineClientBundle（providers.py）：每模型参数生效 +
  限流连续 3 次自动切换 fallback 模型重试一次（对齐 claude-code query.ts）
"""

from typing import List, Optional

from app.llm.core.base import BaseLLMClient
from app.llm.core.types import Message, Role
from app.llm.retry import DEFAULT_MAX_RETRIES, FallbackTriggeredError, with_retry

# 引擎纯 LLM 节点的默认输出上限（每模型配置缺省时的兜底）
DEFAULT_NODE_MAX_TOKENS = 8192


def _is_bundle(llm: object) -> bool:
    """EngineClientBundle 鸭子判定（providers.py 的 dataclass，避免循环 import）"""
    return hasattr(llm, "primary")


async def llm_chat(
    llm: object,
    messages: List[Message],
    *,
    system: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
) -> str:
    """带重试的单轮对话，返回文本内容（空响应返回空串，由调用方降级）。

    llm 可为裸 BaseLLMClient 或 EngineClientBundle（推荐，携带每模型参数与 fallback）。
    """
    bundle = llm if _is_bundle(llm) else None
    primary: BaseLLMClient = bundle.primary if bundle else llm  # type: ignore[assignment]

    eff_max_tokens = max_tokens or (bundle.max_tokens if bundle else None) or DEFAULT_NODE_MAX_TOKENS
    eff_temperature = temperature if temperature is not None else (bundle.temperature if bundle else None)
    retries = bundle.retry_times if bundle and bundle.retry_times is not None else DEFAULT_MAX_RETRIES

    async def _call(client: BaseLLMClient) -> str:
        resp = await with_retry(
            lambda: client.chat(
                messages,
                system=system,
                max_tokens=eff_max_tokens,
                temperature=eff_temperature,
            ),
            max_retries=retries,
        )
        return resp.text() or ""

    try:
        return await _call(primary)
    except FallbackTriggeredError:
        # 限流连续触发：切换 fallback 模型重试一次（无 fallback 则上抛）
        if bundle is not None and bundle.fallback is not None:
            from app.utils.logging_init import get_logger

            get_logger("app.engine.llm_bridge").warning(
                f"⚠️ [llm_bridge] 连续限流，切换 fallback 模型 → {getattr(bundle.fallback, 'model', '')}"
            )
            return await _call(bundle.fallback)
        raise


def sync_chat(llm: object, user_prompt: str, *, system: Optional[str] = None) -> str:
    """同步环境调用新客户端（Reflector / SignalProcessor 等同步代码路径）。

    已在事件循环线程中时降级到新线程隔离运行，避免嵌套 asyncio.run 报错。
    """
    import asyncio
    import threading

    async def _run() -> str:
        return await llm_chat(
            llm, [Message(role=Role.USER, content=user_prompt)], system=system
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_run())

    container: dict = {}

    def _in_thread():
        try:
            container["result"] = asyncio.run(_run())
        except Exception as e:  # noqa: BLE001
            container["error"] = e

    t = threading.Thread(target=_in_thread, daemon=True)
    t.start()
    t.join(timeout=300)
    if "error" in container:
        raise container["error"]
    return container.get("result", "")
