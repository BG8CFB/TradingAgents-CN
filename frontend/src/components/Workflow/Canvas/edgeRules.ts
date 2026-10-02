import type { InputBinding, StageSpecDto, WorkflowSpecDto } from '@/api/workflows'

/**
 * 画布连线规则（设计文档 §5.3）：
 * - 连线不是新执行语义，而是 inputs 声明（stage.inputs / NodeRef.inputs）的图形化载体
 * - 输出端口 kind：report（节点报告键）| field（judge 裁决字段，值为 state_key.field
 *   点路径）| state（辩论全记录 state_key）| all（all_upstream 选择器，仅泳道段有）
 * - 连线校验：方向（只能上游段 → 下游段）、辩论组封闭（组员不直接对外）、
 *   标量槽单来源（field 绑定语义）
 */

export const ALL_UPSTREAM = 'all_upstream'

export interface OutPort {
  /** handle id（画布端口标识） */
  id: string
  /** 写入 binding 的值 */
  key: string
  label: string
  kind: 'report' | 'field' | 'state' | 'all'
}

export interface InSlot {
  slot: string
  /** 标量槽：仅接受单来源（field/state 点路径绑定语义；report 键列表语义不受限） */
  scalar: boolean
}

/** 智能体库元数据（画布成员枚举 + 端口派生 + NodeSpec 派生） */
export interface AgentMeta {
  slug: string
  name: string
  phase: number
  report_keys: string[]
  template_slots: string[]
  /** 节点类型（registry 权威；库外兜底：phase1→analyst 其余→debater） */
  kind: string
  /** registry 执行节点名锚（NodeSpec.node_name 派生用） */
  node_name?: string
  /** registry 事件键锚（NodeSpec.event_key 派生用） */
  event_key?: string
}

export function agentMetaFromList(items: {
  slug: string
  phase: number
  report_keys?: string[]
  kind?: string
  node_name?: string
  event_key?: string
  spec: { name?: string; template_inputs?: { slot?: string }[] }
}[]): AgentMeta[] {
  return items.map((it) => ({
    slug: it.slug,
    name: it.spec?.name || it.slug,
    phase: it.phase ?? 0,
    report_keys: it.report_keys || [],
    template_slots: (it.spec?.template_inputs || []).map((t) => t.slot || '').filter(Boolean),
    kind: it.kind || (it.phase === 1 ? 'analyst' : 'debater'),
    node_name: it.node_name,
    event_key: it.event_key,
  }))
}

// ── 节点 id 约定 ─────────────────────────────────────────────────────────────
// 泳道段：band:{stageId}；段内成员：node:{stageId}:{slug}

export const bandNodeId = (stageId: string) => `band:${stageId}`
export const memberNodeId = (stageId: string, slug: string) => `node:${stageId}:${slug}`

export function parseNodeId(
  id: string,
): { kind: 'band'; stageId: string } | { kind: 'node'; stageId: string; slug: string } | null {
  if (id.startsWith('band:')) return { kind: 'band', stageId: id.slice(5) }
  if (id.startsWith('node:')) {
    const rest = id.slice(5)
    const idx = rest.indexOf(':')
    if (idx > 0) return { kind: 'node', stageId: rest.slice(0, idx), slug: rest.slice(idx + 1) }
  }
  return null
}

// ── 输出端口 ────────────────────────────────────────────────────────────────

/**
 * 辩论组 state 键的有效值（state_key 缺省时以 stage id 兜底）。
 * 写入（canConnect）、端口派生（bandOutPorts）、解析（resolveBindingSource）
 * 三侧必须同口径，否则出现「写入成功、派生消失」的悬空连线。
 */
export function effectiveStateKey(stage: Pick<StageSpecDto, 'id' | 'state_key'>): string {
  return stage.state_key || `${stage.id}_state`
}

/**
 * 泳道段的对外输出端口：
 * - 任意段：all_upstream 聚合端口（「全部上游」）
 * - 辩论段：judge 报告键 + 裁决字段（state_key.judge_decision）+ 辩论全记录（state_key）
 */
