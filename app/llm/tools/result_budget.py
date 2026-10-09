"""工具结果预算：超限落盘 + 预览引用（对齐 claude-code 的 maxResultSizeChars 模式）。

原则：大结果不硬截断丢失，全文原子落盘到 runtime 工件目录，
模型收到短预览 + 完整结果文件路径——上下文不被大输出撑爆，信息也不丢。
"""

import re
import threading
from typing import Optional

import logging
from app.utils.runtime_paths import ensure_subdir

logger = logging.getLogger("app.llm.tools.result_budget")

# 默认阈值：超过则落盘（MCP 等场景可各自覆盖）
DEFAULT_MAX_RESULT_CHARS = 30_000
# 回传给模型的预览长度
PREVIEW_CHARS = 2_000
# 工具名清洗（文件名安全）
_UNSAFE = re.compile(r"[^a-zA-Z0-9_.-]")

_seq_lock = threading.Lock()
_seq_counter = 0


def _next_seq() -> int:
    global _seq_counter
    with _seq_lock:
        _seq_counter += 1
        return _seq_counter


def _safe_name(name: str) -> str:
    cleaned = _UNSAFE.sub("_", name)[:64]
    return cleaned or "tool"


def apply_result_budget(
    name: str,
    result: str,
    *,
    task_id: str = "",
    max_chars: Optional[int] = None,
) -> str:
    """对工具结果应用预算：未超限原样返回；超限落盘并返回预览 + 文件路径。

    Args:
        name: 工具名（用于工件文件命名）
        result: 工具结果的字符串形式
        task_id: 任务 ID（工件目录隔离；缺省归入 adhoc/）
        max_chars: 阈值覆盖，缺省 DEFAULT_MAX_RESULT_CHARS
    """
    limit = max_chars if max_chars and max_chars > 0 else DEFAULT_MAX_RESULT_CHARS
    if len(result) <= limit:
        return result
    # 硬上限：单个工具结果过大时截断，防止上下文被撑爆。
    # 实测：中国市场分析师的消息体累积到 1,144,006 tokens 被 API 拒绝
    # （"maximum context length is 1048576 tokens"），整位分析师直接中断。
    # 与旧版"落盘 + 2K 预览"不同：这里保留前 limit 字符并**显式标注已截断**，
    # 模型能明确知道数据不完整（旧版正因静默截断、模型误当全量而停用）。
    return (
        result[:limit]
        + f"\n\n⚠️【结果已截断】原始返回 {len(result):,} 字符，此处仅保留前 {limit:,} 字符。"
        "如需完整数据，请改用带过滤条件（如 ts_code / trade_date / date / symbols）的"
        "查询缩小范围，或分批次获取。"
    )

    seq = _next_seq()
    scope = _safe_name(task_id or "adhoc")
    try:
        artifacts_dir = ensure_subdir(f"artifacts/tool-results/{scope}")
        path = artifacts_dir / f"{_safe_name(name)}-{seq}.txt"
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(result, encoding="utf-8")
        tmp.replace(path)  # 原子写
    except OSError as e:  # 落盘失败退化为纯截断，绝不因预算机制丢掉整次调用
        logger.warning(f"⚠️ [result_budget] {name} 落盘失败，退化为截断: {e}")
        return result[:PREVIEW_CHARS] + f"\n...[结果共 {len(result)} 字符，已截断（落盘失败）]"

    logger.info(f"📦 [result_budget] {name} 结果 {len(result)} 字符超限，已落盘: {path}")
    return (
        f"{result[:PREVIEW_CHARS]}\n"
        f"...[结果共 {len(result)} 字符，已截断。完整结果已保存：{path}]"
    )
