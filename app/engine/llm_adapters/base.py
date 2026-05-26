"""
LLM 适配器统一基类
提供 token 跟踪、API Key 解析等通用能力
"""

import os
import time
from typing import Optional

from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult

from app.utils.logging_manager import get_logger, get_logger_manager

logger = get_logger("agents")

# Token 跟踪器
try:
    from app.services.usage_statistics_service import token_tracker

    TOKEN_TRACKING_ENABLED = True
except ImportError:
    token_tracker = None
    TOKEN_TRACKING_ENABLED = False


class BaseChatAdapter:
    """
    LLM 适配器 mixin，提供统一的 token 跟踪和 API Key 解析。

    不继承任何 LangChain 类，由具体适配器通过多重继承混入。
    """

    _provider_name: str = ""
    _model_name_alias: str = ""

    # ── API Key 解析 ──────────────────────────────────────────

    @staticmethod
    def resolve_api_key(
        provider: str,
        api_key: Optional[str] = None,
        api_key_env: Optional[str] = None,
    ) -> Optional[str]:
        """
        统一 API Key 解析。

        优先级: 显式 api_key 参数 > 环境变量 > None
        对本地模型（如 Ollama）返回 None 也合法。
        """
        if api_key:
            return api_key

        if not api_key_env:
            return None

        env_val = os.getenv(api_key_env)
        if not env_val:
            return None

        # 过滤占位符
        try:
            from app.utils.api_key_utils import is_valid_api_key

            if is_valid_api_key(env_val):
                return env_val
        except ImportError:
            return env_val

        return None

    # ── Token 跟踪 ────────────────────────────────────────────

    def _track_token_usage(self, result, kwargs: dict, start_time: float):
        """从 LLM 调用结果中提取 token 用量并记录。"""
        if not TOKEN_TRACKING_ENABLED or not token_tracker:
            return

        try:
            provider = getattr(self, "_provider_name", "unknown")
            model_name = getattr(self, "model_name", None) or getattr(self, "_model_name_alias", "unknown")

            input_tokens = 0
            output_tokens = 0

            # 优先从 usage_metadata 提取（ChatOpenAI 标准路径）
            usage = getattr(result, "usage_metadata", None)
            if usage and isinstance(usage, dict):
                input_tokens = usage.get("input_tokens", 0) or 0
                output_tokens = usage.get("output_tokens", 0) or 0

            # 回退到 llm_output.token_usage（部分 provider 的旧路径）
            if input_tokens == 0 and output_tokens == 0:
                llm_output = getattr(result, "llm_output", None)
                if llm_output and isinstance(llm_output, dict):
                    token_usage = llm_output.get("token_usage", {})
                    input_tokens = token_usage.get("prompt_tokens", 0) or 0
                    output_tokens = token_usage.get("completion_tokens", 0) or 0

            # 最后估算
            if input_tokens == 0 and output_tokens == 0:
                input_tokens = self._estimate_input_tokens(kwargs)
                output_tokens = self._estimate_output_tokens(result)

            if input_tokens > 0 or output_tokens > 0:
                session_id = kwargs.pop("session_id", None) or f"{provider}_{int(time.time())}"
                analysis_type = kwargs.pop("analysis_type", None) or "stock_analysis"

                record = token_tracker.track_usage(
                    provider=provider,
                    model_name=model_name,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    session_id=session_id,
                    analysis_type=analysis_type,
                )

                elapsed = time.time() - start_time
                cost = record.cost if record else 0.0

                log_mgr = get_logger_manager()
                log_mgr.log_token_usage(
                    logger, provider, model_name,
                    input_tokens, output_tokens, cost, session_id,
                )
                logger.info(
                    f"[Token] {provider}/{model_name} "
                    f"in={input_tokens} out={output_tokens} "
                    f"cost={cost:.6f} elapsed={elapsed:.2f}s"
                )

        except Exception as e:
            logger.warning("Token 跟踪失败: %s", e, exc_info=True)

    @staticmethod
    def _estimate_input_tokens(kwargs: dict) -> int:
        """估算输入 token 数（2 字符/token）"""
        messages = kwargs.get("messages")
        if not messages:
            return 0
        total_chars = sum(len(str(getattr(m, "content", ""))) for m in messages)
        return max(1, total_chars // 2)

    @staticmethod
    def _estimate_output_tokens(result) -> int:
        """估算输出 token 数（2 字符/token）"""
        total_chars = 0
        for gen_list in getattr(result, "generations", []):
            if isinstance(gen_list, list):
                for g in gen_list:
                    msg = getattr(g, "message", None)
                    if msg:
                        total_chars += len(str(getattr(msg, "content", "")))
        return max(1, total_chars // 2)

    @property
    def provider_name(self) -> str:
        return getattr(self, "_provider_name", "")
