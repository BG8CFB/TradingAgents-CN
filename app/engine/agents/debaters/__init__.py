"""通用辩论成员工厂（自定义 debater/judge NodeSpec 的执行路径）。"""

from app.engine.agents.debaters.generic import create_generic_debater, create_generic_judge

__all__ = ["create_generic_debater", "create_generic_judge"]
