"""手写编排层（替代 LangGraph graph/setup.py）— 保序流水线 + 节点封装。

run_pipeline 采用 PEP 562 惰性导出：orchestrator/__init__ 不再在模块级
import pipeline（pipeline → workflow.executor → agents → orchestrator.invoker
的环曾靠 11+ 处函数内延迟 import 硬撑，现于包根断开）。
"""


def __getattr__(name):
    if name == "run_pipeline":
        from .pipeline import run_pipeline
        return run_pipeline
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
