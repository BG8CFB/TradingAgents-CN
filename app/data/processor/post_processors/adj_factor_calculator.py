"""复权因子推导器 — 基于 corporate_actions 计算复权因子（A股/美股）。

支持 5 种权益变动的标准公式（向后累积）：
1. **现金分红 / 特别分红**（cash_dividend / special_dividend）：
   factor *= (prev_close - amount) / prev_close
   需要除权前一日收盘价 prev_close。

2. **送股 / 转增**（bonus_issue / capital_reserve_increase）：
   factor *= ratio_from / (ratio_from + ratio_to)
   解释：每 ratio_from 股送 ratio_to 股，旧股价值按总股本扩大比例稀释。
   例：10 送 10（from=10, to=10），factor *= 10/(10+10) = 0.5

3. **配股**（rights_issue）：
   factor *= (ratio_from * prev_close + ratio_to * rights_price)
            / ((ratio_from + ratio_to) * prev_close)
   解释：每 ratio_from 股配 ratio_to 股，配股价 rights_price 通常低于市价。
   prev_close 为除权前一日收盘价。

4. **减资 / 回购**（share_buyback / capital_reduction）：
   factor *= (ratio_from * prev_close - ratio_to * buyback_price)
            / ((ratio_from - ratio_to) * prev_close)
   解释：每 ratio_from 股回购 ratio_to 股，回购价 buyback_price。
   总股本减少，旧股价值按比例放大。

5. **拆股 / 合股**（stock_split / reverse_split）：
   factor *= ratio_to / ratio_from
   例：1 拆 10（from=1, to=10），factor *= 10

字段语义（重要）：
    - ``adj_factor``：**向后复权因子**，保留原始累积值（最新一日 ≠ 1.0）。
      用于历史价格向后调整：``向后复权价 = 原始价 × adj_factor``。
    - ``fore_adj_factor``：**前复权因子**，已归一化使**最新一日 = 1.0**。
      用于把历史价格向前调整到当前基准：``前复权价 = 原始价 × fore_adj_factor``。
      归一化方式：``fore = adj × (1.0 / result[-1].adj)``。

调用方需在 action dict 中填充 `prev_close`（除权前一日收盘价），
否则 cash_dividend / rights_issue / share_buyback 将跳过（保留前一次 factor）。

异步版本（``calculate_from_corporate_actions_async``）会在 prev_close 缺失时
自动通过传入的 ``PrevCloseLookup`` 回退查询 T-1 收盘价。
"""

import logging
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from app.data.processor.post_processors.prev_close_lookup import PrevCloseLookup

logger = logging.getLogger(__name__)

# 需要 prev_close 才能计算复权因子的 action_type 集合
_ACTION_TYPES_NEED_PREV_CLOSE = frozenset({
    "cash_dividend",
    "special_dividend",
    "rights_issue",
    "share_buyback",
    "capital_reduction",
})


