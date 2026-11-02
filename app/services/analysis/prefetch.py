"""数据预取（自 analysis_service.py 拆分）。

职责：分析执行前把该股票在该市场的全部支持数据域拉取入 MongoDB，
保证分析过程数据命中标准库；含符号规范化（与 schema normalize_symbol 一致）。
"""

import logging
from typing import Dict

from app.data.core.interface import DataInterface

logger = logging.getLogger(__name__)


class PrefetchMixin:
    """数据预取 mixin：分析前的全域数据拉取。"""

    @staticmethod
    def _normalize_symbol_for_data(symbol: str, market: str) -> str:
        """规范化股票代码以匹配数据库存储格式（与 schema normalize_symbol 一致）"""
        symbol = (symbol or "").strip()
        if market == "CN":
            return symbol.replace(".SZ", "").replace(".SH", "").replace(".BJ", "").zfill(6)
        if market == "HK":
            return symbol.replace(".HK", "").replace(".hk", "").zfill(5)
        return symbol.upper()

    def _prefetch_stock_data(
        self,
        market: str,
        symbol: str,
    ) -> Dict[str, str]:
        """预拉取该股票在该市场的所有支持数据域到 MongoDB。

        拉取 DataRefreshService 支持的全部按需刷新域（不依赖分析师选择），
        确保分析过程中所有数据都从 MongoDB 命中。

        Args:
            market: 市场标识 (CN/HK/US)
            symbol: 股票代码

        Returns:
            各域的刷新状态 {domain: status}
        """
        from app.core.async_utils import run_async

        # 传入 domains=None，由 DataRefreshService 拉取全部支持的域
        di = DataInterface.get_instance()
        result = run_async(
            di.refresh(
                market,
                symbol,
                domains=None,  # None = 全部支持的域
                force=False,  # 有缓存就跳过
                timeout=60,
            )
        )

        # 记录结果摘要
        domain_statuses = {}
        for domain, dr in result.domains.items():
            domain_statuses[domain] = dr.status
            if dr.status == "failed":
                logger.warning(f"📊 [数据预拉取] {domain} 失败: {dr.error}")
            else:
                logger.info(f"📊 [数据预拉取] {domain}: {dr.status} ({dr.record_count} 条, {dr.latency_ms}ms)")

        refreshed = sum(1 for s in domain_statuses.values() if s == "refreshed")
        fresh = sum(1 for s in domain_statuses.values() if s == "fresh")
        failed = sum(1 for s in domain_statuses.values() if s in ("failed", "timeout"))
        logger.info(f"📊 [数据预拉取] 完成: {refreshed} 个域刷新, {fresh} 个域已是最新, {failed} 个域失败")

        return domain_statuses