export function bandOutPorts(spec: WorkflowSpecDto, stage: StageSpecDto): OutPort[] {
  const ports: OutPort[] = [
    { id: 'out:all', key: ALL_UPSTREAM, label: '全部上游', kind: 'all' },
  ]
  if (stage.mode !== 'debate') return ports

  const judgeDef = spec.nodes.find((n) => n.slug === stage.judge)
  const stateKey = effectiveStateKey(stage)
  for (const key of judgeDef?.report_keys || []) {
    ports.push({ id: `out:r:${key}`, key, label: key, kind: 'report' })
  }
  ports.push({
    id: 'out:f:judge_decision',
    key: `${stateKey}.judge_decision`,
    label: '裁决字段 judge_decision',
    kind: 'field',
  })
  ports.push({ id: `out:s:${stateKey}`, key: stateKey, label: `辩论全记录 ${stateKey}`, kind: 'state' })
  return ports
}

/** 成员节点输出端口：报告键（spec.nodes 定义；分析师取 agent 库 report_keys） */
export function nodeOutPorts(
  spec: WorkflowSpecDto,
  slug: string,
  agents: AgentMeta[],
): OutPort[] {
  const nodeDef = spec.nodes.find((n) => n.slug === slug)
  const keys = nodeDef?.report_keys?.length
    ? nodeDef.report_keys
    : agents.find((a) => a.slug === slug)?.report_keys || []
  return keys.map((key) => ({ id: `out:r:${key}`, key, label: key, kind: 'report' as const }))
}

// ── 输入槽 ─────────────────────────────────────────────────────────────────

const SCALAR_SLOTS = new Set(['judge_decision'])

/** 消费者输入槽：契约槽（agent 库 template_inputs）∪ 已声明 inputs 键 */
export function consumerInSlots(
  slots: string[],
  declared: Record<string, InputBinding> | undefined,
): InSlot[] {
  const merged = new Set<string>(slots)
  for (const key of Object.keys(declared || {})) merged.add(key)
  return [...merged].map((slot) => ({ slot, scalar: SCALAR_SLOTS.has(slot) }))
}

// ── 绑定解析（spec → 边）───────────────────────────────────────────────────

export interface BindingEdge {
  /** 边 id 需全局唯一且可逆解析 */
  id: string
  source: string
  sourceHandle: string
  target: string
  targetHandle: string
  bindingKey: string
}

function stageIndexOf(spec: WorkflowSpecDto, stageId: string): number {
  return spec.stages.findIndex((s) => s.id === stageId)
}

/** 绑定值 → 生产者定位（供重排/删除的失效检测复用；all_upstream 与悬空值返回 null） */
export function resolveBindingProducer(
  spec: WorkflowSpecDto,
  agents: AgentMeta[],
  value: string,
  consumerStageId: string,
): { nodeId: string; stageId: string; slug?: string } | null {
  if (value === ALL_UPSTREAM) return null
  const src = resolveBindingSource(spec, agents, value, consumerStageId)
  if (!src) return null
  const parsed = parseNodeId(src.nodeId)
  return parsed ? { nodeId: src.nodeId, stageId: parsed.stageId, slug: parsed.kind === 'node' ? parsed.slug : undefined } : null
}

export interface DeclaredBindingEntry {
  /** 消费方组 id */
  stageId: string
  /** 消费方节点 id（band:{stageId} 或 node:{stageId}:{slug}） */
  nodeId: string
  slot: string
  value: string
}

