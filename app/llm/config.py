"""
app/llm 层配置（本层唯一直接读环境变量的模块，已在 pre-commit 白名单）

配置项：
- ARK_API_KEY               火山 Ark API Key（两协议共用）
- ARK_ANTHROPIC_BASE_URL    Anthropic 协议端点
- ARK_OPENAI_BASE_URL       OpenAI 兼容协议端点
- LLM_DEFAULT_MODEL         默认模型
"""

import os
from dataclasses import dataclass
from pathlib import Path

from app.constants.llm_defaults import DEFAULT_MAX_TOKENS, MAX_TOKENS_MAX
import logging

logger = logging.getLogger("app.llm.config")


def project_root() -> Path:
    """项目根目录（app/llm/config.py 上两级）"""
    return Path(__file__).resolve().parents[2]


def _load_dotenv_once() -> None:
    """独立使用本层时（测试/脚本）自行加载项目根 .env；已加载则跳过"""
    if os.environ.get("ARK_API_KEY"):
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(project_root() / ".env", override=False)
    except ImportError:
        pass


DEFAULT_ANTHROPIC_BASE_URL = "https://ark.cn-beijing.volces.com/api/coding"
DEFAULT_OPENAI_BASE_URL = "https://ark.cn-beijing.volces.com/api/coding/v3"
DEFAULT_MODEL = "deepseek-v4-flash"


@dataclass
class LLMConfig:
    api_key: str = ""
    anthropic_base_url: str = DEFAULT_ANTHROPIC_BASE_URL
    openai_base_url: str = DEFAULT_OPENAI_BASE_URL
    default_model: str = DEFAULT_MODEL
    timeout: float = 300.0  # 长思考模型可能较慢，参考 claude-code 默认 600s，取 300s
    # 兜底默认（单一源头 app/constants/llm_defaults.py；此前 4096 曾导致推理模型
    # 思考阶段即截断、正文为空——2026-08-19 事故）。LLM_DEFAULT_MAX_TOKENS 作全局回滚开关。
    max_tokens: int = DEFAULT_MAX_TOKENS


def load_config() -> LLMConfig:
    """从环境变量加载配置（独立使用时先加载项目根 .env）"""
    _load_dotenv_once()
    raw_max_tokens = os.getenv("LLM_DEFAULT_MAX_TOKENS", "").strip()
    max_tokens = DEFAULT_MAX_TOKENS
    if raw_max_tokens:
        try:
            val = int(raw_max_tokens)
        except ValueError:
            logger.warning(f"⚠️ [app.llm] LLM_DEFAULT_MAX_TOKENS 非法: {raw_max_tokens!r}，忽略")
        else:
            if val >= 1:
                max_tokens = min(val, MAX_TOKENS_MAX)
    cfg = LLMConfig(
        api_key=os.getenv("ARK_API_KEY", ""),
        anthropic_base_url=os.getenv("ARK_ANTHROPIC_BASE_URL", DEFAULT_ANTHROPIC_BASE_URL),
        openai_base_url=os.getenv("ARK_OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL),
        default_model=os.getenv("LLM_DEFAULT_MODEL", DEFAULT_MODEL),
        max_tokens=max_tokens,
    )
    if not cfg.api_key:
        logger.warning("⚠️ [app.llm] ARK_API_KEY 未配置，调用将在创建客户端时报 AuthError")
    return cfg
