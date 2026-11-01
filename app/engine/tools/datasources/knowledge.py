"""知识库预注入数据源 — stock_news 向量检索 + 分析报告引用校验。

预注入：分析师启动时按 (symbol, analysis_date) 检索 top-K 语料，
以 <tool_data> 注入（走 DATASOURCE_REGISTRY，分析师 data_tools 引用
knowledge_base 即启用）。as_of = 分析日期，防前视是硬约束。

引用校验：注入的引用集合登记在进程内台账（task_id::agent_key 定位），
分析师报告落板后由 orchestrator/agents.pop 校验——报告中 [序号] 必须
命中当次注入集合，无效引用剔除并计数（kb_citation_stats，记分卡数据源）。
"""

import json
import logging
import re
import threading
from typing import Dict, List, Optional, Tuple

from app.engine.tools.common.tool_result import (
    ErrorCodes,
    error_result,
    format_tool_result,
    no_data_result,
    success_result,
)

logger = logging.getLogger(__name__)


# ── 注入台账（进程内；分析异常中断的残留项由容量上限兜底清理） ──────────────

_ledger_lock = threading.Lock()
_injection_ledger: Dict[str, List[Dict]] = {}
_LEDGER_MAX_ENTRIES = 256


def make_injection_key(task_id: str, agent_key: str) -> str:
    return f"{task_id}::{agent_key}"


def record_injection(key: str, references: List[Dict]) -> None:
    with _ledger_lock:
        if len(_injection_ledger) >= _LEDGER_MAX_ENTRIES:
            for stale in list(_injection_ledger)[: len(_injection_ledger) // 2]:
                _injection_ledger.pop(stale, None)
        _injection_ledger[key] = references


def pop_injection(key: str) -> Optional[List[Dict]]:
    with _ledger_lock:
        return _injection_ledger.pop(key, None)


def _resolve_market(stock_code: str) -> str:
    from app.utils.stock_utils import StockUtils

    try:
        market_info = StockUtils.get_market_info(stock_code)
        if market_info.get("is_hk"):
            return "HK"
        if market_info.get("is_us"):
            return "US"
    except Exception as e:  # noqa: BLE001 - 检测失败按 CN 兜底
        logger.debug(f"[知识库工具] 市场类型检测失败，默认CN: {e}")
    return "CN"


def _injection_query(symbol: str, current_date: str) -> str:
    return (
        f"{symbol} {current_date or ''} 重要新闻 公告 业绩 重大事件 利好 风险 变化"
    )


def get_knowledge_base_brief(
    stock_code: str,
    current_date: Optional[str] = None,
    top_k: Optional[int] = None,
    injection_key: Optional[str] = None,
) -> str:
    """预检索知识库 top-K 语料，返回 ToolResult JSON。

    Args:
        stock_code: 股票代码（如 000001.SZ / 00700.HK / AAPL）
        current_date: 分析日期（as_of 截断，防前视）
        top_k: 返回条数（缺省取 settings.KB_EMBEDDING_TOP_K）
        injection_key: 注入台账键（task_id::agent_key），供报告落板后引用校验
    """
    if not stock_code:
        return format_tool_result(error_result(ErrorCodes.MISSING_PARAM, "未提供股票代码"))

    from app.core.async_utils import run_async
    from app.core.config import settings
    from app.data.core.interface import DataInterface

    market = _resolve_market(stock_code)
    effective_top_k = top_k or settings.KB_EMBEDDING_TOP_K

    try:
        di = DataInterface.get_instance()
        # symbol 归一与 as_of 防前视均在数据层契约内完成
        refs = run_async(
            di.kb_search(
                market, stock_code,
                _injection_query(stock_code, current_date or ""),
                as_of=current_date,
                top_k=effective_top_k,
            )
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[知识库工具] 检索失败 {stock_code}@{market}: {e}")
        return format_tool_result(error_result(ErrorCodes.DATA_FETCH_ERROR, f"知识库检索失败: {e}"))

    if not refs:
        return format_tool_result(no_data_result(
            message=f"知识库暂无 {stock_code} 可检索语料（索引未就绪、语料未同步或未配置向量模型）",
            suggestion="这是正常状态，不要重试；可基于其他新闻数据继续分析",
        ))

    references = [
        {
            "idx": i + 1,
            "title": r.get("title", ""),
            "data_source": r.get("data_source", ""),
            "publish_time": r.get("publish_time", ""),
            "type": r.get("type", "news"),
            "snippet": r.get("snippet", ""),
        }
        for i, r in enumerate(refs)
    ]
    if injection_key:
        record_injection(injection_key, references)

    payload = {
        "as_of": current_date or "",
        "references": references,
        "citation_rule": (
            "引用本组语料时必须在对应结论处标注 [序号]（如 [1]），"
            "序号只能取自 references 列表，不得引用列表之外的来源或编造序号"
        ),
    }
    logger.info(f"[知识库工具] {stock_code}@{market} 注入 {len(references)} 条（as_of={current_date}）")
    return format_tool_result(success_result(json.dumps(payload, ensure_ascii=False, indent=2)))


# ── 引用校验 ────────────────────────────────────────────────────────────────

# [数字] 且不后跟 "(" —— 避开 Markdown 链接 [text](url)；年份为 4 位数不命中
_CITATION_RE = re.compile(r"\[(\d{1,3})\](?!\()")


def validate_citations(text: str, references: List[Dict]) -> Tuple[str, Dict]:
    """校验报告引用序号 ∈ 当次注入集合。

    无效引用（越界/编造序号）从文本中剔除并计数；有效引用保留。
    返回 (清理后文本, 统计)。
    """
    max_idx = len(references)
    valid: set = set()
    invalid: List[int] = []

    def _classify(match: "re.Match") -> str:
        n = int(match.group(1))
        if 1 <= n <= max_idx:
            valid.add(n)
            return match.group(0)
        invalid.append(n)
        return ""

    cleaned = _CITATION_RE.sub(_classify, text)
    stats = {
        "injected_count": max_idx,
        "cited_refs": sorted(valid),
        "cited_count": len(valid),
        "invalid_citations": sorted(set(invalid)),
        "invalid_count": len(invalid),
    }
    return cleaned, stats
