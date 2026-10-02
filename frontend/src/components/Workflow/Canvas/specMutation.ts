import type { InputBinding, NodeSpecDto, StageSpecDto, WorkflowSpecDto } from '@/api/workflows'
import {
  ALL_UPSTREAM,
  bandNodeId,
  declaredBindingEntries,
  effectiveStateKey,
  memberNodeId,
  removeConnection,
  resolveBindingProducer,
  stageMemberSlugs,
  stageMembers,
  type AgentMeta,
} from './edgeRules'

/**
 * spec 成员变更纯函数（设计文档 §5.3 两层模型的操作层）：
 * 拖放落点 / palette 点击 / 表单选择三个入口共用，保证派生规则唯一。
 * 「任意智能体」原则：约束只保留后端 validator 的硬边界——
 * - 辩手：任意类型均可（sides 只要求命中 nodes 库，执行层统一走辩手发言路径）
 * - 裁决：type 必须 judge/terminal（validator 硬约束），非 judge 类型不进裁决位
 * - 单智能体：任意类型均可（须命中 nodes 库）
 * - 显式批：非 analyst 成员必须先在 spec.nodes 派生 NodeSpec；analyst 裸引用即可
 */

/** spec.nodes 已占用的报告键集合（report_keys 全工作流唯一约束） */
function occupiedReportKeys(spec: WorkflowSpecDto): Set<string> {
  const used = new Set<string>()
  for (const n of spec.nodes) for (const k of n.report_keys || []) used.add(k)
  return used
}

/** 智能体库条目 → NodeSpec（registry 英文锚优先；过滤与他节点冲突的报告键） */
export function deriveNodeSpec(spec: WorkflowSpecDto, agent: AgentMeta): NodeSpecDto {
  const used = occupiedReportKeys(spec)
  return {
    slug: agent.slug,
    type: agent.kind,
    execution: agent.kind === 'analyst' ? 'tool_loop' : 'single_turn',
    memory: null,
    node_name: agent.node_name || agent.name || agent.slug,
    event_key: agent.event_key || agent.slug,
    report_keys: agent.report_keys.filter((k) => !used.has(k)),
    terminal: false,
  }
}

/** spec.nodes 无该 slug 时派生补建（返回是否新建） */
export function ensureNodeSpec(spec: WorkflowSpecDto, agent: AgentMeta): boolean {
  if (spec.nodes.some((n) => n.slug === agent.slug)) return false
  spec.nodes.push(deriveNodeSpec(spec, agent))
  return true
}

// ── 添加到已有阶段：先判定（plan，不改 spec）后执行（apply）────────────────

export type StageAddAction =
  | { kind: 'push'; needNodeSpec: boolean }
  | { kind: 'add-side' }
  | { kind: 'confirm-pool-switch'; needNodeSpec: boolean }
  | { kind: 'confirm-replace-judge' }
  | { kind: 'confirm-replace-single' }
  | { kind: 'none'; reason: string }

/** 类型适配矩阵（kind × 目标组模式 → 动作/拒绝理由；边界=后端 validator 硬约束） */
export function planStageAdd(spec: WorkflowSpecDto, stageId: string, agent: AgentMeta): StageAddAction {
  const stage = spec.stages.find((s) => s.id === stageId)
  if (!stage) return { kind: 'none', reason: '目标组不存在' }

  if (stage.mode === 'parallel_batch') {
    if ((stage.nodes || []).some((n) => n.ref === agent.slug)) {
      return { kind: 'none', reason: '该智能体已是本组成员' }
    }
    if (stage.pool) return { kind: 'confirm-pool-switch', needNodeSpec: agent.kind !== 'analyst' }
    return { kind: 'push', needNodeSpec: agent.kind !== 'analyst' }
  }
  if (stage.mode === 'debate') {
    // judge 类型 → 裁决位；其余任意类型 → 辩手位（validator 对 sides 无 type 约束）
    if (agent.kind === 'judge' || agent.kind === 'terminal') {
      if (stage.judge === agent.slug) return { kind: 'none', reason: '该智能体已是本组裁决' }
      if ((stage.sides || []).includes(agent.slug)) return { kind: 'none', reason: '辩手不可兼任裁决' }
      return { kind: 'confirm-replace-judge' }
    }
    if (stage.judge === agent.slug) return { kind: 'none', reason: '该智能体是本组裁决，不可兼任辩手' }
    if ((stage.sides || []).includes(agent.slug)) return { kind: 'none', reason: '该智能体已是本组辩手' }
    return { kind: 'add-side' }
  }
  // single：任意类型可当唯一成员（分析师会退化为单轮产出，不执行工具循环）
  if (stage.node === agent.slug) return { kind: 'none', reason: '该智能体已是本组成员' }
  return { kind: 'confirm-replace-single' }
}

