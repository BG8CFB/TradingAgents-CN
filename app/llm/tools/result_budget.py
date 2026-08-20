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
    limit = max_chars if max_chars is not None else DEFAULT_MAX_RESULT_CHARS
    if len(result) <= limit:
        return result

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

    logger.info(f"📦 [result_budget] {name} 结果 {len(result)} 字符超限 {limit}，已落盘: {path}")
    return (
        f"{result[:PREVIEW_CHARS]}\n"
        f"...[结果共 {len(result)} 字符，已截断。完整结果已保存：{path}]"
    )