/** 枚举 spec 内全部已声明绑定（debate/single 组输入 + batch 成员 NodeRef 输入） */
export function declaredBindingEntries(spec: WorkflowSpecDto): DeclaredBindingEntry[] {
  const entries: DeclaredBindingEntry[] = []
  const pushValue = (stageId: string, nodeId: string, slot: string, binding: InputBinding) => {
    if (Array.isArray(binding)) binding.forEach((v) => entries.push({ stageId, nodeId, slot, value: v }))
    else if (binding) entries.push({ stageId, nodeId, slot, value: binding })
  }
  for (const stage of spec.stages) {
    if (stage.mode === 'debate') {
      for (const [slot, binding] of Object.entries(stage.inputs || {})) {
        pushValue(stage.id, bandNodeId(stage.id), slot, binding)
      }
    } else if (stage.mode === 'single' && stage.node) {
      for (const [slot, binding] of Object.entries(stage.inputs || {})) {
        pushValue(stage.id, memberNodeId(stage.id, stage.node), slot, binding)
      }
    } else {
      for (const ref of stage.nodes || []) {
        for (const [slot, binding] of Object.entries(ref.inputs || {})) {
          pushValue(stage.id, memberNodeId(stage.id, ref.ref), slot, binding)
        }
      }
    }
  }
  return entries
}

/** 单个绑定值 → 源端口定位（找不到生产者时返回 null，该绑定不出现在画布） */
function resolveBindingSource(
  spec: WorkflowSpecDto,
  agents: AgentMeta[],
  value: string,
  consumerStageId: string,
): { nodeId: string; port: OutPort } | null {
  if (value === ALL_UPSTREAM) {
    // 聚合端口取紧邻上游段（视觉近似；语义 = 全部上游）
    const idx = stageIndexOf(spec, consumerStageId)
    for (let i = idx - 1; i >= 0; i--) {
      return { nodeId: bandNodeId(spec.stages[i].id), port: { id: 'out:all', key: ALL_UPSTREAM, label: '全部上游', kind: 'all' } }
    }
    return null
  }
  const dotted = value.match(/^([\w-]+)\.([\w-]+)$/)
  if (dotted) {
    // state_key.field → 裁决字段端口（judge 裁决；只认严格上游的辩论段，与裸键分支同口径）
    const consumerIdx = stageIndexOf(spec, consumerStageId)
    const stage = spec.stages.find(
      (s) => s.mode === 'debate' && effectiveStateKey(s) === dotted[1] && stageIndexOf(spec, s.id) < consumerIdx,
    )
    if (stage) {
      return {
        nodeId: bandNodeId(stage.id),
        port: { id: `out:f:${dotted[2]}`, key: value, label: `裁决字段 ${dotted[2]}`, kind: 'field' },
      }
    }
    return null
  }
  // 裸键：报告键或 state_key → 逐段找生产者（辩论段查 band 端口，其余查成员端口）
  for (const stage of spec.stages) {
    if (stage.id === consumerStageId) break
    if (stage.mode === 'debate') {
      const judgeDef = spec.nodes.find((n) => n.slug === stage.judge)
      if ((judgeDef?.report_keys || []).includes(value)) {
        return { nodeId: bandNodeId(stage.id), port: { id: `out:r:${value}`, key: value, label: value, kind: 'report' } }
      }
      if (effectiveStateKey(stage) === value) {
        return { nodeId: bandNodeId(stage.id), port: { id: `out:s:${value}`, key: value, label: `辩论全记录 ${value}`, kind: 'state' } }
      }
      // 辩手报告（bull_researcher 等）从辩手成员端口出
      for (const side of stage.sides || []) {
        if (nodeOutPorts(spec, side, agents).some((p) => p.key === value)) {
          return { nodeId: memberNodeId(stage.id, side), port: { id: `out:r:${value}`, key: value, label: value, kind: 'report' } }
        }
      }
      continue
    }
    const members = stageMembers(spec, stage, agents)
    for (const m of members) {
      if (nodeOutPorts(spec, m.slug, agents).some((p) => p.key === value)) {
        return { nodeId: memberNodeId(stage.id, m.slug), port: { id: `out:r:${value}`, key: value, label: value, kind: 'report' } }
      }
    }
  }
  return null
}

export interface StageMember {
  slug: string
  name: string
  /** pool 动态成员（不在 spec 显式枚举中） */
  dynamic: boolean
}

