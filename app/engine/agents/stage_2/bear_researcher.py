"""
Stage 2 看跌研究员 — 薄包装，委托给 researcher_factory。

保留此文件以维持所有 import 路径的向后兼容。
"""

from app.engine.agents.stage_2.researcher_factory import create_researcher


def create_bear_researcher(llm, memory):
    """创建看跌研究员节点（委托给工厂函数）。"""
    return create_researcher(llm, memory, side="bear")
