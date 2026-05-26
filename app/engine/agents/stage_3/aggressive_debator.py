"""
Stage 3 激进风险辩手 — 薄包装，委托给 debator_factory。

保留此文件以维持所有 import 路径的向后兼容。
"""

from app.engine.agents.stage_3.debator_factory import create_debator


def create_risky_debator(llm):
    """创建激进风险辩手节点（委托给工厂函数）。"""
    return create_debator(llm, side="risky")
