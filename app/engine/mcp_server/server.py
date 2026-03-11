"""
Finance MCP Server Entry Point
"""
import asyncio
import logging
from mcp.server.fastmcp import FastMCP
from app.data.manager import DataSourceManager
from app.utils.stock_utils import StockUtils, StockMarket

# Initialize Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize MCP Server
mcp = FastMCP("FinanceMCP")

# Initialize DataSourceManager (Global instance)
manager = DataSourceManager()


# Import tools to register them (will be implemented in separate files)
# For FastMCP, we usually define tools in the same file or import functions and use @mcp.tool
# We will use the import approach by defining tools in modules and then importing them here
# However, FastMCP decorator needs to be on the function.
# A better pattern for modularity with FastMCP is to have tool functions return the tool definition
# or simply import the module and have the module use the `mcp` instance if passed,
# OR just define wrappers here that call the logic in `tools/finance/`.

# Let's try to keep it simple: Define logic in `tools/finance/` and wrap them here.

from app.engine.mcp_server.tools.finance.market_data import get_stock_kline_logic
from app.engine.mcp_server.tools.finance.fundamental import get_company_metrics_logic
from app.engine.mcp_server.tools.finance.news import get_finance_news_logic


@mcp.tool()
async def get_stock_data(code: str, period: str = "day", limit: int = 120) -> str:
    """
    Get stock market data (K-line).

    Args:
        code: Stock code (e.g., '000001.SZ', 'AAPL', '00700.HK').
        period: Data period ('day', 'week', 'month', '5m', '15m', '30m', '60m'). Default is 'day'.
        limit: Number of data points to return. Default is 120.
    """
    return await get_stock_kline_logic(manager, code, period, limit)


@mcp.tool()
async def get_company_metrics(code: str, date: str) -> str:
    """
    Get fundamental financial metrics for a company.

    Args:
        code: Stock code (e.g., '000001.SZ').
        date: Trade date to query metrics for (YYYYMMDD).
    """
    return await get_company_metrics_logic(manager, code, date)


@mcp.tool()
async def get_finance_news(code: str, days: int = 2, limit: int = 10) -> str:
    """
    Get financial news and announcements for a specific stock.

    Args:
        code: Stock code.
        days: Lookback window in days (default 2).
        limit: Max number of news items (default 10).
    """
    return await get_finance_news_logic(manager, code, days, limit)


def main():
    """Run the MCP server"""
    logger.info("Starting FinanceMCP Server...")
    mcp.run()

if __name__ == "__main__":
    main()
