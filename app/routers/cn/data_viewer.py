# data-access-exempt: 调 Reader 私有方法 _latest_sort_field；待上提为 DataInterface 公开能力后移除
"""数据查看器分页工具 — 三市场 /stock/{symbol} 抽样校验共用。

问题背景：Reader 各域仓储的返回排序不统一（daily_quotes 升序、
daily_indicators/money_flow 降序），查看器路由若直接按列表头部分页，
升序域会展示"最旧 N 条"，与前端"仅展示最新记录"文案矛盾。

方案：分页前按域的排序键统一降序（最新在前），排序键复用
Reader._LATEST_SORT_FIELDS 的既有映射（trade_date/report_period/
updated_at 等），与 read_latest 的"最新一条"语义一致；无排序键的
记录排尾部，保持稳定输出。
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _sort_records_desc(records: List[Dict], sort_field: str) -> List[Dict]:
    """按 sort_field 降序排序；键缺失/不可比较的记录稳定排尾部。"""

    def _key(rec: Dict):
        val = rec.get(sort_field)
        if val is None or val == "":
            return (0, "")
        if isinstance(val, (int, float)):
            return (1, val)
        return (1, str(val))

    return sorted(records, key=_key, reverse=True)


def paginate_domain_items(
    domain: str,
    data: Any,
    page: int,
    page_size: int,
) -> Dict:
    """按域排序键降序后分页，返回查看器条目结构。

    Args:
        domain: 数据域（用于推导排序键）
        data: di.read 返回的 data（列表或单条 dict）
        page: 页码（1 起）
        page_size: 每页条数

    Returns:
        {"total": 总条数, "items": 当前页记录}
    """
    from app.data.core.reader import Reader

    sort_field = Reader._latest_sort_field(domain)
    if isinstance(data, list):
        ordered = _sort_records_desc(data, sort_field) if data else []
        total = len(ordered)
        start = (page - 1) * page_size
        return {"total": total, "items": ordered[start:start + page_size]}
    return {"total": 1, "items": [data] if data else []}


__all__ = ["paginate_domain_items"]
