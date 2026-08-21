"""辩论 barrier 合并纯函数测试（无 mock，无外部 I/O）

覆盖：
- 双侧（Phase 2）并行合并与手工构造的串行结果逐字段等价
- 三方（Phase 3）合并 + latest_speaker 语义
- 一侧失败（update 空/无 state_key）时该轮缺席、count 只加成功数
- messages 按固定侧序合并
"""

import pytest

from app.engine.orchestrator.pipeline import _merge_debate_updates


def _mk_update_inv(side: str, content: str, count_snapshot: int) -> dict:
    """模拟 researcher 节点返回的 update：基于旧 count 快照 append_round"""
    idx = count_snapshot // 2
    rounds: list = []
    for _ in range(idx + 1):
        rounds.append({})
    rounds[idx][side] = content
    return {
        "investment_debate_state": {"rounds": rounds, "count": count_snapshot + 1},
        "reports": {f"{side}_researcher": f"partial-{side}"},
        "messages": [f"msg-{side}"],
    }


class TestPhase2Merge:
    def test_merge_equals_serial_result(self):
        # 串行语义：Bull 先写 rounds[0]["bull"]，Bear 后写 rounds[0]["bear"]，count=2
        serial_rounds = [{"bull": "bull-r0", "bear": "bear-r0"}]

        st = {"investment_debate_state": {"rounds": [], "count": 0}, "reports": {}, "messages": []}
        updates = [
            _mk_update_inv("bull", "bull-r0", 0),
            _mk_update_inv("bear", "bear-r0", 0),  # 双方基于同一快照 count=0
        ]
        succeeded = _merge_debate_updates(
            st, updates, state_key="investment_debate_state", side_keys=["bull", "bear"]
        )
        ds = st["investment_debate_state"]
        assert succeeded == ["bull", "bear"]
        assert ds["rounds"] == serial_rounds
        assert ds["count"] == 2
        # messages 固定侧序
        assert st["messages"] == ["msg-bull", "msg-bear"]

    def test_merge_second_round(self):
        st = {
            "investment_debate_state": {"rounds": [{"bull": "b0", "bear": "e0"}], "count": 2},
            "reports": {}, "messages": [],
        }
        updates = [
            _mk_update_inv("bull", "bull-r1", 2),
            _mk_update_inv("bear", "bear-r1", 2),
        ]
        _merge_debate_updates(
            st, updates, state_key="investment_debate_state", side_keys=["bull", "bear"]
        )
        ds = st["investment_debate_state"]
        assert ds["rounds"] == [
            {"bull": "b0", "bear": "e0"},
            {"bull": "bull-r1", "bear": "bear-r1"},
        ]
        assert ds["count"] == 4

    def test_one_side_failed(self):
        st = {"investment_debate_state": {"rounds": [], "count": 0}, "reports": {}, "messages": []}
        updates = [
            _mk_update_inv("bull", "bull-r0", 0),
            {},  # Bear 失败降级：空 update
        ]
        succeeded = _merge_debate_updates(
            st, updates, state_key="investment_debate_state", side_keys=["bull", "bear"]
        )
        ds = st["investment_debate_state"]
        assert succeeded == ["bull"]
        assert ds["rounds"] == [{"bull": "bull-r0"}]  # bear 缺席该轮
        assert ds["count"] == 1


class TestPhase3Merge:
    def _mk_update_risk(self, side: str, content: str, count_snapshot: int) -> dict:
        idx = count_snapshot // 3
        rounds: list = [{} for _ in range(idx + 1)]
        rounds[idx][side] = content
        return {
            "risk_debate_state": {"rounds": rounds, "count": count_snapshot + 1},
            "reports": {f"{side}_analyst": f"partial-{side}"},
            "messages": [f"msg-{side}"],
        }

    def test_three_way_merge_and_latest_speaker(self):
        st = {"risk_debate_state": {"rounds": [], "count": 0}, "reports": {}, "messages": []}
        updates = [
            self._mk_update_risk("risky", "risky-r0", 0),
            self._mk_update_risk("safe", "safe-r0", 0),
            self._mk_update_risk("neutral", "neutral-r0", 0),
        ]
        succeeded = _merge_debate_updates(
            st, updates, state_key="risk_debate_state",
            side_keys=["risky", "safe", "neutral"], has_latest_speaker=True,
        )
        ds = st["risk_debate_state"]
        assert succeeded == ["risky", "safe", "neutral"]
        assert ds["rounds"] == [{"risky": "risky-r0", "safe": "safe-r0", "neutral": "neutral-r0"}]
        assert ds["count"] == 3
        # 旧串行轮末侧为 neutral → latest_speaker 等价
        assert ds["latest_speaker"] == "neutral"

    def test_last_speaker_skips_failed_side(self):
        st = {"risk_debate_state": {"rounds": [], "count": 0}, "reports": {}, "messages": []}
        updates = [
            self._mk_update_risk("risky", "risky-r0", 0),
            {},  # safe 失败
            self._mk_update_risk("neutral", "neutral-r0", 0),
        ]
        _merge_debate_updates(
            st, updates, state_key="risk_debate_state",
            side_keys=["risky", "safe", "neutral"], has_latest_speaker=True,
        )
        ds = st["risk_debate_state"]
        assert ds["count"] == 2
        assert "safe" not in ds["rounds"][0]
        assert ds["latest_speaker"] == "neutral"  # 固定顺序最后一个有产出者

    def test_all_sides_failed(self):
        st = {"risk_debate_state": {"rounds": [], "count": 0}, "reports": {}, "messages": []}
        succeeded = _merge_debate_updates(
            st, [{}, {}, {}], state_key="risk_debate_state",
            side_keys=["risky", "safe", "neutral"], has_latest_speaker=True,
        )
        assert succeeded == []
        assert st["risk_debate_state"]["count"] == 0
        assert "latest_speaker" not in st["risk_debate_state"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
