"""
MCP 工具参数验证器

提供统一的参数验证功能，防止恶意参数导致资源耗尽或其他问题。

验证规则：
1. 股票代码格式验证
2. 日期格式验证
3. 数值范围验证
4. 字符串长度验证
"""

import re
import logging
from datetime import datetime
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class ValidationResult:
    """验证结果"""
    def __init__(self, is_valid: bool, error_message: str = ""):
        self.is_valid = is_valid
        self.error_message = error_message

    def __bool__(self):
        return self.is_valid


class MCPToolValidators:
    """MCP 工具参数验证器"""

    # 股票代码正则表达式
    # A股: 6位数字
    STOCK_CODE_CN = re.compile(r'^\d{6}$')
    # 港股: 4-5位数字
    STOCK_CODE_HK = re.compile(r'^\d{4,5}$')
    # 美股: 大写字母
    STOCK_CODE_US = re.compile(r'^[A-Z]{1,5}$')

    @staticmethod
    def validate_stock_code(code: str, market_type: str = "cn") -> ValidationResult:
        """
        验证股票代码格式

        Args:
            code: 股票代码
            market_type: 市场类型 ("cn", "hk", "us")

        Returns:
            ValidationResult
        """
        if not code or not isinstance(code, str):
            return ValidationResult(False, "股票代码不能为空")

        code = code.strip().upper()

        # 处理带市场后缀的代码
        if "." in code:
            parts = code.split(".")
            code = parts[0]
            suffix = parts[1].upper()
            if suffix in ["SH", "SZ"]:
                market_type = "cn"
            elif suffix == "HK":
                market_type = "hk"
            elif suffix in ["US", "NYSE", "NASDAQ", "AMEX"]:
                market_type = "us"

        # 根据市场类型验证
        if market_type.lower() in ["cn", "a股", "a", "china"]:
            if not MCPToolValidators.STOCK_CODE_CN.match(code):
                return ValidationResult(False, f"A股代码格式错误：{code}，应为6位数字")
        elif market_type.lower() in ["hk", "港股", "hongkong"]:
            if not MCPToolValidators.STOCK_CODE_HK.match(code):
                return ValidationResult(False, f"港股代码格式错误：{code}，应为4-5位数字")
        elif market_type.lower() in ["us", "美股", "usa", "united states"]:
            if not MCPToolValidators.STOCK_CODE_US.match(code):
                return ValidationResult(False, f"美股代码格式错误：{code}，应为1-5位大写字母")
        else:
            # 自动检测
            if MCPToolValidators.STOCK_CODE_CN.match(code):
                return ValidationResult(True)
            elif MCPToolValidators.STOCK_CODE_HK.match(code):
                return ValidationResult(True)
            elif MCPToolValidators.STOCK_CODE_US.match(code):
                return ValidationResult(True)
            else:
                return ValidationResult(False, f"股票代码格式错误：{code}，无法识别市场类型")

        return ValidationResult(True)

    @staticmethod
    def validate_date(date_str: str) -> ValidationResult:
        """
        验证日期格式和有效性

        Args:
            date_str: 日期字符串 (YYYY-MM-DD)

        Returns:
            ValidationResult
        """
        if not date_str or not isinstance(date_str, str):
            return ValidationResult(False, "日期不能为空")

        date_str = date_str.strip()

        # 验证格式
        try:
            parsed_date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return ValidationResult(False, f"日期格式错误：{date_str}，应为 YYYY-MM-DD")

        # 验证范围 (1900-01-01 到 2100-12-31)
        if parsed_date.year < 1900 or parsed_date.year > 2100:
            return ValidationResult(False, f"日期超出范围：{date_str}，应在 1900-2100 之间")

        return ValidationResult(True)

    @staticmethod
    def validate_date_range(start_date: str, end_date: str) -> ValidationResult:
        """
        验证日期范围

        Args:
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            ValidationResult
        """
        # 验证单个日期
        start_result = MCPToolValidators.validate_date(start_date)
        if not start_result:
            return start_result

        end_result = MCPToolValidators.validate_date(end_date)
        if not end_result:
            return end_result

        # 验证顺序
        start = datetime.strptime(start_date.strip(), "%Y-%m-%d")
        end = datetime.strptime(end_date.strip(), "%Y-%m-%d")

        if start > end:
            return ValidationResult(False, f"开始日期不能晚于结束日期：{start_date} > {end_date}")

        # 验证间隔 (不超过1年)
        delta = end - start
        if delta.days > 365:
            return ValidationResult(False, f"日期范围过大：{delta.days} 天，不应超过 365 天")

        return ValidationResult(True)

    @staticmethod
    def validate_limit(limit: int, min_val: int = 1, max_val: int = 1000) -> ValidationResult:
        """
        验证数量限制

        Args:
            limit: 限制值
            min_val: 最小值
            max_val: 最大值

        Returns:
            ValidationResult
        """
        if not isinstance(limit, int):
            try:
                limit = int(limit)
            except (ValueError, TypeError):
                return ValidationResult(False, f"限制值必须为整数：{limit}")

        if limit < min_val or limit > max_val:
            return ValidationResult(False, f"限制值超出范围：{limit}，应在 {min_val}-{max_val} 之间")

        return ValidationResult(True)

    @staticmethod
    def validate_string_length(value: str, max_length: int = 100, field_name: str = "字段") -> ValidationResult:
        """
        验证字符串长度

        Args:
            value: 字符串值
            max_length: 最大长度
            field_name: 字段名称（用于错误消息）

        Returns:
            ValidationResult
        """
        if not isinstance(value, str):
            return ValidationResult(False, f"{field_name}必须为字符串")

        if len(value) > max_length:
            return ValidationResult(False, f"{field_name}长度超出限制：{len(value)} > {max_length}")

        return ValidationResult(True)

    @staticmethod
    def validate_period(period: str) -> ValidationResult:
        """
        验证 K 线周期

        Args:
            period: 周期 (day, week, month, minute, 等)

        Returns:
            ValidationResult
        """
        valid_periods = ["day", "week", "month", "minute", "5m", "15m", "30m", "60m", "1d", "1w", "1m"]

        if not period or not isinstance(period, str):
            return ValidationResult(False, "周期不能为空")

        period = period.strip().lower()

        # 映射常见别名
        period_map = {
            "daily": "day", "d": "day",
            "weekly": "week", "w": "week",
            "monthly": "month", "m": "month",
            "minutely": "minute", "1min": "minute", "60min": "60m"
        }

        period = period_map.get(period, period)

        if period not in valid_periods:
            return ValidationResult(False, f"无效的周期：{period}，支持：{', '.join(valid_periods)}")

        return ValidationResult(True)

    @staticmethod
    def sanitize_input(input_str: str, max_length: int = 200) -> str:
        """
        清理输入字符串，移除危险字符

        Args:
            input_str: 输入字符串
            max_length: 最大长度

        Returns:
            清理后的字符串
        """
        if not isinstance(input_str, str):
            return str(input_str)

        # 截断长度
        if len(input_str) > max_length:
            input_str = input_str[:max_length]
            logger.warning(f"输入字符串被截断到 {max_length} 字符")

        # 移除危险字符 (SQL 注入、XSS 等)
        dangerous_patterns = [
            r'<script.*?>.*?</script>',  # XSS
            r"[';\"-]",  # SQL 注入字符
            r'\.\./',  # 路径遍历
            r'\|\|.*&&',  # 命令注入
        ]

        cleaned = input_str
        for pattern in dangerous_patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

        return cleaned.strip()


# 便捷函数
def validate_stock_code(code: str, market_type: str = "cn") -> Tuple[bool, str]:
    """验证股票代码，返回 (is_valid, error_message)"""
    result = MCPToolValidators.validate_stock_code(code, market_type)
    return result.is_valid, result.error_message


def validate_date(date_str: str) -> Tuple[bool, str]:
    """验证日期，返回 (is_valid, error_message)"""
    result = MCPToolValidators.validate_date(date_str)
    return result.is_valid, result.error_message


def validate_limit(limit: int, min_val: int = 1, max_val: int = 1000) -> Tuple[bool, str]:
    """验证限制值，返回 (is_valid, error_message)"""
    result = MCPToolValidators.validate_limit(limit, min_val, max_val)
    return result.is_valid, result.error_message


def validate_period(period: str) -> Tuple[bool, str]:
    """验证周期，返回 (is_valid, error_message)"""
    result = MCPToolValidators.validate_period(period)
    return result.is_valid, result.error_message
