"""
普通函数 → ToolDef 适配器（去 langchain StructuredTool）

约定：被包装函数使用类型注解 + docstring（首段为描述），
Annotated[T, "描述"] 会转成 JSON Schema property description。
同步/异步函数均支持（runner 统一处理 awaitable）。
"""

import inspect
from typing import Any, Callable, List, Optional, get_args, get_origin, get_type_hints

from app.utils.logging_init import get_logger

from ..core.types import ToolDef

logger = get_logger("app.llm.tools")

_TYPE_MAP = {
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "str": "string",
    "list": "array",
    "dict": "object",
}


def _annotation_to_schema(ann: Any) -> dict:
    """类型注解 → JSON Schema 类型（Annotated[T, desc] 提取描述）"""
    desc = None
    if get_origin(ann) is not None and hasattr(ann, "__metadata__"):
        args = get_args(ann)
        ann = args[0]
        if len(args) > 1 and isinstance(args[1], str):
            desc = args[1]
    type_name = getattr(ann, "__name__", None) or (
        get_origin(ann) and getattr(get_origin(ann), "__name__", None)
    )
    schema: dict = {"type": _TYPE_MAP.get(type_name, "string")}
    if desc:
        schema["description"] = desc
    return schema


def func_to_tooldef(
    fn: Callable,
    name: Optional[str] = None,
    description: Optional[str] = None,
    is_concurrency_safe: bool = False,
) -> ToolDef:
    """带注解与 docstring 的普通函数 → ToolDef"""
    sig = inspect.signature(fn)
    try:
        hints = get_type_hints(fn, include_extras=True)
    except Exception:  # noqa: BLE001 - 注解解析失败退化为全 string
        hints = {}

    props = {}
    required = []
    for pname, param in sig.parameters.items():
        if pname in ("self", "cls"):
            continue
        props[pname] = _annotation_to_schema(hints.get(pname, str))
        if param.default is inspect.Parameter.empty:
            required.append(pname)

    schema: dict = {"type": "object", "properties": props}
    if required:
        schema["required"] = required

    doc = description or inspect.getdoc(fn) or fn.__name__
    return ToolDef(
        name=name or fn.__name__,
        description=doc,
        params_schema=schema,
        handler=fn,
        is_concurrency_safe=is_concurrency_safe,
    )


def funcs_to_tooldefs(funcs: List[Callable], default_safe: bool = False) -> List[ToolDef]:
    """批量转换（数据查询类工具默认只读安全）"""
    return [func_to_tooldef(f, is_concurrency_safe=default_safe) for f in funcs]