/** 无确认场景直接执行（push / add-side）；返回是否有变更 */
export function applyStageAdd(spec: WorkflowSpecDto, stageId: string, agent: AgentMeta): boolean {
  const plan = planStageAdd(spec, stageId, agent)
  const stage = spec.stages.find((s) => s.id === stageId)
  if (!stage) return false
  if (plan.kind === 'push') {
    if (plan.needNodeSpec) ensureNodeSpec(spec, agent)
    stage.nodes = [...(stage.nodes || []), { ref: agent.slug }]
    return true
  }
  if (plan.kind === 'add-side') {
    ensureNodeSpec(spec, agent)
    stage.sides = [...(stage.sides || []), agent.slug]
    return true
  }
  return false
}

/** pool 动态批 → 显式枚举并加入该智能体（失去「新分析师自动纳入」，须先确认） */
export function applyPoolSwitchAndAdd(spec: WorkflowSpecDto, stageId: string, agent: AgentMeta): boolean {
  const stage = spec.stages.find((s) => s.id === stageId)
  if (!stage || stage.mode !== 'parallel_batch' || !stage.pool) return false
  if (agent.kind !== 'analyst') ensureNodeSpec(spec, agent)
  stage.pool = undefined
  stage.nodes = [{ ref: agent.slug }]
  if (!stage.concurrency) stage.concurrency = 3
  return true
}

/**
 * terminal 标记随裁决转移（仅当旧裁决持有时——多辩论段工作流中非终段裁决
 * 不带 terminal，更换不应凭空造出第二个决策写入者）。
 */
export function transferTerminal(spec: WorkflowSpecDto, fromSlug: string, toSlug: string): void {
  const from = spec.nodes.find((n) => n.slug === fromSlug)
  const to = spec.nodes.find((n) => n.slug === toSlug)
  if (!from?.terminal) return
  from.terminal = false
  if (to) to.terminal = true
}

/** 更换辩论组裁决（确认后执行）：terminal 标记随旧 judge 转移到新 judge */
export function applyReplaceJudge(spec: WorkflowSpecDto, stageId: string, agent: AgentMeta): boolean {
  const stage = spec.stages.find((s) => s.id === stageId)
  if (!stage || stage.mode !== 'debate') return false
  ensureNodeSpec(spec, agent)
  const oldJudge = stage.judge
  if (oldJudge && oldJudge !== agent.slug) transferTerminal(spec, oldJudge, agent.slug)
  stage.judge = agent.slug
  return true
}

/** 更换单智能体阶段成员（确认后执行） */
export function applyReplaceSingle(spec: WorkflowSpecDto, stageId: string, agent: AgentMeta): boolean {
  const stage = spec.stages.find((s) => s.id === stageId)
  if (!stage || stage.mode !== 'single') return false
  ensureNodeSpec(spec, agent)
  stage.node = agent.slug
  return true
}

// ── 新建阶段 ─────────────────────────────────────────────────────────────────

