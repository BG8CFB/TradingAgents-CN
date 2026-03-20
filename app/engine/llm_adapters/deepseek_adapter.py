"""
DeepSeek LLM适配器，支持Token使用统计
"""

import os
import time
from typing import Any, Dict, List, Optional, Union
from langchain_core.messages import BaseMessage, AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI
from langchain_core.callbacks import CallbackManagerForLLMRun

# 导入统一日志系统
from app.utils.logging_init import setup_llm_logging

# 导入日志模块
from app.utils.logging_manager import get_logger, get_logger_manager
logger = get_logger('agents')
logger = setup_llm_logging()

# 导入token跟踪器
try:
    from app.engine.config.config_manager import token_tracker
    TOKEN_TRACKING_ENABLED = True
    logger.info("✅ Token跟踪功能已启用")
except ImportError:
    TOKEN_TRACKING_ENABLED = False
    logger.warning("⚠️ Token跟踪功能未启用")


class ChatDeepSeek(ChatOpenAI):
    """
    DeepSeek聊天模型适配器，支持Token使用统计
    
    继承自ChatOpenAI，添加了Token使用量统计功能
    """
    
    def __init__(
        self,
        model: str = "deepseek-chat",
        api_key: Optional[str] = None,
        base_url: str = "https://api.deepseek.com",
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        **kwargs
    ):
        """
        初始化DeepSeek适配器
        
        Args:
            model: 模型名称，默认为deepseek-chat
            api_key: API密钥，如果不提供则从环境变量DEEPSEEK_API_KEY获取
            base_url: API基础URL
            temperature: 温度参数
            max_tokens: 最大token数
            **kwargs: 其他参数
        """
        
        # 获取API密钥
        if api_key is None:
            # 导入 API Key 验证工具
            try:
                from app.utils.api_key_utils import is_valid_api_key
            except ImportError:
                def is_valid_api_key(key):
                    # 为了支持本地AI模型，API Key总是有效的
                    return True

            # 从环境变量读取 API Key
            env_api_key = os.getenv("DEEPSEEK_API_KEY")

            # 验证环境变量中的 API Key 是否有效（排除占位符）
            if env_api_key and is_valid_api_key(env_api_key):
                api_key = env_api_key
                logger.info("✅ [DeepSeek初始化] 使用环境变量中的有效 API Key")
            elif env_api_key:
                logger.warning("⚠️ [DeepSeek初始化] 环境变量中的 API Key 无效（可能是占位符），将被忽略")
                api_key = None
            else:
                api_key = None

            if not api_key:
                raise ValueError(
                    "DeepSeek API密钥未找到。请在 Web 界面配置 API Key "
                    "(设置 -> 大模型厂家) 或设置 DEEPSEEK_API_KEY 环境变量。"
                )
        
        # 初始化父类（使用新版参数名，替代已弃用的 openai_api_key/openai_api_base）
        super().__init__(
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )
        
        self.model_name = model
        
    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """
        生成聊天响应，并记录token使用量
        """

        # 记录开始时间
        start_time = time.time()

        # 提取并移除自定义参数，避免传递给父类
        session_id = kwargs.pop('session_id', None)
        analysis_type = kwargs.pop('analysis_type', None)

        try:
            # 调用父类方法生成响应
            result = super()._generate(messages, stop, run_manager, **kwargs)
            
            # 提取token使用量
            input_tokens = 0
            output_tokens = 0
            
            # 尝试从响应中提取token使用量
            if hasattr(result, 'llm_output') and result.llm_output:
                token_usage = result.llm_output.get('token_usage', {})
                if token_usage:
                    input_tokens = token_usage.get('prompt_tokens', 0)
                    output_tokens = token_usage.get('completion_tokens', 0)
            
            # 如果没有获取到token使用量，进行估算
            if input_tokens == 0 and output_tokens == 0:
                input_tokens = self._estimate_input_tokens(messages)
                output_tokens = self._estimate_output_tokens(result)
                logger.debug(f"🔍 [DeepSeek] 使用估算token: 输入={input_tokens}, 输出={output_tokens}")
            else:
                logger.info(f"📊 [DeepSeek] 实际token使用: 输入={input_tokens}, 输出={output_tokens}")
            
            # 记录token使用量
            if TOKEN_TRACKING_ENABLED and (input_tokens > 0 or output_tokens > 0):
                try:
                    # 使用提取的参数或生成默认值
                    if session_id is None:
                        session_id = f"deepseek_{hash(str(messages))%10000}"
                    if analysis_type is None:
                        analysis_type = 'stock_analysis'

                    # 记录使用量
                    usage_record = token_tracker.track_usage(
                        provider="deepseek",
                        model_name=self.model_name,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        session_id=session_id,
                        analysis_type=analysis_type
                    )

                    if usage_record:
                        if usage_record.cost == 0.0:
                            logger.warning(f"⚠️ [DeepSeek] 成本计算为0，可能配置有问题")
                        else:
                            logger.info(f"💰 [DeepSeek] 本次调用成本: ¥{usage_record.cost:.6f}")

                        # 使用统一日志管理器的Token记录方法
                        logger_manager = get_logger_manager()
                        logger_manager.log_token_usage(
                            logger, "deepseek", self.model_name,
                            input_tokens, output_tokens, usage_record.cost,
                            session_id
                        )
                    else:
                        logger.warning(f"⚠️ [DeepSeek] 未创建使用记录")

                except Exception as track_error:
                    logger.error(f"⚠️ [DeepSeek] Token统计失败: {track_error}", exc_info=True)
            
            return result
            
        except Exception as e:
            logger.error(f"❌ [DeepSeek] 调用失败: {e}", exc_info=True)
            raise
    
    def _estimate_input_tokens(self, messages: List[BaseMessage]) -> int:
        """
        估算输入token数量
        
        Args:
            messages: 输入消息列表
            
        Returns:
            估算的输入token数量
        """
        total_chars = 0
        for message in messages:
            if hasattr(message, 'content'):
                total_chars += len(str(message.content))
        
        # 粗略估算：中文约1.5字符/token，英文约4字符/token
        # 这里使用保守估算：2字符/token
        estimated_tokens = max(1, total_chars // 2)
        return estimated_tokens
    
    def _estimate_output_tokens(self, result: ChatResult) -> int:
        """
        估算输出token数量
        
        Args:
            result: 聊天结果
            
        Returns:
            估算的输出token数量
        """
        total_chars = 0
        for generation in result.generations:
            if hasattr(generation, 'message') and hasattr(generation.message, 'content'):
                total_chars += len(str(generation.message.content))
        
        # 粗略估算：2字符/token
        estimated_tokens = max(1, total_chars // 2)
        return estimated_tokens
    
    def invoke(
        self,
        input: Union[str, List[BaseMessage]],
        config: Optional[Dict] = None,
        **kwargs: Any,
    ) -> AIMessage:
        """
        调用模型生成响应
        
        Args:
            input: 输入消息
            config: 配置参数
            **kwargs: 其他参数（包括session_id和analysis_type）
            
        Returns:
            AI消息响应
        """
        
        # 处理输入
        if isinstance(input, str):
            messages = [HumanMessage(content=input)]
        else:
            messages = input
        
        # 调用生成方法
        result = self._generate(messages, **kwargs)
        
        # 返回第一个生成结果的消息
        if result.generations:
            return result.generations[0].message
        else:
            return AIMessage(content="")


def create_deepseek_llm(
    model: str = "deepseek-chat",
    temperature: float = 0.1,
    max_tokens: Optional[int] = None,
    **kwargs
) -> ChatDeepSeek:
    """
    创建DeepSeek LLM实例的便捷函数
    
    Args:
        model: 模型名称
        temperature: 温度参数
        max_tokens: 最大token数
        **kwargs: 其他参数
        
    Returns:
        ChatDeepSeek实例
    """
    return ChatDeepSeek(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs
    )


# 为了向后兼容，提供别名
DeepSeekLLM = ChatDeepSeek
