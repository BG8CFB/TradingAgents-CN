"""
工具注册表

用法：
    from app.llm import tool_registry

    @tool_registry.register
    def get_current_time() -> str:
        '''获取当前 UTC 时间'''
        ...

    # 或显式声明 schema：
    @tool_registry.register(description="...", params_schema={...})
    def foo(x: int) -> str: ...

handler 签名：同步或异步，参数名与 params_schema 的 properties 对应，返回 str。
"""

import inspect
from typing import Any, Callable, Dict, List, Optional

import logging

from ..core.types import ToolDef

logger = logging.getLogger("app.llm.tools")


class ToolRegistry:
    """进程内工具注册表（简单 dict 存储，协议转换由各 client 完成）"""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDef] = {}

    def register(
        self,
        fn: Optional[Callable] = None,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        params_schema: Optional[Dict[str, Any]] = None,
    ):
        """装饰器或直接调用注册"""

        def wrap(f: Callable) -> Callable:
            tool_name = name or f.__name__
            tool_def = ToolDef(
                name=tool_name,
                description=description or inspect.getdoc(f) or tool_name,
                params_schema=params_schema or self._infer_schema(f),
                handler=f,
            )
            self._tools[tool_name] = tool_def
            logger.debug(f"注册工具: {tool_name}")
            return f

        return wrap(fn) if fn is not None else wrap

    @staticmethod
    def _infer_schema(fn: Callable) -> Dict[str, Any]:
        """从函数签名推断最简 JSON Schema（显式 params_schema 优先）"""
        sig = inspect.signature(fn)
        props: Dict[str, Any] = {}
        required: List[str] = []
        for pname, param in sig.parameters.items():
            if pname in ("self", "cls"):
                continue
            ann = param.annotation
            t = {"int": "integer", "float": "number", "bool": "boolean", "str": "string"}.get(
                getattr(ann, "__name__", ""), "string"
            )
            props[pname] = {"type": t}
            if param.default is inspect.Parameter.empty:
                required.append(pname)
        schema: Dict[str, Any] = {"type": "object", "properties": props}
        if required:
            schema["required"] = required
        return schema

    def get(self, name: str) -> Optional[ToolDef]:
        return self._tools.get(name)

    def defs(self) -> List[ToolDef]:
        return list(self._tools.values())

    def extend(self, defs: List[ToolDef]) -> None:
        """批量并入已构造的 ToolDef（直接复用定义，含 handler 与并发标记）。

        公共 API：子代理取工具子集等场景应使用本方法，禁止直接访问内部存储。
        """
        for t in defs:
            self._tools[t.name] = t

    async def execute(self, name: str, tool_input: Dict[str, Any], *, task_id: str = "") -> str:
        """执行工具，返回字符串结果。未知工具/异常都转为可回传的错误文本。

        结果统一经过 result_budget：超限落盘 + 预览引用，防止大输出撑爆上下文。
        """
        from .result_budget import apply_result_budget

        tool = self._tools.get(name)
        if tool is None:
            return f"错误：未知工具 '{name}'"
        try:
            result = tool.handler(**tool_input)
            if inspect.isawaitable(result):
                result = await result
            return apply_result_budget(name, str(result), task_id=task_id)
        except Exception as e:  # noqa: BLE001 - 工具错误必须回传给模型而非中断循环
            logger.warning(f"工具 {name} 执行失败: {e}")
            return f"工具执行失败: {e}"


# 全局默认注册表
tool_registry = ToolRegistry()


@tool_registry.register(
    description="获取当前的 UTC 时间，格式为 ISO 8601。当用户询问当前时间、日期时使用。",
    params_schema={"type": "object", "properties": {}},
)
def get_current_time() -> str:
    """演示用内置工具：真实实现（非 mock）"""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