/** 首个不与现有阶段冲突的 stage_N id（修复「删除后 length+1 碰撞」） */
export function nextStageId(spec: WorkflowSpecDto): string {
  const used = new Set(spec.stages.map((s) => s.id))
  for (let i = 1; ; i++) {
    const id = `stage_${i}`
    if (!used.has(id)) return id
  }
}

export interface CreatedStage {
  stage: StageSpecDto
  /** 建段后的引导提示（辩论组还缺辩手/裁决等） */
  hint?: string
}

/**
 * 空白落点：按智能体 kind 落到唯一可执行的组型（后端执行约束）——
 * analyst 只挂并行装配器；trader/summary 在 single 工厂白名单；
 * 辩手/裁决/终端只在辩论组可执行（辩手位/裁决位），单独成组启动即失败。
 */
export function createStageForAgent(spec: WorkflowSpecDto, agent: AgentMeta): CreatedStage {
  const id = nextStageId(spec)
  if (agent.kind === 'analyst') {
    return {
      stage: { id, mode: 'parallel_batch', nodes: [{ ref: agent.slug }], concurrency: 3 },
    }
  }
  if (agent.kind === 'debater' || agent.kind === 'judge' || agent.kind === 'terminal') {
    ensureNodeSpec(spec, agent)
    const isJudge = agent.kind === 'judge' || agent.kind === 'terminal'
    return {
      stage: {
        id,
        mode: 'debate',
        sides: isJudge ? [] : [agent.slug],
        judge: isJudge ? agent.slug : '',
        state_key: `${id}_state`,
        rounds: 1,
        report_view: 'generic',
        inputs: {},
        // 辩论组默认运行时可关（发起分析时可跳过）；并行/单智能体组结构性必跑
        optional: true,
      },
      hint: isJudge
        ? `已创建辩论组并把「${agent.name}」放入裁决位：裁决/终端类智能体在辩论组内运行，请继续拖入至少 2 方辩手`
        : '已创建公平辩论组：继续从左侧拖入辩手（任意类型智能体均可，至少 2 方）与 1 名裁决',
    }
  }
  ensureNodeSpec(spec, agent)
  return { stage: { id, mode: 'single', node: agent.slug, inputs: {} } }
}

export type StrategyMode = 'parallel_batch' | 'debate' | 'single'

/** 可拖出的空策略模块（single 无空模块——单个智能体直接拖空白即建组） */
export type GroupModuleMode = Exclude<StrategyMode, 'single'>

/**
 * 空策略组（并行 / 公平辩论）：不预填任何成员——
 * 用户拖出区域后自由拖入智能体，不被旧流水线框架束缚。
 */
export function blankGroupOf(spec: WorkflowSpecDto, mode: GroupModuleMode): StageSpecDto {
  const id = nextStageId(spec)
  if (mode === 'parallel_batch') return { id, mode, nodes: [], concurrency: 3 }
  return {
    id,
    mode: 'debate',
    sides: [],
    judge: '',
    state_key: `${id}_state`,
    rounds: 1,
    report_view: 'generic',
    inputs: {},
    // 辩论组默认运行时可关（发起分析时可跳过）；并行/单智能体组结构性必跑
    optional: true,
  }
}

/** 建组后的引导提示（palette 点击 / 画布拖出 / 工具栏共用） */
export const GROUP_ADD_HINTS: Record<GroupModuleMode, string> = {
  parallel_batch: '并行组已创建：从左侧拖入任意智能体（组内并行执行）',
  debate: '公平辩论组已创建：从左侧拖入任意智能体当辩手（至少 2 方，支持多智能体）与 1 名裁决；默认可关（发起分析时可跳过）',
}

/**
 * 命中测试：落点所在组矩形（倒序取最上层——与节点 zIndex/渲染序一致）。
 * palette 拖放、成员跨组拖动、插入索引三处共用同一命中口径。
 */
