"""
客户端工厂：按协议创建 BaseLLMClient 实例

对外唯一入口（app/llm/__init__.py 转发），消费方不直接 import 协议实现。
每模型参数（max_tokens/timeout/temperature/thinking_*）随实例化烙入客户端；
temperature 与思考参数作为实例默认值（调用处显式传参可覆盖）。
思考参数烙入实例后，压缩器、子代理、fallback 备模型等所有内部调用
自动继承各客户端自己的思考配置，无需调用链逐层透传。
"""

from typing import Optional

from ..config import LLMConfig, load_config
from .base import BaseLLMClient
from .errors import AuthError

VALID_PROTOCOLS = ("anthropic", "openai")


def create_client(
    protocol: str = "anthropic",
    *,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    config: Optional[LLMConfig] = None,
    max_tokens: Optional[int] = None,
    timeout: Optional[float] = None,
    temperature: Optional[float] = None,
    thinking_budget: Optional[int] = None,
    thinking_effort: Optional[str] = None,
    provider: Optional[str] = None,
) -> BaseLLMClient:
    """
    创建 LLM 客户端。

    Args:
        protocol: "anthropic" 或 "openai"
        model: 模型名，缺省用配置中的 default_model
        api_key: 覆盖配置中的 key（优先级：参数 > 环境变量）
        base_url: 覆盖配置中的端点
        config:  完整配置对象（测试/多套环境用）
        max_tokens / timeout / temperature: 每模型参数（数据库"添加模型"配置），
            缺省回退 .env 层默认值；temperature 存为实例默认，调用处可覆盖
        thinking_budget / thinking_effort: 思考参数（数据库"添加模型"配置），
            存为实例默认值（thinking.py 按方言注入；调用处显式传参可覆盖）
        provider: 厂家标识（如 "openai"/"deepseek"/"vllm"），思考方言判定用
    """
    if protocol not in VALID_PROTOCOLS:
        raise ValueError(f"未知协议: {protocol}，可选: {VALID_PROTOCOLS}")

    cfg = config or load_config()
    key = api_key or cfg.api_key
    if not key:
        raise AuthError("缺少 API key：请设置 ARK_API_KEY 或传入 api_key 参数", protocol=protocol)

    model = model or cfg.default_model

    if protocol == "anthropic":
        from ..protocols.anthropic_client import AnthropicLLMClient

        return AnthropicLLMClient(
            api_key=key,
            base_url=base_url or cfg.anthropic_base_url,
            model=model,
            timeout=timeout if timeout is not None else cfg.timeout,
            max_tokens=max_tokens if max_tokens is not None else cfg.max_tokens,
            temperature=temperature,
            thinking_budget=thinking_budget,
            thinking_effort=thinking_effort,
            provider=provider,
        )

    from ..protocols.openai_client import OpenAILLMClient

    return OpenAILLMClient(
        api_key=key,
        base_url=base_url or cfg.openai_base_url,
        model=model,
        timeout=timeout if timeout is not None else cfg.timeout,
        max_tokens=max_tokens if max_tokens is not None else cfg.max_tokens,
        temperature=temperature,
        thinking_budget=thinking_budget,
        thinking_effort=thinking_effort,
        provider=provider,
    )