/** 阶段成员：batch（pool → 智能体库 phase1 全集；显式枚举 → refs）；single → node */
export function stageMembers(
  spec: WorkflowSpecDto,
  stage: StageSpecDto,
  agents: AgentMeta[],
): StageMember[] {
  if (stage.mode === 'parallel_batch') {
    if (stage.pool) {
      return agents
        .filter((a) => a.phase === 1)
        .map((a) => ({ slug: a.slug, name: a.name, dynamic: true }))
    }
    return (stage.nodes || []).map((ref) => {
      const def = spec.nodes.find((n) => n.slug === ref.ref)
      const meta = agents.find((a) => a.slug === ref.ref)
      return { slug: ref.ref, name: def?.node_name || meta?.name || ref.ref, dynamic: false }
    })
  }
  if (stage.mode === 'single' && stage.node) {
    const def = spec.nodes.find((n) => n.slug === stage.node)
    const meta = agents.find((a) => a.slug === stage.node)
    return [{ slug: stage.node, name: def?.node_name || meta?.name || stage.node, dynamic: false }]
  }
  return []
}

/**
 * 阶段显式成员 slug（纯 spec 口径，不展开 pool 动态成员）：
 * palette「已在流」、成员移除、终点检测等只关心 spec 里写定的引用。
 */
export function stageMemberSlugs(stage: StageSpecDto): string[] {
  if (stage.mode === 'debate') {
    return [...(stage.sides || []), stage.judge].filter((s): s is string => Boolean(s))
  }
  if (stage.mode === 'single') return stage.node ? [stage.node] : []
  return (stage.nodes || []).map((n) => n.ref)
}

/** 解析失败的绑定声明（画布上无对应边，目标卡片以红色虚线警示标记提示） */
export interface DanglingBinding {
  /** 消费方节点 id（band:{stageId} 或 node:{stageId}:{slug}） */
  nodeId: string
  slot: string
  value: string
  reason: string
}

export interface BindingGraph {
  edges: BindingEdge[]
  /** 声明了 inputs 但解析不出生产者（或声明位置无效）的条目 */
  dangling: DanglingBinding[]
}

/**
 * spec → 画布边全集 + 悬空声明。辩论组输入、single 输入正常派生边；
 * batch 成员 NodeRef.inputs 是编译期丢弃的无效声明（canConnect 同口径拒绝），
 * 不渲染假边而计入悬空警示。
 */
export function buildBindingGraph(spec: WorkflowSpecDto, agents: AgentMeta[]): BindingGraph {
  const edges: BindingEdge[] = []
  const dangling: DanglingBinding[] = []
  const push = (
    target: string,
    slot: string,
    value: string,
    consumerStageId: string,
  ) => {
    const src = resolveBindingSource(spec, agents, value, consumerStageId)
    if (!src) {
      dangling.push({ nodeId: target, slot, value, reason: '上游不存在该产出键（生产者已删除或改名）' })
      return
    }
    edges.push({
      id: `e:${src.nodeId}:${src.port.id}:${target}:${slot}:${value}`,
      source: src.nodeId,
      sourceHandle: src.port.id,
      target,
      targetHandle: `in:${slot}`,
      bindingKey: value,
    })
  }
  const pushBinding = (
    target: string,
    slot: string,
    binding: InputBinding,
    consumerStageId: string,
    producerOnly = false,
  ) => {
    const values = Array.isArray(binding) ? binding : binding ? [binding] : []
    if (producerOnly) {
      for (const v of values) {
        dangling.push({ nodeId: target, slot, value: v, reason: '并行批成员不消费输入（编译期被丢弃）' })
      }
      return
    }
    for (const v of values) push(target, slot, v, consumerStageId)
  }

  for (const stage of spec.stages) {
    if (stage.mode === 'debate') {
      for (const [slot, binding] of Object.entries(stage.inputs || {})) {
        pushBinding(bandNodeId(stage.id), slot, binding, stage.id)
      }
    } else if (stage.mode === 'single' && stage.node) {
      for (const [slot, binding] of Object.entries(stage.inputs || {})) {
        pushBinding(memberNodeId(stage.id, stage.node), slot, binding, stage.id)
      }
    } else {
      for (const ref of stage.nodes || []) {
        for (const [slot, binding] of Object.entries(ref.inputs || {})) {
          pushBinding(memberNodeId(stage.id, ref.ref), slot, binding, stage.id, true)
        }
      }
    }
  }
  return { edges, dangling }
}