export function bandAtPoint<T extends { x: number; y: number; width: number; height: number }>(
  bandRects: T[],
  point: { x: number; y: number },
): T | null {
  for (let i = bandRects.length - 1; i >= 0; i--) {
    const b = bandRects[i]
    if (point.x >= b.x && point.x <= b.x + b.width && point.y >= b.y && point.y <= b.y + b.height) {
      return b
    }
  }
  return null
}

/** 落点流坐标 → stages 数组插入索引（2D：落点在某组矩形内 → 该组之后；空白 → 末尾追加） */
export function insertIndexAtPoint(
  spec: WorkflowSpecDto,
  bandRects: { x: number; y: number; width: number; height: number }[],
  point: { x: number; y: number },
): number {
  // 命中即在对应组数组序之后插入
  const hit = bandAtPoint(bandRects, point)
  if (!hit) return spec.stages.length
  return Math.min(bandRects.indexOf(hit) + 1, spec.stages.length)
}

// ── 重排与删除（自由画布：执行序 = 数组序；变更前先检测连线失效）────────────

/** 一条因重排/删除而失效的连线声明（消费方仍声明、生产者已不可向前引用） */
export interface BrokenBinding {
  consumerStageId: string
  /** 消费方节点 id（band:{stageId} / node:{stageId}:{slug}），removeConnection 直接可用 */
  consumerNodeId: string
  slot: string
  value: string
  producerStageId: string
}

/** 是否存在有效的终点节点（terminal:true 且类型合法——validator 同口径） */
export function hasActiveTerminal(spec: WorkflowSpecDto): boolean {
  return spec.nodes.some((n) => n.terminal && (n.type === 'judge' || n.type === 'terminal'))
}

/** splice 移动 stages 数组元素（表单 moveStage 交换的泛化，支持跨多位） */
export function applyStageMove(spec: WorkflowSpecDto, from: number, to: number): void {
  const stages = spec.stages
  if (from === to || from < 0 || to < 0 || from >= stages.length || to >= stages.length) return
  const [moved] = stages.splice(from, 1)
  stages.splice(to, 0, moved)
}

/**
 * 重排失效检测：模拟移动后，凡「生产者旧序在消费方之前、新序不再在前」的声明即失效
 * （validator 只准向前引用）。all_upstream 与本就悬空的声明跳过（顺序无关/存量问题）。
 */
export function detectReorderBreakage(
  spec: WorkflowSpecDto,
  agents: AgentMeta[],
  from: number,
  to: number,
): BrokenBinding[] {
  if (from === to) return []
  const ids = spec.stages.map((s) => s.id)
  const [moved] = ids.splice(from, 1)
  ids.splice(to, 0, moved)
  const newIdxOf = (id: string) => ids.indexOf(id)
  const oldIdxOf = (id: string) => spec.stages.findIndex((s) => s.id === id)
  const broken: BrokenBinding[] = []
  for (const entry of declaredBindingEntries(spec)) {
    if (entry.value === ALL_UPSTREAM) continue
    const producer = resolveBindingProducer(spec, agents, entry.value, entry.stageId)
    if (!producer) continue
    if (oldIdxOf(producer.stageId) >= oldIdxOf(entry.stageId)) continue
    if (newIdxOf(producer.stageId) >= newIdxOf(entry.stageId)) {
      broken.push({
        consumerStageId: entry.stageId,
        consumerNodeId: entry.nodeId,
        slot: entry.slot,
        value: entry.value,
        producerStageId: producer.stageId,
      })
    }
  }
  return broken
}

/** 删除组的可选前置声明（确认文案聚合用） */
export interface StageRemovalPlan {
  memberCount: number
  /** 该组产出被其他组消费的连线（删除组时一并摘除声明） */
  brokenBindings: BrokenBinding[]
  hasTerminalMember: boolean
}

