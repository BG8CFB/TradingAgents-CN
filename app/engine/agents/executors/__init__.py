"""
AgentExecutor 执行引擎包

提供智能体工具调用的自主决策执行框架，核心模块：
- AgentExecutor: 核心执行引擎
- LoopDetector: 多维度循环检测
- TokenBudget: Token 预算管理
- ToolResultProcessor: 工具结果处理
- StateInjector: 执行状态注入（让 LLM 自主决策）
"""

from .agent_executor import AgentExecutor, ExecutionResult
from .loop_detector import LoopDetector, LoopDetectionResult, ToolCallRecord
from .token_budget import TokenBudget, BudgetStatus
from .tool_result_processor import ToolResultProcessor, ProcessedResult
from .state_injector import StateInjector

__all__ = [
    "AgentExecutor",
    "ExecutionResult",
    "LoopDetector",
    "LoopDetectionResult",
    "ToolCallRecord",
    "TokenBudget",
    "BudgetStatus",
    "ToolResultProcessor",
    "ProcessedResult",
    "StateInjector",
]
