"""并行辩论编排契约测试（无 mock，无外部 I/O）

覆盖：
- PipelineDeps 新增模型级并发限额字段（默认 None = 不限，直通零开销）
- compute_total_units 分母与并行/串行开关无关（总发言数不变）
- debate_parallel 配置默认 True（并行），可显式关回串行
"""

import pytest

from app.engine.orchestrator.pipeline import PipelineDeps, compute_total_units


class TestPipelineDepsLimits:
    def test_limit_fields_default_none(self):
        deps = PipelineDeps(
            analyst_client=None, debate_client=None, toolkit=None, config={}
        )
        assert deps.analyst_limit is None
        assert deps.analyst_limit_key is None
        assert deps.debate_limit is None
        assert deps.debate_limit_key is None

    def test_limit_fields_settable(self):
        deps = PipelineDeps(
            analyst_client=None, debate_client=None, toolkit=None, config={},
            analyst_limit=6, analyst_limit_key="zhipu|glm-4",
            debate_limit=3, debate_limit_key="deepseek|deepseek-chat",
        )
        assert deps.analyst_limit == 6
        assert deps.debate_limit_key == "deepseek|deepseek-chat"


class TestTotalUnits:
    def test_total_units_independent_of_parallel_switch(self):
        # 分母只由拓扑决定：分析师数 + 阶段轮次 + 恒执行节点；并行不改变总发言数
        for p2 in (True, False):
            for p3 in (True, False):
                total = compute_total_units(
                    4, phase2_enabled=p2, phase2_rounds=1,
                    phase3_enabled=p3, phase3_rounds=1,
                )
                expected = 4
                if p2:
                    expected += 2 * 2 + 1
                expected += 1
                if p3:
                    expected += 3 * 2 + 1
                expected += 1
                assert total == expected


class TestDebateParallelConfig:
    def test_fallback_switch_present(self):
        # debate_parallel 是 config dict 键（默认 True 并行，False 回退串行）；
        # 验证模块源码包含回退开关（轻量契约，防误删）
        import inspect

        from app.engine.orchestrator import pipeline as pl

        src = inspect.getsource(pl)
        assert 'config.get("debate_parallel", True)' in src


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