// ── 连线校验（拖线时）─────────────────────────────────────────────────────

export interface ConnectContext {
  spec: WorkflowSpecDto
  agents: AgentMeta[]
}

export interface ConnectDecision {
  ok: boolean
  reason?: string
  /** 校验通过时写入的绑定值 */
  value?: string
}

export function canConnect(
  ctx: ConnectContext,
  sourceNodeId: string,
  sourceHandle: string,
  targetNodeId: string,
  targetHandle: string,
): ConnectDecision {
  const src = parseNodeId(sourceNodeId)
  const dst = parseNodeId(targetNodeId)
  if (!src || !dst) return { ok: false, reason: '未知节点' }
  if (sourceNodeId === targetNodeId) return { ok: false, reason: '不能连接自身' }

  const srcStage = ctx.spec.stages.find((s) => s.id === src.stageId)
  const dstStage = ctx.spec.stages.find((s) => s.id === dst.stageId)
  if (!srcStage || !dstStage) return { ok: false, reason: '未知阶段' }

  const srcIdx = stageIndexOf(ctx.spec, src.stageId)
  const dstIdx = stageIndexOf(ctx.spec, dst.stageId)
  if (dstIdx <= srcIdx) {
    return { ok: false, reason: `只能从序号靠前的组连向序号靠后的组（源 #${srcIdx + 1} → 目标 #${dstIdx + 1}，画布按序号执行）` }
  }

  // 辩论组封闭：组员（辩手/裁决）不直接对外
  if (src.kind === 'node' && srcStage.mode === 'debate' && src.slug !== srcStage.judge) {
    return { ok: false, reason: '辩论组辩手由模式封装，请连接组输入' }
  }
  if (dst.kind === 'node' && dstStage.mode === 'debate') {
    return { ok: false, reason: '辩论组成员由组输入统一注入，请连到辩论组端口' }
  }
  // 并行组成员 = 纯生产者（编译器丢弃 NodeRef.inputs，执行期不消费），拒绝假连线
  if (dst.kind === 'node' && dstStage.mode === 'parallel_batch') {
    return { ok: false, reason: '并行组成员是纯生产者（产出报告供下游引用），不消费上游输入' }
  }
  // single 段的输入端口在节点上（dstStage.mode === 'single' 允许）

  const slot = targetHandle.startsWith('in:') ? targetHandle.slice(3) : ''
  if (!slot) return { ok: false, reason: '目标不是输入槽端口' }

  // 计算写入值
  let value: string
  if (src.kind === 'band') {
    if (sourceHandle === 'out:all') value = ALL_UPSTREAM
    else if (sourceHandle.startsWith('out:f:')) {
      value = `${effectiveStateKey(srcStage)}.${sourceHandle.slice(5)}`
    } else if (sourceHandle.startsWith('out:s:')) {
      value = sourceHandle.slice(5)
    } else if (sourceHandle.startsWith('out:r:')) {
      value = sourceHandle.slice(5)
    } else return { ok: false, reason: '未知输出端口' }
  } else {
    if (!sourceHandle.startsWith('out:r:')) return { ok: false, reason: '未知输出端口' }
    value = sourceHandle.slice(5)
  }

  // 标量槽单来源（field 绑定语义 + all_upstream 单值）
  const existing = declaredBinding(ctx.spec, dst, slot)
  const isScalar =
    SCALAR_SLOTS.has(slot) ||
    (existing !== null &&
      (existing === ALL_UPSTREAM || /^[\w-]+\.[\w-]+$/.test(String(existing))))
  if (existing !== null) {
    if (isScalar) return { ok: false, reason: `槽 ${slot} 仅接受单一来源` }
    const list = Array.isArray(existing) ? existing : [existing]
    if (list.includes(value)) return { ok: false, reason: '该连线已存在' }
  }
  return { ok: true, value }
}

