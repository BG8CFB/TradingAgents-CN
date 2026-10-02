"""WorkflowSpec 数据模型（P2 拓扑数据化；P3 输入契约与连线）。

对应设计文档 §4.2/4.3/4.6（docs/superpowers/specs/2026-09-14-workflow-generalization-design.md）：
- NodeSpec = 全局库层的节点类型定义（是什么）；P2 种子仅内置 9 个非分析师节点，
  字段从 P1 registry（app/engine/orchestrator/registry.py）逐项誊抄，由 validator
  做一致性锚点校验（防两处漂移）。分析师仍以 phase1 YAML 为权威（pool 引用）
- WorkflowSpec = 拓扑定义（怎么接）：三类 stage（parallel_batch / debate / single）
- P3：template_inputs 契约（agent_specs 库条目字段，声明「节点需要什么」）+
  inputs 连线（WorkflowSpec 层，声明「槽接哪个上游」）+ submit_report 提交协议

行为约束（golden 等价前提）：本模型只描述「遍历什么」；执行机制（重试/事件/公平
barrier/黑板合并）仍在 pipeline executor，不受本模型影响。
"""

from enum import Enum
from typing import Annotated, Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

# 辩论轮数安全上限（与 pipeline.MAX_ROUNDS 一致；compiler clamp 用）
MAX_ROUNDS = 10

# 全部上游主输出选择器（宽松模式，仅自定义工作流；内置默认工作流逐槽显式枚举）
ALL_UPSTREAM = "all_upstream"


class NodeType(str, Enum):
    """节点类型（设计文档 §4.2 类型表；与 registry.KIND_* 对应 + terminal 独立类型）。

    terminal 是「最终决策产出」类型；内置 risk-manager 为 judge 兼任 terminal
    （NodeSpec.terminal 标记，decision_field 由 workflow.terminal 声明指向其输出）。
    """

    ANALYST = "analyst"
    DEBATER = "debater"
    JUDGE = "judge"
    TRADER = "trader"
    SUMMARIZER = "summarizer"
    TERMINAL = "terminal"


class Execution(str, Enum):
    """执行语义：tool_loop（工具循环）| single_turn（单轮）"""

    TOOL_LOOP = "tool_loop"
    SINGLE_TURN = "single_turn"


class NodePool(str, Enum):
    """动态节点池选择器（内置默认工作流专用）。

    phase1_analysts = phase1 YAML 全部分析师（registry 动态段）。保持现状
    「phase1 新增分析师立即可选」的行为；自定义工作流的显式枚举池是 P5 范围。
    """

    PHASE1_ANALYSTS = "phase1_analysts"


# 记忆槽位（NodeSpec.memory 值域；槽位 → PipelineDeps 字段的绑定表在 executor）
MEMORY_SLOTS: Tuple[str, ...] = ("bull", "bear", "invest_judge", "trader", "risk_manager")


class InputSlot(BaseModel):
    """template_inputs 契约条目（库层：agent_specs 条目字段，只声明「需要什么」不连线）。

    slot: 槽名（prompt 占位符 {{inputs.槽名}} 引用）
    required: True = 编译期校验裁剪后的执行计划仍满足该槽，否则拒绝任务
    required_sources: 槽内必须解析成功的来源键（编译期 fail-fast；内置工作流用它
        把「市场技术/短线资金不可裁」正式化——裁掉产出这些键的分析师即拒绝任务）
    missing_policy: 非必需槽缺失时注入的降级文案（空 = 注入「暂无」占位；
        trader 的 judge_decision 兜底「暂无研究部主管裁决」即此模式）
    """

    model_config = ConfigDict(frozen=True)

    slot: str
    required: bool = False
    required_sources: Tuple[str, ...] = ()
    missing_policy: str = ""


# 槽连线值：str = 单来源（report 键 / field 点路径 / all_upstream 选择器）；
# List[str] = 报告键集合（report 槽的多源语义）。连线属于工作流实例层（NodeRef.inputs）
InputBinding = Union[str, List[str]]


def normalize_binding(binding: InputBinding) -> Tuple[str, ...]:
    """连线值 → 键元组（str 单值 / list 展开），渲染器与校验共用"""
    if isinstance(binding, str):
        return (binding,)
    return tuple(binding)


class NodeSpec(BaseModel):
    """全局库层节点定义（类型定义，非实例配置）。

    slug: 库内全局唯一
    node_name: 旧英文执行节点名（"Bull Researcher"）——node_timings/进度/golden 锚，
        与 registry.AgentIdentity.node_name 逐字一致（validator 锚点校验项）
    event_key: 事件流 agent_key（与各节点 run_conversation 内事件对齐）
    report_keys: 归属本节点的报告键全集（含历史别名；标题解析语义，非产出写入集）
    memory: 记忆槽绑定（None = 无记忆）；槽位 → deps 字段映射在 executor
    terminal: judge 兼任 terminal 标记（decision_field 写入者）
    builtin: 内置只读标记（P2 种子全部 True；fork 机制是 P5 范围）
    """

    model_config = ConfigDict(frozen=True)

    slug: str
    type: NodeType
    execution: Execution
    memory: Optional[Literal["bull", "bear", "invest_judge", "trader", "risk_manager"]] = None
    node_name: str
    event_key: str
    report_keys: Tuple[str, ...] = ()
    terminal: bool = False
    builtin: bool = True

    @model_validator(mode="after")
    def _execution_matches_type(self) -> "NodeSpec":
        """执行语义与类型强绑定（构造期拒绝，DB 写坏的数据在 load 即失败）：
        analyst = 工具循环；debater/judge/trader/summarizer/terminal = 单轮。
        """
        if self.type == NodeType.ANALYST and self.execution != Execution.TOOL_LOOP:
            raise ValueError(f"{self.slug}: analyst 节点 execution 必须为 tool_loop（当前 {self.execution.value}）")
        if self.type != NodeType.ANALYST and self.execution != Execution.SINGLE_TURN:
            raise ValueError(
                f"{self.slug}: {self.type.value} 节点 execution 必须为 single_turn（当前 {self.execution.value}）"
            )
        return self


