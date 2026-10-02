"""并行辩论编排契约测试（无 mock，无外部 I/O）

覆盖：
- PipelineDeps 新增模型级并发限额字段（默认 None = 不限，直通零开销）
- debate_parallel 配置默认 True（并行），可显式关回串行

总单元分母与并行开关无关的公式断言已迁 CompiledPlan.total_units
（tests/engine/workflow/test_compiler_plan.py，2026-09 编排重写）。
"""

import pytest

from app.engine.orchestrator.pipeline import PipelineDeps


class TestPipelineDepsLimits:
    def test_limit_fields_default_none(self):
        deps = PipelineDeps(analyst_client=None, debate_client=None, toolkit=None, config={})
        assert deps.analyst_limit is None
        assert deps.analyst_limit_key is None
        assert deps.debate_limit is None
        assert deps.debate_limit_key is None

    def test_limit_fields_settable(self):
        deps = PipelineDeps(
            analyst_client=None,
            debate_client=None,
            toolkit=None,
            config={},
            analyst_limit=6,
            analyst_limit_key="zhipu|glm-4",
            debate_limit=3,
            debate_limit_key="deepseek|deepseek-chat",
        )
        assert deps.analyst_limit == 6
        assert deps.debate_limit_key == "deepseek|deepseek-chat"


class TestDebateParallelConfig:
    def test_fallback_switch_present(self):
        # debate_parallel 是 config dict 键（默认 True 并行，False 回退串行）；
        # 执行机制 2026-09 迁至 workflow/executor（源码契约防误删，检查搬家后的模块）
        import inspect

        from app.engine.orchestrator.workflow import executor

        src = inspect.getsource(executor)
        assert 'config.get("debate_parallel", True)' in src


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