export function planStageRemoval(
  spec: WorkflowSpecDto,
  agents: AgentMeta[],
  stageId: string,
): StageRemovalPlan | null {
  const stage = spec.stages.find((s) => s.id === stageId)
  if (!stage) return null
  // pool 动态批需展开计数与终点检测；其余模式显式成员即全集
  const memberSlugs =
    stage.mode === 'debate'
      ? stageMemberSlugs(stage)
      : stageMembers(spec, stage, agents).map((m) => m.slug)
  const brokenBindings = declaredBindingEntries(spec)
    .filter((e) => e.stageId !== stageId)
    .filter((e) => {
      const producer = resolveBindingProducer(spec, agents, e.value, e.stageId)
      return producer?.stageId === stageId
    })
    .map((e) => ({
      consumerStageId: e.stageId,
      consumerNodeId: e.nodeId,
      slot: e.slot,
      value: e.value,
      producerStageId: stageId,
    }))
  return {
    memberCount: memberSlugs.length,
    brokenBindings,
    hasTerminalMember: memberSlugs.some((slug) => {
      const def = spec.nodes.find((n) => n.slug === slug)
      return def?.terminal === true
    }),
  }
}

/** 删除组：先摘除下游消费声明（防悬空键被保存校验拒绝），再 splice（不动 spec.nodes） */
export function applyStageRemoval(spec: WorkflowSpecDto, agents: AgentMeta[], stageId: string): boolean {
  const plan = planStageRemoval(spec, agents, stageId)
  if (!plan) return false
  for (const b of plan.brokenBindings) {
    removeConnection(spec, b.consumerNodeId, b.slot, b.value)
  }
  const stages = spec.stages
  const idx = stages.findIndex((s) => s.id === stageId)
  if (idx < 0) return false
  stages.splice(idx, 1)
  return true
}

/** 成员移除方案（按组模式分派；forbidden = 交互上不可删） */
export type MemberRemovalPlan =
  | {
      kind: 'remove-ref' | 'remove-side' | 'clear-judge' | 'clear-node'
      brokenBindings: BrokenBinding[]
      /** 移除后该组处于草稿态（缺成员/缺裁决，保存校验将拒绝，需补齐） */
      leavesDraft: boolean
      draftReason?: string
      /** 移除的是持有 terminal 标记的裁决（决策写入者随之缺席） */
      removesTerminal: boolean
    }
  | { kind: 'forbidden'; reason: string }

export function planMemberRemoval(
  spec: WorkflowSpecDto,
  agents: AgentMeta[],
  stageId: string,
  slug: string,
): MemberRemovalPlan {
  const stage = spec.stages.find((s) => s.id === stageId)
  if (!stage) return { kind: 'forbidden', reason: '目标组不存在' }

  const isProducerOf = (entry: { nodeId: string; stageId: string; value: string }): boolean => {
    const producer = resolveBindingProducer(spec, agents, entry.value, entry.stageId)
    if (!producer) return false
    if (producer.nodeId === memberNodeId(stageId, slug)) return true
    // 裁决报告键经组端口（band out:r:）对外——移除裁决即失去该产出
    return (
      stage.mode === 'debate' &&
      stage.judge === slug &&
      producer.nodeId === bandNodeId(stageId) &&
      (spec.nodes.find((n) => n.slug === slug)?.report_keys || []).includes(entry.value)
    )
  }
  const brokenBindings = declaredBindingEntries(spec)
    .filter((e) => e.stageId !== stageId)
    .filter(isProducerOf)
    .map((e) => ({
      consumerStageId: e.stageId,
      consumerNodeId: e.nodeId,
      slot: e.slot,
      value: e.value,
      producerStageId: stageId,
    }))

  if (stage.mode === 'parallel_batch') {
    if (!(stage.nodes || []).some((n) => n.ref === slug)) {
      return { kind: 'forbidden', reason: '自动纳入的分析师成员不可单独删除；可切换为指定成员模式后调整' }
    }
    // 空并行组可通过校验（nodes:[] 与 pool 二选一检查允许空枚举）
    return { kind: 'remove-ref', brokenBindings, leavesDraft: false, removesTerminal: false }
  }
  if (stage.mode === 'debate') {
    if (stage.judge === slug) {
      return {
        kind: 'clear-judge',
        brokenBindings,
        leavesDraft: true,
        draftReason: '组将缺少裁决',
        removesTerminal: spec.nodes.find((n) => n.slug === slug)?.terminal === true,
      }
    }
    if ((stage.sides || []).includes(slug)) {
      const remaining = (stage.sides || []).filter((s) => s !== slug)
      return {
        kind: 'remove-side',
        brokenBindings,
        leavesDraft: remaining.length < 2,
        draftReason: remaining.length < 2 ? '辩手将少于 2 方' : undefined,
        removesTerminal: false,
      }
    }
    return { kind: 'forbidden', reason: '该智能体不是本组成员' }
  }
  // single
  if (stage.node !== slug) return { kind: 'forbidden', reason: '该智能体不是本组成员' }
  return {
    kind: 'clear-node',
    brokenBindings,
    leavesDraft: true,
    draftReason: '组将缺少成员',
    removesTerminal: false,
  }
}

