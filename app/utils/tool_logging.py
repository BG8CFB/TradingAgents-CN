#!/usr/bin/env python3
"""
工具调用日志装饰器
为所有工具调用添加统一的日志记录
"""

import time
import functools
from typing import Any, Dict, Optional, Callable
from datetime import datetime
from app.engine.config.runtime_settings import get_timezone_name
from app.utils.time_utils import now_config_tz

from app.utils.logging_init import get_logger

# 导入日志模块
from app.utils.logging_manager import get_logger, get_logger_manager
logger = get_logger('agents')

# 工具调用日志器
tool_logger = get_logger("tools")


def log_tool_call(tool_name: Optional[str] = None, log_args: bool = True, log_result: bool = False):
    """
    工具调用日志装饰器

    Args:
        tool_name: 工具名称，如果不提供则使用函数名
        log_args: 是否记录参数
        log_result: 是否记录返回结果（注意：可能包含大量数据）
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 确定工具名称
            name = tool_name or getattr(func, '__name__', 'unknown_tool')

            # 记录开始时间
            start_time = time.time()

            # 准备参数信息
            args_info = {}
            if log_args:
                # 记录位置参数
                if args:
                    args_info['args'] = [str(arg)[:100] + '...' if len(str(arg)) > 100 else str(arg) for arg in args]

                # 记录关键字参数
                if kwargs:
                    args_info['kwargs'] = {
                        k: str(v)[:100] + '...' if len(str(v)) > 100 else str(v)
                        for k, v in kwargs.items()
                    }

            # 记录工具调用开始
            tool_logger.info(
                f"🔧 [工具调用] {name} - 开始",
                extra={
                    'tool_name': name,
                    'event_type': 'tool_call_start',
                    'timestamp': now_config_tz().isoformat(),
                    'args_info': args_info if log_args else None
                }
            )

            try:
                # 执行工具函数
                result = func(*args, **kwargs)

                # 计算执行时间
                duration = time.time() - start_time

                # 准备结果信息
                result_info = None
                if log_result and result is not None:
                    result_str = str(result)
                    result_info = result_str[:200] + '...' if len(result_str) > 200 else result_str

                # 记录工具调用成功
                tool_logger.info(
                    f"✅ [工具调用] {name} - 完成 (耗时: {duration:.2f}s)",
                    extra={
                        'tool_name': name,
                        'event_type': 'tool_call_success',
                        'duration': duration,
                        'result_info': result_info if log_result else None,
                        'timestamp': now_config_tz().isoformat()
                    }
                )

                return result

            except Exception as e:
                # 计算执行时间
                duration = time.time() - start_time

                # 记录工具调用失败
                tool_logger.error(
                    f"❌ [工具调用] {name} - 失败 (耗时: {duration:.2f}s): {str(e)}",
                    extra={
                        'tool_name': name,
                        'event_type': 'tool_call_error',
                        'duration': duration,
                        'error': str(e),
                        'timestamp': now_config_tz().isoformat()
                    },
                    exc_info=True
                )

                # 🔥 [增强] 返回对 LLM 友好的错误提示，而不是直接抛出异常导致程序崩溃或重试循环
                # 这种模式称为 "Graceful Error Handling for Agents"
                error_feedback = (
                    f"❌ 工具 {name} 调用失败\n"
                    f"错误详情: {str(e)}\n\n"
                    f"💡 建议操作:\n"
                    f"1. 请检查输入参数是否符合要求。\n"
                    f"2. 如果是数据源错误，请尝试跳过调用错误的工具。\n"
                    f"3. ⚠️ 请不要用完全相同的参数立即重试，这通常无效。\n"
                    f"4. 如果无法解决，请在报告中记录此错误并继续分析其他部分。"
                )
                return error_feedback

        return wrapper
    return decorator


def log_data_source_call(source_name: str):
    """
    数据源调用专用日志装饰器

    Args:
        source_name: 数据源名称（如：tushare、akshare、yfinance等）
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()

            # 提取股票代码（通常是第一个参数）
            symbol = args[0] if args else kwargs.get('symbol', kwargs.get('ticker', 'unknown'))

            # 记录数据源调用开始
            tool_logger.info(
                f"📊 [数据源] {source_name} - 获取 {symbol} 数据",
                extra={
                    'data_source': source_name,
                    'symbol': symbol,
                    'event_type': 'data_source_call',
                    'timestamp': now_config_tz().isoformat()
                }
            )

            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time

                # 检查结果是否成功
                success = result and "❌" not in str(result) and "错误" not in str(result)

                if success:
                    tool_logger.info(
                        f"✅ [数据源] {source_name} - {symbol} 数据获取成功 (耗时: {duration:.2f}s)",
                        extra={
                            'data_source': source_name,
                            'symbol': symbol,
                            'event_type': 'data_source_success',
                            'duration': duration,
                            'data_size': len(str(result)) if result else 0,
                            'timestamp': now_config_tz().isoformat()
                        }
                    )
                else:
                    tool_logger.warning(
                        f"⚠️ [数据源] {source_name} - {symbol} 数据获取失败 (耗时: {duration:.2f}s)",
                        extra={
                            'data_source': source_name,
                            'symbol': symbol,
                            'event_type': 'data_source_failure',
                            'duration': duration,
                            'timestamp': now_config_tz().isoformat()
                        }
                    )

                return result

            except Exception as e:
                duration = time.time() - start_time

                tool_logger.error(
                    f"❌ [数据源] {source_name} - {symbol} 数据获取异常 (耗时: {duration:.2f}s): {str(e)}",
                    extra={
                        'data_source': source_name,
                        'symbol': symbol,
                        'event_type': 'data_source_error',
                        'duration': duration,
                        'error': str(e),
                        'timestamp': now_config_tz().isoformat()
                    },
                    exc_info=True
                )

                raise

        return wrapper
    return decorator


