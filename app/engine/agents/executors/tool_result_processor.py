"""
工具结果处理器

参考 claw-code conversation.rs 中的 ToolResult（带 is_error 标记）：
- 截断过长的工具返回结果
- 格式化错误消息为结构化信息，不再暗示"请重试"
- 区分成功/失败结果
"""

import json
from dataclasses import dataclass
from typing import Any

from app.utils.logging_init import get_logger

logger = get_logger("executors.tool_result_processor")

MAX_RESULT_LENGTH = 4000
MAX_ERROR_LENGTH = 1000


@dataclass
class ProcessedResult:
    """处理后的工具结果"""
    content: str
    is_error: bool = False
    original_length: int = 0
    was_truncated: bool = False

    def __str__(self) -> str:
        status = "❌" if self.is_error else "✅"
        trunc = " [已截断]" if self.was_truncated else ""
        return f"{status} {len(self.content)} 字符{trunc}"


class ToolResultProcessor:
    """
    工具结果处理器

    使用方式:
        processor = ToolResultProcessor(max_length=4000)
        result = processor.process_success(tool_result)
        result = processor.process_error(exception, tool_name)
    """

    def __init__(self, max_length: int = MAX_RESULT_LENGTH):
        self.max_length = max_length

    def format_raw(self, raw: Any) -> str:
        """将原始结果转换为字符串（供 format_tool_result 兼容调用）"""
        return self._to_string(raw)

    def process_success(self, raw: Any, tool_name: str = "") -> ProcessedResult:
        """处理成功的工具结果"""
        content = self._to_string(raw)
        original_length = len(content)
        was_truncated = False

        if len(content) > self.max_length:
            content = content[:self.max_length] + "\n...[结果已截断，原始长度: {} 字符]".format(
                original_length
            )
            was_truncated = True
            logger.debug(
                f"✂️ [ToolResultProcessor] 截断 {tool_name}: "
                f"{original_length} → {self.max_length} 字符"
            )

        return ProcessedResult(
            content=content,
            is_error=False,
            original_length=original_length,
            was_truncated=was_truncated,
        )

    def process_error(
        self,
        error: Exception,
        tool_name: str = "",
        *,
        suggest_retry: bool = False,
    ) -> ProcessedResult:
        """
        处理工具执行错误

        关键设计：错误消息不暗示"请重试"，而是明确告知 LLM 换用其他方法或直接报告。
        参考 claw-code: ToolResult { is_error: true } 让 LLM 理解这是不可恢复的失败。

        Args:
            error: 异常对象
            tool_name: 工具名称
            suggest_retry: 是否建议重试（仅对超时/网络错误为 True）
        """
        error_type = type(error).__name__
        error_msg = str(error)

        # 根据错误类型决定建议
        if isinstance(error, TimeoutError) or suggest_retry:
            suggestion = "该工具暂时响应超时。可以稍后重试一次，或尝试其他工具获取数据。"
        elif isinstance(error, (ConnectionError,)):
            suggestion = "网络连接失败。请尝试其他工具或基于已有数据继续分析。"
        elif isinstance(error, (ValueError, TypeError)):
            suggestion = "参数格式不正确，请检查参数。如无法修正，请换用其他工具。"
        else:
            suggestion = "请换用其他工具获取数据，或基于已有信息继续分析。"

        content = (
            f"=== ⚠️ 工具执行错误 ===\n"
            f"工具: {tool_name}\n"
            f"错误类型: {error_type}\n"
            f"错误信息: {error_msg[:500]}\n"
            f"=== 💡 建议 ===\n"
            f"{suggestion}"
        )

        if len(content) > MAX_ERROR_LENGTH:
            content = content[:MAX_ERROR_LENGTH] + "\n...[错误信息已截断]"

        return ProcessedResult(
            content=content,
            is_error=True,
            original_length=len(error_msg),
        )

    def process_not_found(self, tool_name: str) -> ProcessedResult:
        """处理工具未找到的情况"""
        return ProcessedResult(
            content=(
                f"=== ⚠️ 工具未找到 ===\n"
                f"工具 '{tool_name}' 不在当前可用工具列表中。\n"
                f"请使用其他可用工具，或直接基于已有信息生成分析报告。"
            ),
            is_error=True,
        )

    def _to_string(self, raw: Any) -> str:
        """将任意类型转换为字符串"""
        if raw is None:
            return ""
        if isinstance(raw, str):
            return raw
        if isinstance(raw, (dict, list)):
            try:
                return json.dumps(raw, ensure_ascii=False, indent=2)
            except (TypeError, ValueError):
                return str(raw)
        return str(raw)