class AdjFactorCalculator:
    """从公司行为推导复权因子。"""

    def calculate_from_corporate_actions(
        self, actions: List[Dict], base_factor: float = 1.0
    ) -> List[Dict]:
        """基于公司行为列表计算每日复权因子（同步版本）。

        Args:
            actions: CorporateActions 文档列表，按 ex_date 升序
                每条 action 可包含：
                - symbol, ex_date, action_type
                - amount: 现金分红金额（每股）
                - ratio_from / ratio_to: 送股/配股/拆股比例
                - rights_price / buyback_price: 配股/回购价
                - prev_close: 除权前一日收盘价（用于现金分红/配股/回购）
            base_factor: 初始复权因子（通常为 1.0）

        Returns:
            AdjFactors 文档列表
        """
        if not actions:
            return []

        # 防御性排序：累积算法依赖 ex_date 升序（最新一日在最后用于归一化基准）
        # 即使上游契约已要求升序，这里仍做一次浅拷贝排序，避免外部 list 被原地修改
        actions = sorted(actions, key=lambda a: str(a.get("ex_date", "")))

        result: List[Dict] = []
        factor = float(base_factor)

        for action in actions:
            action_type = action.get("action_type")
            new_factor = self._apply_single_action(factor, action)
            if new_factor is None:
                # 公式所需字段缺失（如 prev_close），跳过但保留前一次 factor
                logger.warning(
                    "复权因子计算跳过 action_type=%s symbol=%s ex_date=%s "
                    "（字段缺失或为零）",
                    action_type,
                    action.get("symbol"),
                    action.get("ex_date"),
                )
                # 不 append 该日记录，避免与下一日混淆
                continue
            factor = new_factor

            result.append({
                "symbol": action.get("symbol"),
                "trade_date": action.get("ex_date"),
                "adj_factor": round(factor, 6),
                # 临时占位，函数末尾统一归一化（保证最新一日 = 1.0）
                "fore_adj_factor": round(factor, 6),
                "market": action.get("market", "US"),
                "data_source": "local_derived",
                "updated_at": action.get("updated_at"),
            })

        _normalize_fore_adj_factor(result)
        return result

    async def calculate_from_corporate_actions_async(
        self,
        actions: List[Dict],
        base_factor: float = 1.0,
        lookup: Optional["PrevCloseLookup"] = None,
    ) -> List[Dict]:
        """基于公司行为列表计算每日复权因子（异步版本）。

        与同步版本的区别：当 action_type 属于需要 prev_close 的类型
        但 action dict 未填充 prev_close 时，会通过传入的 ``PrevCloseLookup``
        自动回查 T-1 收盘价；如果 lookup 也返回 None，仍保留"跳过"语义。

        Args:
            actions: CorporateActions 文档列表，按 ex_date 升序
            base_factor: 初始复权因子
            lookup: 可选的 T-1 收盘价查询器；为 None 时回退为同步版本行为

        Returns:
            AdjFactors 文档列表
        """
        if not actions:
            return []

        # 防御性排序（与同步版本一致）
        actions = sorted(actions, key=lambda a: str(a.get("ex_date", "")))

        result: List[Dict] = []
        factor = float(base_factor)

        for action in actions:
            action_type = action.get("action_type")

            # 仅对需要 prev_close 的 action_type 触发回查；其他类型直接计算
            if (
                lookup is not None
                and action_type in _ACTION_TYPES_NEED_PREV_CLOSE
                and not _has_valid_prev_close(action)
            ):
                symbol = action.get("symbol")
                ex_date = action.get("ex_date")
                prev_close = await lookup.get(symbol, ex_date) if symbol and ex_date else None
                if prev_close is not None:
                    # 回填 prev_close 后继续走原公式；不修改原 dict 防止外部依赖
                    action = {**action, "prev_close": prev_close}

            new_factor = self._apply_single_action(factor, action)
            if new_factor is None:
                logger.warning(
                    "复权因子计算跳过 action_type=%s symbol=%s ex_date=%s "
                    "（字段缺失或为零，prev_close 查询无结果）",
                    action_type,
                    action.get("symbol"),
                    action.get("ex_date"),
                )
                continue
            factor = new_factor

            result.append({
                "symbol": action.get("symbol"),
                "trade_date": action.get("ex_date"),
                "adj_factor": round(factor, 6),
                # 临时占位，函数末尾统一归一化（保证最新一日 = 1.0）
                "fore_adj_factor": round(factor, 6),
                "market": action.get("market", "US"),
                "data_source": "local_derived",
                "updated_at": action.get("updated_at"),
            })

        _normalize_fore_adj_factor(result)
        return result

    # ------------------------------------------------------------------
    # 单步公式
    # ------------------------------------------------------------------

    def _apply_single_action(
        self, current_factor: float, action: Dict
    ) -> Optional[float]:
        """根据单个公司行为计算累积后的新 factor。

        Returns:
            新 factor（float）；None 表示该 action 无法应用（字段缺失）
        """
        action_type = action.get("action_type")

        if action_type in ("cash_dividend", "special_dividend"):
            return self._apply_cash_dividend(current_factor, action)

        if action_type in ("bonus_issue", "capital_reserve_increase"):
            return self._apply_bonus_issue(current_factor, action)

        if action_type == "rights_issue":
            return self._apply_rights_issue(current_factor, action)

        if action_type in ("share_buyback", "capital_reduction"):
            return self._apply_share_buyback(current_factor, action)

        if action_type in ("stock_split", "reverse_split"):
            return self._apply_stock_split(current_factor, action)

        # 未知 action_type：保留前一次 factor，不算错误
        logger.debug("未知 action_type=%s，复权因子不变", action_type)
        return current_factor

    def _apply_cash_dividend(
        self, current_factor: float, action: Dict
    ) -> Optional[float]:
        """现金分红：factor *= (prev_close - amount) / prev_close"""
        amount = action.get("amount", 0) or 0
        prev_close = action.get("prev_close")
        if amount <= 0:
            return current_factor  # 无分红
        if not prev_close or prev_close <= 0:
            return None  # 无法计算
        return current_factor * (prev_close - amount) / prev_close

    def _apply_bonus_issue(
        self, current_factor: float, action: Dict
    ) -> Optional[float]:
        """送股/转增：factor *= ratio_from / (ratio_from + ratio_to)

        例：10 送 10（from=10, to=10）→ factor *= 0.5
        解释：旧 10 股拆为新 20 股，旧 1 股代表新 2 股，价值减半。
        """
        ratio_from = action.get("ratio_from") or 0
        ratio_to = action.get("ratio_to") or 0
        if ratio_from <= 0 or ratio_to <= 0:
            return None
        return current_factor * ratio_from / (ratio_from + ratio_to)

    def _apply_rights_issue(
        self, current_factor: float, action: Dict
    ) -> Optional[float]:
        """配股：factor *= (ratio_from * prev_close + ratio_to * rights_price)
                            / ((ratio_from + ratio_to) * prev_close)
        """
        ratio_from = action.get("ratio_from") or 0
        ratio_to = action.get("ratio_to") or 0
        rights_price = action.get("rights_price") or 0
        prev_close = action.get("prev_close")
        if ratio_from <= 0 or ratio_to <= 0 or rights_price <= 0:
            return None
        if not prev_close or prev_close <= 0:
            return None
        numerator = ratio_from * prev_close + ratio_to * rights_price
        denominator = (ratio_from + ratio_to) * prev_close
        if denominator <= 0:
            return None
        return current_factor * numerator / denominator

    def _apply_share_buyback(
        self, current_factor: float, action: Dict
    ) -> Optional[float]:
        """减资/回购：factor *= (ratio_from * prev_close - ratio_to * buyback_price)
                            / ((ratio_from - ratio_to) * prev_close)
        """
        ratio_from = action.get("ratio_from") or 0
        ratio_to = action.get("ratio_to") or 0
        buyback_price = action.get("buyback_price") or 0
        prev_close = action.get("prev_close")
        if ratio_from <= 0 or ratio_to <= 0 or buyback_price <= 0:
            return None
        if ratio_from - ratio_to <= 0:
            return None  # 减资比例异常
        if not prev_close or prev_close <= 0:
            return None
        numerator = ratio_from * prev_close - ratio_to * buyback_price
        denominator = (ratio_from - ratio_to) * prev_close
        if denominator <= 0:
            return None
        return current_factor * numerator / denominator

    def _apply_stock_split(
        self, current_factor: float, action: Dict
    ) -> Optional[float]:
        """拆股 / 合股：factor *= ratio_to / ratio_from

        stock_split：ratio_from=1, ratio_to=10 → 1 拆 10 → factor *= 10
        reverse_split：ratio_from=10, ratio_to=1 → 10 合 1 → factor *= 0.1
        """
        ratio_from = action.get("ratio_from") or 0
        ratio_to = action.get("ratio_to") or 0
        if ratio_from <= 0 or ratio_to <= 0:
            return None
        return current_factor * ratio_to / ratio_from