/** 读取消费者（band 组输入 / single 节点 / batch 成员）已声明的槽绑定 */
export function declaredBinding(
  spec: WorkflowSpecDto,
  target: { kind: 'band' | 'node'; stageId: string; slug?: string },
  slot: string,
): InputBinding | null {
  const stage = spec.stages.find((s) => s.id === target.stageId)
  if (!stage) return null
  if (target.kind === 'band' || stage.mode === 'single') {
    return (stage.inputs || {})[slot] ?? null
  }
  const ref = (stage.nodes || []).find((n) => n.ref === target.slug)
  return (ref?.inputs || {})[slot] ?? null
}

// ── spec 变更（连线落库 / 删除连线）────────────────────────────────────────

/** 确保 stage.inputs（debate/single）可写 */
function stageInputs(stage: StageSpecDto): Record<string, InputBinding> {
  if (!stage.inputs) stage.inputs = {}
  return stage.inputs
}

/** 连线写入 inputs 声明（返回 false = 无可写目标） */
export function applyConnection(
  spec: WorkflowSpecDto,
  targetNodeId: string,
  slot: string,
  value: string,
): boolean {
  const dst = parseNodeId(targetNodeId)
  if (!dst) return false
  const stage = spec.stages.find((s) => s.id === dst.stageId)
  if (!stage) return false

  if (dst.kind === 'band' || stage.mode === 'single') {
    const inputs = stageInputs(stage)
    const existing = inputs[slot]
    if (existing === undefined || existing === null) {
      inputs[slot] = value
    } else if (Array.isArray(existing)) {
      if (!existing.includes(value)) existing.push(value)
    } else if (existing !== value) {
      inputs[slot] = [existing, value]
    }
    return true
  }
  // batch 成员 NodeRef
  if (!stage.nodes) stage.nodes = []
  let ref = stage.nodes.find((n) => n.ref === dst.slug)
  if (!ref) {
    ref = { ref: dst.slug }
    stage.nodes.push(ref)
  }
  if (!ref.inputs) ref.inputs = {}
  const existing = ref.inputs[slot]
  if (existing === undefined || existing === null) ref.inputs[slot] = value
  else if (Array.isArray(existing)) {
    if (!existing.includes(value)) existing.push(value)
  } else if (existing !== value) ref.inputs[slot] = [existing, value]
  return true
}

/** 删除连线 = 移除对应声明（值从槽绑定中去掉；空槽保留键由属性面板清理） */
export function removeConnection(
  spec: WorkflowSpecDto,
  targetNodeId: string,
  slot: string,
  value: string,
): boolean {
  const dst = parseNodeId(targetNodeId)
  if (!dst) return false
  const stage = spec.stages.find((s) => s.id === dst.stageId)
  if (!stage) return false

  const shrink = (binding: InputBinding | undefined | null): InputBinding | undefined => {
    if (binding === null || binding === undefined) return undefined
    if (Array.isArray(binding)) {
      const next = binding.filter((v) => v !== value)
      return next.length ? next : undefined
    }
    return binding === value ? undefined : binding
  }
  if (dst.kind === 'band' || stage.mode === 'single') {
    const next = shrink((stage.inputs || {})[slot])
    if (next === undefined) delete (stage.inputs || {})[slot]
    else (stage.inputs || {})[slot] = next
    return true
  }
  const ref = (stage.nodes || []).find((n) => n.ref === dst.slug)
  if (!ref?.inputs) return false
  const next = shrink(ref.inputs[slot])
  if (next === undefined) delete ref.inputs[slot]
  else ref.inputs[slot] = next
  return true
}
