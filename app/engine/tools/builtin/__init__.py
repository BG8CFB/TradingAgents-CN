"""
内置工具包

按数据域组织的金融数据工具，通过 BUILTIN_TOOL_REGISTRY 统一管理。
"""
from .loader import load_builtin_tools

__all__ = ["load_builtin_tools"]
