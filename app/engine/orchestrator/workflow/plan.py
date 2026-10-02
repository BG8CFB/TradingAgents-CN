"""CompiledPlan：WorkflowSpec + CompileParams 的编译产物（执行计划）。

设计定位（设计文档 §4.4）：
- spec 是静态蓝图，params 是每次任务的运行时裁剪；compile 是纯函数（无 I/O、无依赖注入）
- PlannedNode 持「绑定指令」（kind × memory × critical），不持工厂实例——
  工厂 materialize 需要 PipelineDeps（LLM 客户端/记忆），放 executor，使本模块可无 LLM/Mongo 单测
- 执行计划快照（snapshot）：任务启动时冻结 spec 版本 + 编译参数，在跑任务不受编辑影响
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple, Union

from .spec import CompileParams, InputBinding, NodeType, TerminalSpec

# 阶段输入声明（槽名 → 连线绑定）的不可变形态（frozen dataclass 字段要求）
StageInputs = Tuple[Tuple[str, InputBinding], ...]

# 记忆槽位（NodeSpec.memory 值域）→ 运行时依赖字段的绑定表权威定义
# （§4.5 记忆绑定泛化；executor 物化工厂与 runtime 反思遍历共用本表，
# 槽位实例分别在 PipelineDeps / TradingAgentsGraph 上以同名字段承载）
MEMORY_SLOT_FIELDS: Dict[str, str] = {
    "bull": "bull_memory",
    "bear": "bear_memory",
    "invest_judge": "invest_judge_memory",
    "trader": "trader_memory",
    "risk_manager": "risk_manager_memory",
}


@dataclass(frozen=True)
class PlannedNode:
    """单节点执行指令（编译期确定；工厂实例化在 executor）"""

    slug: str
    kind: NodeType
    node_name: str
    event_key: str
    report_key: str = ""  # 主报告键（辩论侧 rounds→reports 重派生用）
    memory: Optional[str] = None  # 记忆槽位名；executor 映射到 PipelineDeps 字段
    critical: bool = False  # 失败自动重试 1 次（judge/trader/summarizer）
    terminal: bool = False  # judge 兼任 terminal（写 workflow 声明的 decision_field）


@dataclass(frozen=True)
class PlannedBatch:
    """并行批阶段（分析师段）：slug 列表运行时经 build_analyst_specs 装配"""

    stage_id: str
    event_phase: str
    slugs: Tuple[str, ...]  # 选中分析师 slug（保持提交序；无效项由装配层跳过并告警）
    concurrency: int = 5


@dataclass(frozen=True)
class PlannedDebate:
    """辩论阶段：N 方公平轮次 + judge 裁决（rounds 为附加轮数，总轮 = rounds+1）"""

    stage_id: str
    event_phase: str
    state_key: str
    sides: Tuple[PlannedNode, ...]
    judge: PlannedNode
    rounds: int
    report_view: str
    inputs: StageInputs = ()  # 组输入声明（executor 阶段开始快照 → state["_stage_inputs"]）


@dataclass(frozen=True)
class PlannedSingle:
    """单节点阶段（trader / summary）"""

    stage_id: str
    event_phase: str
    node: PlannedNode
    inputs: StageInputs = ()  # 节点输入声明（同上）


PlannedStage = Union[PlannedBatch, PlannedDebate, PlannedSingle]


@dataclass(frozen=True)
class MemoryReflection:
    """单条记忆绑定的反思输入声明（P4-b，编译期从计划推导）。

    反思（回测路径）按本声明驱动：每个绑定了记忆槽的节点在任务结束后
    把「自己的历史产出」反思入对应记忆库，不再读固定辩论键：
    - debater：state_key 辩论 state 内 side_key 的累积发言史（argument 格式）
    - judge：state_key 辩论 state 的 judge_decision
    - single：report_key 主报告键（黑板优先、顶层回退）
    component_key = 反思 LLM 调用的 token 归属标识（内置节点保持旧
    reflector 专用方法的口径，自定义节点 = slug）
    """

    slot: str
    component_key: str
    kind: str  # "debater" | "judge" | "single"
    state_key: str = ""
    side_key: str = ""
    label: str = ""  # debater 发言史的 argument 标签（内置侧 = 权威 tag，自定义 = node_name）
    report_key: str = ""


@dataclass(frozen=True)
class CompiledPlan:
    """编译产物：有序阶段执行计划 + 冻结的编译参数（快照源）"""

    workflow_slug: str
    spec_version: int
    spec_hash: str
    stages: Tuple[PlannedStage, ...]
    terminal: TerminalSpec
    params: CompileParams
    memory_reflections: Tuple[MemoryReflection, ...] = ()
    compiled_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def total_units(self, analyst_count: Optional[int] = None) -> int:
        """进度原子单元总数（等权计数）：批阶段节点数 + 辩论(侧×(rounds+1)+judge) + 单节点。

        analyst_count：批阶段实际装配数（运行时 build_analyst_specs 后回填）；
        缺省用编译期 slugs 数（无效 slug 未被装配层过滤时的上界估计）。
        """
        units = 0
        for stage in self.stages:
            if isinstance(stage, PlannedBatch):
                units += analyst_count if analyst_count is not None else len(stage.slugs)
            elif isinstance(stage, PlannedDebate):
                units += len(stage.sides) * (stage.rounds + 1) + 1  # +1 = judge
            else:
                units += 1
        return units

    def snapshot(self) -> Dict[str, Any]:
        """执行计划快照（落 state["_plan_snapshot"]，随任务持久化；编辑 spec 不影响在跑任务）。

        params 用 JSON 模式序列化（tuple → list），保证 Mongo/JSON roundtrip 形状稳定。
        terminal / memory_reflections 为 P4-b 终端契约与反思声明：出口信号探取
        （runtime）与回测反思遍历从快照读取，在跑任务不受 spec 编辑影响。
        """
        return {
            "workflow_slug": self.workflow_slug,
            "spec_version": self.spec_version,
            "spec_hash": self.spec_hash,
            "params": self.params.model_dump(mode="json"),
            "terminal": self.terminal.model_dump(mode="json"),
            "memory_reflections": [
                {
                    "slot": r.slot,
                    "component_key": r.component_key,
                    "kind": r.kind,
                    "state_key": r.state_key,
                    "side_key": r.side_key,
                    "label": r.label,
                    "report_key": r.report_key,
                }
                for r in self.memory_reflections
            ],
            "compiled_at": self.compiled_at,
        }
