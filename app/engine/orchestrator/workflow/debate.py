"""辩论组拓扑上下文（P4-a N 方泛化）。

executor 在物化辩论组成员（辩手/judge）时构造 DebateGroup 下发工厂，
工厂不再各自硬编码 per_turn / state_key / 对手集合 / 报告派生视图：
- 内置工作流：group 值与工厂缺省路径（per_turn=2/3、固定 state_key、
  counterpart 查表）逐字一致，golden 等价锁定
- 自定义 N 方辩论：sides 任意长度，side_key = 内置查表 / 自定义 slug，
  报告视图 = make_generic_report_content 按 sides 元数据物化

放置说明：agents 工厂与 workflow executor 共同依赖，且不依赖任何
agents/workflow 子模块，独立成模块避免双向 import。
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

# 辩论报告派生视图签名：(debate_state, side_key) -> 报告正文
ReportView = Callable[[Optional[Dict], str], str]

# 内置辩论侧 slug → rounds[idx] 内的 side key（共享权威表）：
# executor 物化侧工厂与 compiler 推导记忆反思声明（MemoryReflection.side_key）
# 共用；自定义辩手无条目 → side_key = slug 本身（无歧义，报告/历史视图按键派生）
BUILTIN_DEBATE_SIDE_KEYS: Dict[str, str] = {
    "bull-researcher": "bull",
    "bear-researcher": "bear",
    "risky-analyst": "risky",
    "safe-analyst": "safe",
    "neutral-analyst": "neutral",
}


@dataclass(frozen=True)
class DebateGroup:
    """单个辩论阶段（DebateStage）的运行时拓扑快照。

    state_key: 辩论 state 在黑板上的键（rounds/count/judge_decision 载体）
    per_turn:  每轮发言人数 = len(sides)（轮次推进 count//per_turn）
    sides:     [(side_key, 显示标签), ...] 固定侧序（barrier 合并/公平性依据）；
               显示标签 = registry/NodeSpec 的 node_name（内置侧的个性措辞
               仍由工厂查 _SIDE_CONFIG，标签仅用于自定义侧）
    report_view: rounds -> reports 黑板的报告派生视图
    event_phase: 阶段事件相位（组内工厂 run_node_turn 事件对齐 stage.event_phase）
    judge_decision_field: judge 兼任 terminal 时写入的顶层决策字段（空 = 非终端）
    """

    state_key: str
    per_turn: int
    sides: Tuple[Tuple[str, str], ...]
    report_view: ReportView
    event_phase: str = ""
    judge_decision_field: str = ""

    def side_labels(self) -> Dict[str, str]:
        """side_key → 显示标签（触发语对手名单等文案用）"""
        return dict(self.sides)

    def opponents_of(self, side_key: str) -> List[Tuple[str, str]]:
        """某侧的全部对手（固定侧序，不含自身）"""
        return [(sk, label) for sk, label in self.sides if sk != side_key]

    def opponent_names(self, side_key: str) -> str:
        """对手名单文案（「 和 」连接，debator 触发语对手括号内文案）"""
        return " 和 ".join(label for sk, label in self.sides if sk != side_key)


@dataclass(frozen=True)
class DebateNodeBinding:
    """辩论组成员（辩手/judge）的物化指令（executor → 工厂）。

    slug/node_name/event_key/report_key 来自 PlannedNode（编译期冻结）；
    side_key 仅辩手有值（rounds[idx] 内的键）；memory 为记忆槽位名（可空）。
    """

    slug: str
    node_name: str
    event_key: str
    report_key: str
    side_key: str = ""
    memory: str = ""
    terminal: bool = False
    extra: Dict[str, object] = field(default_factory=dict)
