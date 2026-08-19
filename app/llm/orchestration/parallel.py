"""
并行 fan-out：多个独立对话任务并发执行（asyncio.gather）

给上层分析流水线用（如多个分析师并行分析同一标的）。
参考 claude-code 的并行子代理派发模式。
"""

import asyncio
from dataclasses import dataclass, field
from typing import List, Optional

from app.utils.logging_init import get_logger

from ..core.base import BaseLLMClient
from ..core.types import Message
from ..runner import RunResult, run_conversation

logger = get_logger("app.llm.orchestration.parallel")


@dataclass
class ParallelResult:
    """fan-out 结果：与任务一一对应；单个任务异常不中断其他任务（对应位为 None）"""

    results: List[Optional[RunResult]] = field(default_factory=list)

    @property
    def succeeded(self) -> List[RunResult]:
        return [r for r in self.results if r is not None]


async def gather_conversations(
    client: BaseLLMClient,
    tasks: List[dict],
    *,
    concurrency: int = 5,
) -> ParallelResult:
    """并发执行多个 run_conversation。

    Args:
        client: 共享的协议客户端
        tasks: 每项是 run_conversation 的关键字参数字典，至少含 user_message
        concurrency: 最大并发数（信号量限流）
    """
    sem = asyncio.Semaphore(concurrency)

    async def _run(task_kwargs: dict) -> Optional[RunResult]:
        async with sem:
            try:
                return await run_conversation(client, **task_kwargs)
            except Exception as e:  # noqa: BLE001 - 单任务失败不拖垮整批
                logger.error(f"❌ [parallel] 任务失败: {e}", exc_info=True)
                return None

    results = await asyncio.gather(*(_run(t) for t in tasks))
    ok = sum(1 for r in results if r is not None)
    logger.info(f"🔀 [parallel] fan-out 完成: {ok}/{len(results)} 成功")
    return ParallelResult(results=list(results))


def merge_histories(results: "ParallelResult", separator: str = "\n\n---\n\n") -> List[Message]:
    """把多个子任务的最终报告合并为一条 user 消息（供后续裁决/汇总对话使用）"""
    from ..core.types import Role

    parts = []
    for i, r in enumerate(results.results):
        if r is None:
            parts.append(f"## 任务 {i + 1}\n（执行失败）")
        else:
            parts.append(f"## 任务 {i + 1}\n{r.final_text or '（无输出）'}")
    return [Message(role=Role.USER, content=separator.join(parts))]
