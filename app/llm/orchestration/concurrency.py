"""
工具并发分区（参考 claude-code toolOrchestration.ts 的 partitionToolCalls）

规则：
- 对同一条 assistant 消息内的 tool_use 按序贪心分批：
  连续的"并发安全"工具合一批并发执行（上限 MAX_TOOL_CONCURRENCY），
  非安全工具（写操作）单独成批串行执行
- 批间严格保序（保持模型意图的顺序依赖）
- 未知工具按非安全处理（保守）
"""

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, List, Sequence, TypeVar

from app.utils.logging_init import get_logger

from ..core.types import ToolUseBlock

logger = get_logger("app.llm.orchestration")

MAX_TOOL_CONCURRENCY = 10  # 参考 claude-code CLAUDE_CODE_MAX_TOOL_USE_CONCURRENCY 默认值

T = TypeVar("T")


@dataclass
class ToolBatch:
    """一批工具调用：concurrent=True 时批内可并发"""

    items: List[ToolUseBlock]
    concurrent: bool


def _is_concurrency_safe(tu: ToolUseBlock, lookup: Callable[[str], bool]) -> bool:
    try:
        return bool(lookup(tu.name))
    except Exception:  # noqa: BLE001 - 判定异常按保守处理（对齐参考项目）
        return False


def partition_tool_calls(
    tool_uses: Sequence[ToolUseBlock],
    lookup: Callable[[str], bool],
) -> List[ToolBatch]:
    """贪心分批：连续安全工具合并，非安全工具单批。lookup(name) 返回该工具是否并发安全。"""
    batches: List[ToolBatch] = []
    for tu in tool_uses:
        safe = _is_concurrency_safe(tu, lookup)
        if safe and batches and batches[-1].concurrent and len(batches[-1].items) < MAX_TOOL_CONCURRENCY:
            batches[-1].items.append(tu)
        else:
            batches.append(ToolBatch(items=[tu], concurrent=safe))
    return batches


async def run_batches(
    batches: List[ToolBatch],
    executor: Callable[[ToolUseBlock], Awaitable[str]],
) -> List[str]:
    """按批执行：并发批 asyncio.gather，串行批逐个执行；返回与输入顺序一致的结果列表。"""
    results: List[str] = []
    for batch in batches:
        if batch.concurrent and len(batch.items) > 1:
            batch_results = await asyncio.gather(*(executor(tu) for tu in batch.items))
            logger.info(f"⚡ [orchestration] 并发执行 {len(batch.items)} 个只读工具")
            results.extend(batch_results)
        else:
            for tu in batch.items:
                results.append(await executor(tu))
    return results
