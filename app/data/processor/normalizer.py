"""标准化执行器 — 调用 Adapter 方法转换原始数据。"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# 域 → adapt 方法名映射
DOMAIN_METHOD_MAP = {
    "basic_info": "adapt_basic_info",
    "trade_calendar": "adapt_trade_calendar",
    "daily_quotes": "adapt_daily_quotes",
    "daily_indicators": "adapt_daily_indicators",
    "financial_data": "adapt_financial_data",
    "adj_factors": "adapt_adj_factors",
    "corporate_actions": "adapt_corporate_actions",
    "news": "adapt_news",
    "market_quotes": "adapt_market_quotes",
}


class Normalizer:
    """标准化执行器。调用 Adapter 的 adapt 方法将原始数据转为标准文档。"""

    def normalize(self, raw_data: Any, domain: str, adapter) -> List[Dict]:
        """标准化原始数据。

        Args:
            raw_data: Provider 返回的原始 DataFrame/Dict
            domain: 数据域
            adapter: BaseAdapter 实例

        Returns:
            标准化后的文档列表
        """
        method_name = DOMAIN_METHOD_MAP.get(domain)
        if not method_name:
            logger.warning(f"未知域: {domain}")
            return []

        method = getattr(adapter, method_name, None)
        if not method:
            logger.warning(f"Adapter {adapter.source_name} 无方法 {method_name}")
            return []

        try:
            schemas = method(raw_data)
            if not schemas:
                return []
            return [s.to_db_doc() for s in schemas]
        except NotImplementedError:
            logger.debug(f"Adapter {adapter.source_name} 不支持 {domain}")
            return []
        except Exception as e:
            logger.warning(f"标准化 {domain} 失败 ({adapter.source_name}): {e}")
            return []
