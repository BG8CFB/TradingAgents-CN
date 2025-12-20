from .utils.agent_utils import Toolkit, create_msg_delete
from .utils.agent_states import AgentState, InvestDebateState, RiskDebateState
from .utils.memory import FinancialSituationMemory

from .analysts.dynamic_analyst import create_dynamic_analyst

# Stage 2
from .stage_2.bear_researcher import create_bear_researcher
from .stage_2.bull_researcher import create_bull_researcher
from .stage_2.research_manager import create_research_manager
from .stage_2.trader import create_trader

# Stage 3
from .stage_3.aggresive_debator import create_risky_debator
from .stage_3.conservative_debator import create_safe_debator
from .stage_3.neutral_debator import create_neutral_debator
from .stage_3.risk_manager import create_risk_manager

# Stage 4

# 导入统一日志系统
from tradingagents.utils.logging_init import get_logger
logger = get_logger("default")

__all__ = [
    "FinancialSituationMemory",
    "Toolkit",
    "AgentState",
    "create_msg_delete",
    "InvestDebateState",
    "RiskDebateState",
    "create_bear_researcher",
    "create_bull_researcher",
    "create_research_manager",
    "create_dynamic_analyst",
    "create_neutral_debator",
    "create_risky_debator",
    "create_risk_manager",
    "create_safe_debator",
    "create_trader",
]
