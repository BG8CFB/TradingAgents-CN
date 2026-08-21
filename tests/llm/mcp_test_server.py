"""测试用最小 MCP stdio server（官方 mcp SDK low-level API，真实进程）

mcp 2.0 移除了 mcp.server.fastmcp，改用 Server 构造器回调风格。
不依赖任何第三方封装；行为与旧 FastMCP 版一致（add/multiply/fail）。
"""

import anyio

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

_NUM = {"type": "number"}


def _tool(name: str, desc: str, props: dict, required: list) -> types.Tool:
    return types.Tool(
        name=name,
        description=desc,
        input_schema={"type": "object", "properties": props, "required": required},
    )


TOOLS = [
    _tool("add", "两数相加", {"a": _NUM, "b": _NUM}, ["a", "b"]),
    _tool("multiply", "两数相乘", {"a": _NUM, "b": _NUM}, ["a", "b"]),
    _tool("fail", "总是返回 isError（用于错误回传断言）", {"message": {"type": "string"}}, ["message"]),
]


async def on_list_tools(ctx, params) -> types.ListToolsResult:
    return types.ListToolsResult(tools=TOOLS)


async def on_call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
    args = params.arguments or {}
    try:
        if params.name == "add":
            text = str(float(args["a"]) + float(args["b"]))
        elif params.name == "multiply":
            text = str(float(args["a"]) * float(args["b"]))
        else:
            raise ValueError(f"预期失败: {args.get('message', '')}")
    except ValueError as e:
        # isError 路径：错误文本回传，不抛异常（client 侧转 "MCP 工具执行错误"）
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=str(e))], is_error=True
        )
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)])


server = Server("calc", on_list_tools=on_list_tools, on_call_tool=on_call_tool)


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(main)