def log_llm_call(provider: str, model: str):
    """
    LLM调用专用日志装饰器

    Args:
        provider: LLM提供商（如：openai、deepseek、tongyi等）
        model: 模型名称
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()

            # 记录LLM调用开始
            tool_logger.info(
                f"🤖 [LLM调用] {provider}/{model} - 开始",
                extra={
                    'llm_provider': provider,
                    'llm_model': model,
                    'event_type': 'llm_call_start',
                    'timestamp': now_config_tz().isoformat()
                }
            )

            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time

                tool_logger.info(
                    f"✅ [LLM调用] {provider}/{model} - 完成 (耗时: {duration:.2f}s)",
                    extra={
                        'llm_provider': provider,
                        'llm_model': model,
                        'event_type': 'llm_call_success',
                        'duration': duration,
                        'timestamp': now_config_tz().isoformat()
                    }
                )

                return result

            except Exception as e:
                duration = time.time() - start_time

                tool_logger.error(
                    f"❌ [LLM调用] {provider}/{model} - 失败 (耗时: {duration:.2f}s): {str(e)}",
                    extra={
                        'llm_provider': provider,
                        'llm_model': model,
                        'event_type': 'llm_call_error',
                        'duration': duration,
                        'error': str(e),
                        'timestamp': now_config_tz().isoformat()
                    },
                    exc_info=True
                )

                raise

        return wrapper
    return decorator


# 便捷函数
def log_tool_usage(tool_name: str, symbol: str = None, **extra_data):
    """
    记录工具使用情况的便捷函数

    Args:
        tool_name: 工具名称
        symbol: 股票代码（可选）
        **extra_data: 额外的数据
    """
    extra = {
        'tool_name': tool_name,
        'event_type': 'tool_usage',
        'timestamp': now_config_tz().isoformat(),
        **extra_data
    }

    if symbol:
        extra['symbol'] = symbol

    tool_logger.info(f"📋 [工具使用] {tool_name}", extra=extra)


def log_analysis_step(step_name: str, symbol: str, **extra_data):
    """
    记录分析步骤的便捷函数

    Args:
        step_name: 步骤名称
        symbol: 股票代码
        **extra_data: 额外的数据
    """
    extra = {
        'step_name': step_name,
        'symbol': symbol,
        'event_type': 'analysis_step',
        'timestamp': now_config_tz().isoformat(),
        **extra_data
    }

    tool_logger.info(f"📈 [分析步骤] {step_name} - {symbol}", extra=extra)


def log_analysis_module(module_name: str, session_id: str = None):
    """
    分析模块日志装饰器
    自动记录模块的开始和结束

    Args:
        module_name: 模块名称（如：market_analyst、fundamentals_analyst等）
        session_id: 会话ID（可选）
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 尝试从参数中提取股票代码
            symbol = None

            # 特殊处理：信号处理模块的参数结构
            if module_name == "graph_signal_processing":
                # 信号处理模块：process_signal(self, full_signal, stock_symbol=None)
                if len(args) >= 3:  # self, full_signal, stock_symbol
                    symbol = str(args[2]) if args[2] else None
                elif 'stock_symbol' in kwargs:
                    symbol = str(kwargs['stock_symbol']) if kwargs['stock_symbol'] else None
            else:
                if args:
                    # 检查第一个参数是否是state字典（分析师节点的情况）
                    first_arg = args[0]
                    if isinstance(first_arg, dict) and 'company_of_interest' in first_arg:
                        symbol = str(first_arg['company_of_interest'])
                    # 检查第一个参数是否是股票代码
                    elif isinstance(first_arg, str) and len(first_arg) <= 10:
                        symbol = first_arg

            # 从kwargs中查找股票代码
            if not symbol:
                for key in ['symbol', 'ticker', 'stock_code', 'stock_symbol', 'company_of_interest']:
                    if key in kwargs:
                        symbol = str(kwargs[key])
                        break

            # 如果还是没找到，使用默认值
            if not symbol:
                symbol = 'unknown'

            # 生成会话ID
            actual_session_id = session_id or f"session_{int(time.time())}"

            # 记录模块开始
            logger_manager = get_logger_manager()

            start_time = time.time()

            logger_manager.log_module_start(
                tool_logger, module_name, symbol, actual_session_id,
                function_name=func.__name__,
                args_count=len(args),
                kwargs_keys=list(kwargs.keys())
            )

            try:
                # 执行分析函数
                result = func(*args, **kwargs)

                # 计算执行时间
                duration = time.time() - start_time

                # 记录模块完成
                result_length = len(str(result)) if result else 0
                logger_manager.log_module_complete(
                    tool_logger, module_name, symbol, actual_session_id,
                    duration, success=True, result_length=result_length,
                    function_name=func.__name__
                )

                return result

            except Exception as e:
                # 计算执行时间
                duration = time.time() - start_time

                # 记录模块错误
                logger_manager.log_module_error(
                    tool_logger, module_name, symbol, actual_session_id,
                    duration, str(e),
                    function_name=func.__name__
                )

                # 重新抛出异常
                raise

        return wrapper
    return decorator


def log_analyst_module(analyst_type: str):
    """
    分析师模块专用装饰器

    Args:
        analyst_type: 分析师类型（如：market、fundamentals、technical、sentiment等）
    """
    return log_analysis_module(f"{analyst_type}_analyst")


def log_graph_module(graph_type: str):
    """
    图处理模块专用装饰器

    Args:
        graph_type: 图处理类型（如：signal_processing、workflow等）
    """
    return log_analysis_module(f"graph_{graph_type}")


def log_dataflow_module(dataflow_type: str):
    """
    数据流模块专用装饰器

    Args:
        dataflow_type: 数据流类型（如：cache、interface、provider等）
    """
    return log_analysis_module(f"dataflow_{dataflow_type}")
