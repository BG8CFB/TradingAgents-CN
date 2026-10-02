"""A 股报告期公共工具 — CN 各源共享（tushare/akshare 批量财务均按报告期查询）。"""

from datetime import date
from typing import List, Optional

_QUARTER_ENDS = ((12, 31), (9, 30), (6, 30), (3, 31))


def recent_report_periods(n: int = 5, today: Optional[str] = None) -> List[str]:
    """滚动最近 n 个已过报告期（YYYYMMDD，倒序）。

    最新一期可能尚未披露完——按报告期查询只返回已披露公司，每日重拉
    配合 upsert 同键覆盖，天然补上迟披露的公司，无需单独回填。
    """
    d = date.fromisoformat(today) if today else date.today()
    periods: List[str] = []
    year = d.year
    while len(periods) < n:
        for m, day in _QUARTER_ENDS:
            if date(year, m, day) < d:
                periods.append(f"{year}{m:02d}{day:02d}")
                if len(periods) == n:
                    break
        year -= 1
    return periods
