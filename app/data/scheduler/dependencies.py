"""依赖链管理 — 拓扑排序。"""

import logging
from typing import Dict, List, Set

logger = logging.getLogger(__name__)


class DependencyGraph:
    """数据域依赖图。"""

    def __init__(self):
        self._deps: Dict[str, Set[str]] = {}

    def add_dependency(self, domain: str, depends_on: str) -> None:
        if domain not in self._deps:
            self._deps[domain] = set()
        self._deps[domain].add(depends_on)

    def get_execution_order(self, domains: List[str]) -> List[List[str]]:
        """拓扑排序，返回并行组列表。

        Returns:
            [[独立组1], [依赖组2], [依赖组3], ...]
        """
        # 简化实现: 按依赖层数分组
        remaining = set(domains)
        result = []
        completed = set()

        while remaining:
            # 找出无未满足依赖的域
            ready = []
            for d in remaining:
                deps = self._deps.get(d, set())
                if not deps or all(dep in completed or dep not in remaining for dep in deps):
                    ready.append(d)

            if not ready:
                # 循环依赖，强制加入剩余
                ready = list(remaining)

            result.append(ready)
            completed.update(ready)
            remaining -= set(ready)

        return result