/** 从组移除成员（batch 过滤 refs / side 过滤 / 裁决与单成员清空；连带摘除下游声明） */
export function applyMemberRemoval(spec: WorkflowSpecDto, agents: AgentMeta[], stageId: string, slug: string): boolean {
  const plan = planMemberRemoval(spec, agents, stageId, slug)
  if (plan.kind === 'forbidden') return false
  const stage = spec.stages.find((s) => s.id === stageId)
  if (!stage) return false
  for (const b of plan.brokenBindings) {
    removeConnection(spec, b.consumerNodeId, b.slot, b.value)
  }
  if (plan.kind === 'remove-ref') {
    stage.nodes = (stage.nodes || []).filter((n) => n.ref !== slug)
  } else if (plan.kind === 'remove-side') {
    stage.sides = (stage.sides || []).filter((s) => s !== slug)
  } else if (plan.kind === 'clear-judge') {
    stage.judge = ''
  } else {
    stage.node = ''
  }
  return true
}

// ── state_key 变更迁移 ─────────────────────────────────────────────────────

/**
 * 辩论组 state_key 改名时迁移全 spec 的引用值：裸键 oldKey（辩论全记录）与
 * 点路径 oldKey.field（裁决字段）替换为新键，存量连线跟随改名不断线。
 * newKey 为空 = 回落到 id 兜底键（与 effectiveStateKey 同口径）。
 * 须在 stage.state_key 被赋新值之前调用（旧键由当前 spec 推导）。
 */
export function migrateStateKeyRefs(spec: WorkflowSpecDto, stageId: string, newKey: string): void {
  const stage = spec.stages.find((s) => s.id === stageId)
  if (!stage || stage.mode !== 'debate') return
  const oldKey = effectiveStateKey(stage)
  const nextKey = newKey.trim() || `${stage.id}_state`
  if (nextKey === oldKey) return

  const rewrite = (v: string): string =>
    v === oldKey ? nextKey : v.startsWith(`${oldKey}.`) ? `${nextKey}${v.slice(oldKey.length)}` : v
  const rewriteBinding = (b: InputBinding): InputBinding =>
    Array.isArray(b) ? b.map(rewrite) : rewrite(b)

  for (const st of spec.stages) {
    if (st.inputs) {
      for (const key of Object.keys(st.inputs)) st.inputs[key] = rewriteBinding(st.inputs[key])
    }
    for (const ref of st.nodes || []) {
      if (ref.inputs) {
        for (const key of Object.keys(ref.inputs)) ref.inputs[key] = rewriteBinding(ref.inputs[key])
      }
    }
  }
}
