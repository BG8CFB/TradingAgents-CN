"""
写入前校验 (Validation)

在数据写入 MongoDB 前执行校验，拒绝不合法数据。
按数据域定义不同的校验规则。
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ValidationError:
    """单条校验错误"""

    __slots__ = ("field", "rule", "message", "value")

    def __init__(self, field: str, rule: str, message: str, value: Any = None):
        self.field = field
        self.rule = rule
        self.message = message
        self.value = value

    def __repr__(self) -> str:
        return f"ValidationError({self.field}, {self.rule}: {self.message})"


class DataValidator:
    """按数据域执行写入前校验"""

    # 必填字段定义
    REQUIRED_FIELDS: Dict[str, List[str]] = {
        "basic_info": ["symbol", "name"],
        "trade_calendar": ["exchange", "cal_date"],
        "daily_quotes": ["symbol", "trade_date"],
        "daily_indicators": ["symbol", "trade_date"],
        "adj_factors": ["symbol", "trade_date"],
        "financial": ["symbol", "report_period", "statement_type"],
        "market_quotes": ["symbol"],
        "news": ["content_hash"],
    }

    # 数值范围校验规则
    RANGE_RULES: Dict[str, Dict[str, Tuple[Optional[float], Optional[float]]]] = {
        "daily_quotes": {
            "open": (0, None),     # 价格 ≥ 0
            "high": (0, None),
            "low": (0, None),
            "close": (0, None),
            "volume": (0, None),   # 成交量 ≥ 0
            "amount": (0, None),
            "pct_chg": (-30, 30),  # A 股涨跌幅 ±30%（含科创板 ±20%）
        },
        "daily_indicators": {
            "total_mv": (0, None),
            "circ_mv": (0, None),
            "turnover_rate": (0, 100),
        },
    }

    def validate_batch(
        self, domain: str, records: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[ValidationError]]:
        """
        批量校验记录。

        Returns:
            (valid_records, invalid_records, errors)
        """
        valid: List[Dict[str, Any]] = []
        invalid: List[Dict[str, Any]] = []
        all_errors: List[ValidationError] = []

        for record in records:
            errors = self.validate(domain, record)
            if errors:
                invalid.append(record)
                all_errors.extend(errors)
            else:
                valid.append(record)

        if invalid:
            logger.warning(
                "域 %s 校验: %d/%d 条记录不合法",
                domain, len(invalid), len(records),
            )

        return valid, invalid, all_errors

    def validate(self, domain: str, record: Dict[str, Any]) -> List[ValidationError]:
        """校验单条记录"""
        errors: List[ValidationError] = []

        # 1. 必填字段检查
        required = self.REQUIRED_FIELDS.get(domain, [])
        for field_name in required:
            value = record.get(field_name)
            if value is None or value == "" or value == "NaN":
                errors.append(ValidationError(
                    field=field_name, rule="required",
                    message=f"必填字段 {field_name} 缺失",
                    value=value,
                ))

        # 2. 数值范围检查
        range_rules = self.RANGE_RULES.get(domain, {})
        for field_name, (min_val, max_val) in range_rules.items():
            value = record.get(field_name)
            if value is None:
                continue
            try:
                num_val = float(value)
                if min_val is not None and num_val < min_val:
                    errors.append(ValidationError(
                        field=field_name, rule="min_value",
                        message=f"{field_name}={num_val} < {min_val}",
                        value=num_val,
                    ))
                if max_val is not None and num_val > max_val:
                    errors.append(ValidationError(
                        field=field_name, rule="max_value",
                        message=f"{field_name}={num_val} > {max_val}",
                        value=num_val,
                    ))
            except (ValueError, TypeError):
                pass

        # 3. 日期格式检查
        date_fields = ["trade_date", "report_period", "cal_date"]
        for field_name in date_fields:
            value = record.get(field_name)
            if value and isinstance(value, str):
                if not self._is_valid_date(value):
                    errors.append(ValidationError(
                        field=field_name, rule="date_format",
                        message=f"{field_name}={value} 不是合法日期",
                        value=value,
                    ))

        return errors

    @staticmethod
    def _is_valid_date(date_str: str) -> bool:
        """检查日期字符串格式（YYYY-MM-DD 或 YYYYMMDD）"""
        if not date_str:
            return False
        # 接受 YYYY-MM-DD 和 YYYYMMDD
        cleaned = date_str.replace("-", "")
        if len(cleaned) != 8:
            return False
        try:
            year, month, day = int(cleaned[:4]), int(cleaned[4:6]), int(cleaned[6:8])
            return 1990 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31
        except (ValueError, IndexError):
            return False