class NodeRef(BaseModel):
    """工作流层节点引用（实例配置）：ref 指向库 slug；inputs = 槽 → 上游连线（P3）"""

    model_config = ConfigDict(frozen=True)

    ref: str
    default_selected: Optional[bool] = None
    inputs: Dict[str, InputBinding] = Field(default_factory=dict)


class Stage(BaseModel):
    """stage 公共基类：id 工作流内唯一；optional=false 的 stage 不可被 params 关闭

    event_phase：事件流相位（state["_phase"] / 事件 phase 字段），与 stage id 分离——
    id 按设计文档命名（research_debate 等），event_phase 保持历史值（research 等），
    golden 事件序列与历史回放不受 stage 改名影响。缺省回落 stage.id。
    """

    model_config = ConfigDict(frozen=True)

    id: str
    optional: bool = False
    event_phase: Optional[str] = None


class ParallelBatchStage(Stage):
    """并行批阶段（分析师段）：nodes 显式枚举或 pool 动态池（二选一）"""

    mode: Literal["parallel_batch"] = "parallel_batch"
    nodes: Tuple[NodeRef, ...] = ()
    pool: Optional[NodePool] = None
    concurrency: int = Field(default=5, ge=1)


class DebateStage(Stage):
    """辩论阶段：N 方辩手轮次公平发言 + judge 裁决（rounds 为附加轮数，总轮 = rounds+1）

    report_view：辩论报告派生视图名（rounds → reports 黑板的重派生函数），
    compiler 经视图注册表绑定实现；P2 内置 investment / risk 两视图，P4 可扩展。
    inputs：组输入（槽 → 上游连线）——注入全体辩手与 judge 的公共上游报告，
    辩手/ judge 的节点级连线在各自 NodeRef.inputs（P4 N 方泛化时形状不变）。
    """

    mode: Literal["debate"] = "debate"
    state_key: str
    sides: Tuple[str, ...]
    rounds: int = Field(default=1, ge=0, le=MAX_ROUNDS)
    judge: str
    report_view: str = "investment"
    inputs: Dict[str, InputBinding] = Field(default_factory=dict)


class SingleStage(Stage):
    """单节点阶段（trader/summary）；inputs = 该节点的槽 → 上游连线（阶段级承载）"""

    mode: Literal["single"] = "single"
    node: str
    inputs: Dict[str, InputBinding] = Field(default_factory=dict)


StageSpec = Annotated[
    Union[ParallelBatchStage, DebateStage, SingleStage],
    Field(discriminator="mode"),
]


class TerminalSpec(BaseModel):
    """终端契约：最终决策字段 + 信号回退链（点路径）+ 总结节点"""

    model_config = ConfigDict(frozen=True)

    decision_field: str
    signal_fallback: Tuple[str, ...] = ()
    summary_node: str


class WorkflowSpec(BaseModel):
    """工作流拓扑定义（种子 YAML 的 schema）。

    version: schema 版本（当前 1）
    nodes: 库层内置节点（P2 = 9 个非分析师节点；分析师经 pool 引 phase1）
    stages: 有序阶段列表（执行顺序 = 列表顺序）
    """

    model_config = ConfigDict(frozen=True)

    version: int = 1
    slug: str
    name: str
    description: str = ""
    enabled: bool = True
    builtin: bool = True
    terminal: TerminalSpec
    nodes: Tuple[NodeSpec, ...] = ()
    stages: Tuple[StageSpec, ...] = ()

    def node_by_slug(self, slug: str) -> Optional[NodeSpec]:
        """slug → 库内 NodeSpec（未命中 None）"""
        for node in self.nodes:
            if node.slug == slug:
                return node
        return None

    def stage_by_id(self, stage_id: str) -> Optional[Stage]:
        """stage id → StageSpec（未命中 None）"""
        for stage in self.stages:
            if stage.id == stage_id:
                return stage
        return None


class StageOverride(BaseModel):
    """单阶段运行时覆盖（CompileParams.stage_overrides 的值类型）"""

    model_config = ConfigDict(frozen=True)

    enabled: Optional[bool] = None
    rounds: Optional[int] = None
    concurrency: Optional[int] = None


class CompileParams(BaseModel):
    """编译参数：spec 是静态蓝图，params 是每次任务的运行时裁剪（设计文档 §4.4）。

    selected_nodes: parallel_batch 阶段节点子集（承接 selected_analysts）
    stage_overrides: 阶段启停/轮数/并发覆盖（承接 phaseN_enabled / phaseN_debate_rounds 等）
    """

    model_config = ConfigDict(frozen=True)

    selected_nodes: Tuple[str, ...] = ()
    stage_overrides: Dict[str, StageOverride] = Field(default_factory=dict)
