"""数据校验器 — 写入前的字段校验。"""

import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

# 各域必填字段
_REQUIRED_FIELDS = {
    "basic_info": ["symbol", "name"],
    "trade_calendar": ["exchange", "cal_date", "is_open"],
    "daily_quotes": ["symbol", "trade_date", "close"],
    "daily_indicators": ["symbol", "trade_date"],
    "adj_factors": ["symbol", "trade_date", "adj_factor"],
    "corporate_actions": ["symbol", "ex_date", "action_type"],
    "financial_data": ["symbol", "report_period", "statement_type"],
    "market_quotes": ["symbol", "last_price"],
    "news": ["symbol", "title", "content_hash"],
}

# 价格字段 → 正数检查
_PRICE_FIELDS = ["open", "high", "low", "close", "pre_close", "last_price", "adj_factor"]

# 涨跌幅范围（按市场）
_PCT_RANGE = {
    "CN": (-30, 30),
    "HK": (-100, 100),
    "US": (-100, 100),
}


class Validator:
    """数据校验器。"""

    def validate(self, records: List[Dict], domain: str, market: str) -> Tuple[List[Dict], List[Dict]]:
        """校验记录，返回 (有效记录, 错误记录)。"""
        if not records:
            return [], []

        valid = []
        errors = []

        required = _REQUIRED_FIELDS.get(domain, [])

        for rec in records:
            issues = self._validate_record(rec, domain, market, required)
            if issues:
                errors.append({"record": rec, "issues": issues})
            else:
                valid.append(rec)

        if errors:
            logger.warning(f"校验 {domain}/{market}: {len(valid)} 有效, {len(errors)} 错误")

        return valid, errors

    def _validate_record(self, rec: Dict, domain: str, market: str, required: List[str]) -> List[str]:
        issues = []

        # 必填字段
        for field in required:
            if field not in rec or rec[field] is None:
                issues.append(f"缺少必填字段: {field}")

        if issues:
            return issues

        # 价格正数检查
        for pf in _PRICE_FIELDS:
            val = rec.get(pf)
            if val is not None and isinstance(val, (int, float)) and val < 0:
                issues.append(f"价格不能为负: {pf}={val}")

        # 涨跌幅范围
        pct = rec.get("pct_chg")
        if pct is not None:
            lo, hi = _PCT_RANGE.get(market, (-100, 100))
            if pct < lo or pct > hi:
                issues.append(f"涨跌幅超范围: pct_chg={pct} (范围 {lo}~{hi})")

        return issues
