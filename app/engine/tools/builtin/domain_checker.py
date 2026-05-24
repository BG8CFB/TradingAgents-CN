"""
数据域可用性检测器

替代旧的 availability.py（只看 YAML 配置），改为实际查询 MongoDB 记录数。
提供两层检测：
1. 标准域：查 MongoDB 集合记录数
2. 非标准域：检测 AKShare 可导入性或自定义策略
"""
import logging
import time
import threading
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class DomainAvailabilityChecker:
    """数据域可用性检测器（async）"""

    def __init__(self):
        self._standard_domains = self._load_standard_domains()

    def _load_standard_domains(self) -> set:
        """加载标准域名称集合"""
        try:
            from app.data.storage.mongo.collections import _BUSINESS_COLLECTIONS
            return set(_BUSINESS_COLLECTIONS.keys())
        except Exception:
            return set()

    async def check_domain(self, market: str, domain: str) -> bool:
        """检查单个域是否有数据"""
        try:
            from app.data.core.interface import DataInterface
            di = DataInterface.get_instance()
            stats = await di.get_domain_stats(market, [domain])
            count = stats.get(domain, {}).get("records", 0)
            return count > 0
        except Exception:
            return False

    async def batch_check_domains(
        self, market: str, domains: List[str]
    ) -> Dict[str, bool]:
        """批量检测域状态，返回 {domain: has_data}"""
        if not domains:
            return {}

        try:
            from app.data.core.interface import DataInterface
            di = DataInterface.get_instance()
            stats = await di.get_domain_stats(market, domains)
            return {
                d: stats.get(d, {}).get("records", 0) > 0
                for d in domains
            }
        except Exception as e:
            logger.warning(f"批量域检测失败: {e}")
            return {d: False for d in domains}

    async def check_tool(
        self, spec, market: str, domain_status: Dict[str, bool]
    ) -> bool:
        """检查单个工具是否可用"""
        if market not in spec.markets:
            return False

        if spec.non_standard:
            return self._check_non_standard(spec)

        if not spec.domains:
            return True

        return all(domain_status.get(d, False) for d in spec.domains)

    async def batch_check(
        self, specs: list, market: str
    ) -> Dict[str, bool]:
        """批量检测所有工具的可用性"""
        # 收集所有标准域
        standard_domains = set()
        for spec in specs:
            if not spec.non_standard:
                standard_domains.update(spec.domains)

        # 一次性查 MongoDB
        domain_status = await self.batch_check_domains(market, list(standard_domains))

        # 逐工具判定
        results = {}
        for spec in specs:
            results[spec.tool_id] = await self.check_tool(spec, market, domain_status)

        available_count = sum(1 for v in results.values() if v)
        logger.info(
            f"[DomainChecker] 市场={market}, "
            f"可用={available_count}/{len(results)}, "
            f"域状态={domain_status}"
        )
        return results

    def _check_non_standard(self, spec) -> bool:
        """非标准域的可用性检查"""
        check = spec.availability_check
        if check == "akshare_alive":
            try:
                import akshare
                return True
            except ImportError:
                return False
        return True


class AvailabilityCache:
    """
    预计算的可用性缓存（sync 读取）

    在 analysis_service 的 async 上下文中预计算好各工具的可用性状态，
    后续 sync 的 _inject_tool_data 直接读取缓存。
    """

    _instance: Optional["AvailabilityCache"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._tool_availability: Dict[str, bool] = {}
        self._market: str = ""
        self._computed_at: float = 0

    @classmethod
    def get_instance(cls) -> "AvailabilityCache":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls):
        with cls._lock:
            cls._instance = None

    async def compute(self, market: str, specs: list) -> None:
        """异步预计算所有工具的可用性"""
        checker = DomainAvailabilityChecker()
        self._tool_availability = await checker.batch_check(specs, market)
        self._market = market
        self._computed_at = time.time()

        available = sum(1 for v in self._tool_availability.values() if v)
        unavailable = len(self._tool_availability) - available
        logger.info(
            f"[AvailabilityCache] 市场={market}, "
            f"可用={available}, 不可用={unavailable}, "
            f"详情={self._tool_availability}"
        )

    def is_available(self, tool_id: str) -> bool:
        """同步查询工具可用性"""
        return self._tool_availability.get(tool_id, False)

    def get_unavailable_ids(self, tool_ids: List[str]) -> List[str]:
        """从指定列表中筛选不可用工具"""
        return [tid for tid in tool_ids if not self._tool_availability.get(tid, False)]

    def get_available_ids(self, tool_ids: List[str]) -> List[str]:
        """从指定列表中筛选可用工具"""
        return [tid for tid in tool_ids if self._tool_availability.get(tid, False)]

    @property
    def market(self) -> str:
        return self._market

    @property
    def all_results(self) -> Dict[str, bool]:
        return dict(self._tool_availability)
