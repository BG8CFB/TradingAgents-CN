"""测试用最小 MCP stdio server（官方 mcp SDK FastMCP，真实进程）"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("calc")


@mcp.tool()
def add(a: float, b: float) -> float:
    """两数相加"""
    return a + b


@mcp.tool()
def multiply(a: float, b: float) -> float:
    """两数相乘"""
    return a * b


@mcp.tool()
def fail(message: str) -> str:
    """总是返回 isError（用于错误回传断言）"""
    raise ValueError(f"预期失败: {message}")


if __name__ == "__main__":
    mcp.run()
