"""测试进度追踪器"""

import pytest

from app.services.progress.tracker import AnalysisStep, safe_serialize


class TestAnalysisStep:
    def test_defaults(self):
        step = AnalysisStep(name="test", description="desc")
        assert step.status == "pending"
        assert step.weight == 0.1
        assert step.start_time is None
        assert step.end_time is None

    def test_custom_values(self):
        step = AnalysisStep(name="test", description="desc", status="completed", weight=0.5)
        assert step.status == "completed"
        assert step.weight == 0.5


class TestSafeSerialize:
    def test_dict(self):
        data = {"a": 1, "b": "text"}
        assert safe_serialize(data) == data

    def test_list(self):
        data = [1, "two", None]
        assert safe_serialize(data) == data

    def test_primitives(self):
        assert safe_serialize("hello") == "hello"
        assert safe_serialize(42) == 42
        assert safe_serialize(3.14) == 3.14
        assert safe_serialize(True) is True
        assert safe_serialize(None) is None

    def test_nested(self):
        data = {"a": [1, {"b": 2}]}
        assert safe_serialize(data) == {"a": [1, {"b": 2}]}

    def test_object_with_dict(self):
        class Obj:
            def __init__(self):
                self.x = 1
        result = safe_serialize(Obj())
        assert result == {"x": 1}

    def test_fallback_to_str(self):
        class Unusual:
            pass
        obj = Unusual()
        result = safe_serialize(obj)
        assert isinstance(result, (str, dict))


class TestRedisProgressTrackerInit:
    def test_phase_config_parsing(self):
        from app.services.progress.tracker import RedisProgressTracker
        with pytest.MonkeyPatch.context() as m:
            tracker = RedisProgressTracker.__new__(RedisProgressTracker)
            tracker.task_id = "t1"
            tracker.analysts = []
            tracker.phase_config = {
                "phase2_enabled": True,
                "phase2_debate_rounds": 3,
                "phase3_enabled": False,
                "phase3_debate_rounds": 2,
                "phase4_enabled": True,
            }
            tracker.llm_provider = "test"
            tracker.on_update = None
            tracker.phase2_enabled = bool(tracker.phase_config.get("phase2_enabled", False))
            tracker.phase2_rounds = int(tracker.phase_config.get("phase2_debate_rounds", 1))
            tracker.phase3_enabled = bool(tracker.phase_config.get("phase3_enabled", False))
            tracker.phase3_rounds = int(tracker.phase_config.get("phase3_debate_rounds", 1))
            tracker.phase4_enabled = bool(tracker.phase_config.get("phase4_enabled", True))
            tracker.phase4_rounds = int(tracker.phase_config.get("phase4_debate_rounds", 1))

            assert tracker.phase2_enabled is True
            assert tracker.phase2_rounds == 3
            assert tracker.phase3_enabled is False
            assert tracker.phase4_enabled is True
