"""预注入数据源包

由代码（编排器）控制的金融数据获取实现：分析师启动时预调用、
结果以 <tool_data> 注入上下文，LLM 不可主动调用。
与 AI 可调用内置工具（app/engine/tools/builtin）是两套独立方案。
规格声明见 registry.py（DATASOURCE_REGISTRY）。
"""

from . import capital_flow, china_market, fundamentals, market, news, sentiment
from .loader import load_datasource_tools

__all__ = [
    "capital_flow",
    "china_market",
    "fundamentals",
    "market",
    "news",
    "sentiment",
    "load_datasource_tools",
]