def _has_valid_prev_close(action: Dict) -> bool:
    """判断 action 中是否已包含有效 prev_close（>0 的数值）。"""
    value = action.get("prev_close")
    if value is None:
        return False
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def _normalize_fore_adj_factor(result: List[Dict]) -> None:
    """对 result 中所有记录的 ``fore_adj_factor`` 做"最新一日 = 1.0"归一化（in-place）。

    背景：
        循环中 ``fore_adj_factor`` 与 ``adj_factor`` 共用累积值（向后累积），
        最新一日的累积值通常 ≠ 1.0。前复权价格下游消费要求"以最新一日为基准"，
        因此 ``fore_adj_factor`` 必须按 ``1.0 / result[-1].adj_factor`` 归一化，
        而 ``adj_factor``（向后复权）保留原始累积值不变。

    归一化失败（result 为空或最新一日因子 ≤ 0）时静默跳过 — 调用方
    应在更上层识别异常数据。
    """
    if not result:
        return
    latest = result[-1].get("fore_adj_factor") or 0.0
    if latest <= 0:
        logger.warning(
            "fore_adj_factor 归一化跳过：最新一日因子非正 (%s)，symbol=%s",
            latest,
            result[-1].get("symbol"),
        )
        return
    norm = 1.0 / float(latest)
    for row in result:
        raw = row.get("fore_adj_factor") or 0.0
        row["fore_adj_factor"] = round(float(raw) * norm, 6)

