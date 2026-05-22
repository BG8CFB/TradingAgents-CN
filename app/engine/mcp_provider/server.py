"""
Finance MCP Server Entry Point — 基于新数据架构 DataInterface。
"""
import json
import logging
import re
from mcp.server.fastmcp import FastMCP
from app.data.core.interface import DataInterface

# Initialize Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize MCP Server
mcp = FastMCP("FinanceMCP")

# Import tools to register them
from app.engine.mcp_provider.tools.finance.market_data import get_stock_kline_logic
from app.engine.mcp_provider.tools.finance.fundamental import get_company_metrics_logic
from app.engine.mcp_provider.tools.finance.news import get_finance_news_logic

# 尝试复用已有的验证函数
try:
    from app.engine.tools.common.param_validators import (
        validate_stock_code as _validate_stock_code,
        validate_limit as _validate_limit,
        validate_period as _validate_period,
        validate_date as _validate_date,
    )
    _VALIDATORS_AVAILABLE = True
except ImportError:
    _VALIDATORS_AVAILABLE = False


# ---- 内联验证辅助函数 ----

def _check_code(code: str) -> str | None:
    """验证股票代码：去除前后空格，检查非空。返回错误消息或 None。"""
    code = code.strip()
    if not code:
        return "股票代码不能为空"
    if _VALIDATORS_AVAILABLE:
        ok, msg = _validate_stock_code(code)
        if not ok:
            return msg
    return None


def _check_period(period: str) -> str | None:
    """验证 K 线周期。返回错误消息或 None。"""
    period = period.strip().lower()
    if _VALIDATORS_AVAILABLE:
        ok, msg = _validate_period(period)
        if not ok:
            return msg
        return None
    # 兜底验证
    valid = ("day", "week", "month", "5m", "15m", "30m", "60m", "1d", "1w", "1m", "minute")
    if period not in valid:
        return f"period 参数无效，支持: {', '.join(valid)}"
    return None


def _check_limit(limit: int, min_val: int = 1, max_val: int = 1000) -> str | None:
    """验证数量限制。返回错误消息或 None。"""
    if _VALIDATORS_AVAILABLE:
        ok, msg = _validate_limit(limit, min_val, max_val)
        if not ok:
            return msg
        return None
    # 兜底验证
    if not isinstance(limit, int) or not (min_val <= limit <= max_val):
        return f"limit 参数必须在 {min_val}-{max_val} 之间"
    return None


# YYYYMMDD 或 YYYY-MM-DD
_DATE_RE = re.compile(r"^\d{4}[-]?\d{2}[-]?\d{2}$")


def _check_date(date_str: str) -> str | None:
    """验证日期格式。返回错误消息或 None。"""
    if not date_str or not isinstance(date_str, str):
        return "日期不能为空"
    date_str = date_str.strip()
    if _VALIDATORS_AVAILABLE:
        ok, msg = _validate_date(date_str)
        if not ok:
            return msg
        return None
    # 兜底验证
    if not _DATE_RE.match(date_str):
        return "日期格式错误，应为 YYYYMMDD 或 YYYY-MM-DD"
    return None


def _check_days(days: int) -> str | None:
    """验证天数范围。返回错误消息或 None。"""
    if not isinstance(days, int) or not (1 <= days <= 365):
        return "days 参数必须在 1-365 之间"
    return None


@mcp.tool()
async def get_stock_data(code: str, period: str = "day", limit: int = 120) -> str:
    """
    Get stock market data (K-line).

    Args:
        code: Stock code (e.g., '000001.SZ', 'AAPL', '00700.HK').
        period: Data period ('day', 'week', 'month', '5m', '15m', '30m', '60m'). Default is 'day'.
        limit: Number of data points to return. Default is 120.
    """
    code = code.strip()
    if err := _check_code(code):
        return json.dumps({"error": err})
    if err := _check_period(period):
        return json.dumps({"error": err})
    if err := _check_limit(limit):
        return json.dumps({"error": err})
    return await get_stock_kline_logic(DataInterface.get_instance(), code, period, limit)


@mcp.tool()
async def get_company_metrics(code: str, date: str) -> str:
    """
    Get fundamental financial metrics for a company.

    Args:
        code: Stock code (e.g., '000001.SZ').
        date: Trade date to query metrics for (YYYYMMDD or YYYY-MM-DD).
    """
    code = code.strip()
    if err := _check_code(code):
        return json.dumps({"error": err})
    if err := _check_date(date):
        return json.dumps({"error": err})
    return await get_company_metrics_logic(DataInterface.get_instance(), code, date)


@mcp.tool()
async def get_finance_news(code: str, days: int = 2, limit: int = 10) -> str:
    """
    Get financial news and announcements for a specific stock.

    Args:
        code: Stock code.
        days: Lookback window in days (default 2).
        limit: Max number of news items (default 10).
    """
    code = code.strip()
    if err := _check_code(code):
        return json.dumps({"error": err})
    if err := _check_days(days):
        return json.dumps({"error": err})
    if err := _check_limit(limit):
        return json.dumps({"error": err})
    return await get_finance_news_logic(DataInterface.get_instance(), code, days, limit)


def main():
    """Run the MCP server"""
    logger.info("Starting FinanceMCP Server...")
    mcp.run()

if __name__ == "__main__":
    main()
