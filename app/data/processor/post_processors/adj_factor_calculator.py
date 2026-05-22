"""复权因子推导器 — 基于 corporate_actions 计算复权因子（美股）。"""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class AdjFactorCalculator:
    """从公司行为推导复权因子。"""

    def calculate_from_corporate_actions(
        self, actions: List[Dict], base_factor: float = 1.0
    ) -> List[Dict]:
        """基于公司行为列表计算每日复权因子。

        Args:
            actions: CorporateActions 文档列表，按 ex_date 升序
            base_factor: 初始复权因子（通常为 1.0）

        Returns:
            AdjFactors 文档列表
        """
        if not actions:
            return []

        result = []
        factor = base_factor

        for action in actions:
            action_type = action.get("action_type")
            if action_type in ("cash_dividend", "special_dividend"):
                amount = action.get("amount", 0) or 0
                if amount > 0:
                    # 简化处理: factor *= (1 - dividend/price)
                    factor *= (1 - amount / (amount + factor))

            elif action_type == "stock_split":
                ratio_from = action.get("ratio_from", 1) or 1
                ratio_to = action.get("ratio_to", 1) or 1
                if ratio_from > 0:
                    factor *= ratio_to / ratio_from

            elif action_type == "reverse_split":
                ratio_from = action.get("ratio_from", 1) or 1
                ratio_to = action.get("ratio_to", 1) or 1
                if ratio_from > 0:
                    factor *= ratio_to / ratio_from

            elif action_type == "bonus_issue":
                ratio_from = action.get("ratio_from", 1) or 1
                ratio_to = action.get("ratio_to", 1) or 1
                if ratio_from > 0:
                    factor *= ratio_to / (ratio_from + ratio_to)

            elif action_type == "rights_issue":
                ratio_from = action.get("ratio_from", 1) or 1
                ratio_to = action.get("ratio_to", 1) or 1
                rights_price = action.get("rights_price", 0) or 0
                if ratio_from > 0 and rights_price > 0:
                    factor *= (ratio_from + ratio_to) / (ratio_from + ratio_to * rights_price)

            result.append({
                "symbol": action.get("symbol"),
                "trade_date": action.get("ex_date"),
                "adj_factor": round(factor, 6),
                "fore_adj_factor": round(factor, 6),
                "market": action.get("market", "US"),
                "data_source": "local_derived",
                "updated_at": action.get("updated_at"),
            })

        return result
