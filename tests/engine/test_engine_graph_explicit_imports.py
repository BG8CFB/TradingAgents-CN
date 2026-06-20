"""
graph 模块显式导入完整性测试。

验证从星号导入重构为显式导入后，所有需要的符号都可正常访问：
- app.engine.graph.setup：GraphSetup 内部使用的所有工厂函数
- app.engine.graph.trading_graph：TradingAgentsGraph 使用的 Toolkit
"""

from __future__ import annotations


def test_setup_imports_all_stage2_factories():
    import app.engine.graph.setup as setup_mod

    for name in (
        "SimpleAgentFactory",
        "create_bear_researcher",
        "create_bull_researcher",
        "create_research_manager",
        "create_trader",
    ):
        assert hasattr(setup_mod, name), f"setup 模块缺失 {name}"


def test_setup_imports_all_stage3_factories():
    import app.engine.graph.setup as setup_mod

    for name in (
        "create_risky_debator",
        "create_safe_debator",
        "create_neutral_debator",
        "create_risk_manager",
    ):
        assert hasattr(setup_mod, name), f"setup 模块缺失 {name}"


def test_setup_imports_toolkit_and_agent_state():
    import app.engine.graph.setup as setup_mod

    assert hasattr(setup_mod, "Toolkit")
    assert hasattr(setup_mod, "AgentState")


def test_trading_graph_imports_toolkit():
    import app.engine.graph.trading_graph as tg_mod

    assert hasattr(tg_mod, "Toolkit"), "trading_graph 缺失 Toolkit"


def test_no_star_imports_remain():
    """重构后不应残留 `from app.engine.agents import *`。"""
    import app.engine.graph.setup as setup_mod
    import app.engine.graph.trading_graph as tg_mod
    import inspect

    for mod in (setup_mod, tg_mod):
        src = inspect.getsource(mod)
        assert "from app.engine.agents import *" not in src, (
            f"{mod.__name__} 仍使用星号导入"
        )


def test_graphsetup_class_can_instantiate_dependencies():
    """GraphSetup 所需符号真实可调用（不构造 LLM，仅验证符号可用性）。"""
    from app.engine.graph.setup import GraphSetup
    from app.engine.agents.utils.agent_utils import Toolkit
    from app.engine.graph.conditional_logic import ConditionalLogic

    # 仅验证类可定位，不实际实例化（实例化需要 LLM/Memory 等重依赖）
    assert GraphSetup is not None
    assert Toolkit is not None
    assert ConditionalLogic is not None
