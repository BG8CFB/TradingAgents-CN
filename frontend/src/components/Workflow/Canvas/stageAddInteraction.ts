import { ElMessage, ElMessageBox } from 'element-plus'
import type { WorkflowSpecDto } from '@/api/workflows'
import { removeConnection, type AgentMeta } from './edgeRules'
import {
  applyMemberRemoval,
  applyPoolSwitchAndAdd,
  applyReplaceJudge,
  applyReplaceSingle,
  applyStageAdd,
  applyStageMove,
  applyStageRemoval,
  detectReorderBreakage,
  planMemberRemoval,
  planStageAdd,
  planStageRemoval,
  type BrokenBinding,
} from './specMutation'

/**
 * 「智能体加入阶段」交互入口（palette 点击 / 画布 drop 共用）：
 * plan 判定 → push/add-side 直接执行，confirm 类弹框确认后执行，
 * none 拒绝提示。spec 变更规则全部委托 specMutation.ts（三入口唯一派生）。
 * 返回是否有变更（调用方据此 markDirty）。
 */
export async function addAgentToStage(
  spec: WorkflowSpecDto,
  stageId: string,
  agent: AgentMeta,
): Promise<boolean> {
  const plan = planStageAdd(spec, stageId, agent)
  const label = `${agent.name}（${agent.slug}）`

  if (plan.kind === 'none') {
    ElMessage.warning(plan.reason)
    return false
  }
  if (plan.kind === 'push' || plan.kind === 'add-side') {
    const changed = applyStageAdd(spec, stageId, agent)
    if (changed) ElMessage.success(`已将 ${label} 加入组「${stageId}」`)
    return changed
  }
  if (plan.kind === 'confirm-pool-switch') {
    try {
      await ElMessageBox.confirm(
        `该并行组当前是自动模式（全部分析师自动加入）。改为指定成员后将失去自动纳入，本次以 ${label} 作为成员之一。是否继续？`,
        '切换为指定成员',
        { type: 'warning', confirmButtonText: '切换并加入', cancelButtonText: '取消' },
      )
    } catch {
      return false
    }
    applyPoolSwitchAndAdd(spec, stageId, agent)
    ElMessage.success(`已切换为指定成员并加入 ${label}`)
    return true
  }
  if (plan.kind === 'confirm-replace-judge') {
    try {
      await ElMessageBox.confirm(
        `是否将组「${stageId}」的裁决更换为 ${label}？如原裁决持有 terminal（决策写入）标记，将随之转移。`,
        '更换裁决',
        { type: 'warning', confirmButtonText: '更换', cancelButtonText: '取消' },
      )
    } catch {
      return false
    }
    applyReplaceJudge(spec, stageId, agent)
    ElMessage.success(`组「${stageId}」裁决已更换为 ${label}`)
    return true
  }
  // confirm-replace-single
  try {
    await ElMessageBox.confirm(
      `组「${stageId}」当前是单智能体组，是否将成员更换为 ${label}？`,
      '换单智能体组成员',
      { type: 'warning', confirmButtonText: '更换', cancelButtonText: '取消' },
    )
  } catch {
    return false
  }
  applyReplaceSingle(spec, stageId, agent)
  ElMessage.success(`组「${stageId}」成员已更换为 ${label}`)
  return true
}

// ── 删除与重排（键盘 Delete / 属性面板按钮 / 框选批量 / band ↑↓ 共用入口）────

/** 删除目标（画布选中集解析结果；band 已选时其成员不单独重复删） */
export interface RemovalTarget {
  type: 'band' | 'node'
  stageId: string
  slug?: string
}

function formatBindings(bindings: BrokenBinding[]): string {
  const uniq = [...new Map(bindings.map((b) => [`${b.consumerNodeId}|${b.slot}|${b.value}`, b])).values()]
  const lines = uniq.slice(0, 5).map((b) => `· ${b.value} → 组「${b.consumerStageId}」槽 ${b.slot}`)
  if (uniq.length > 5) lines.push(`· ……共 ${uniq.length} 条`)
  return lines.join('\n')
}

/**
 * 删除选中组/成员：聚合影响面 → 一次确认（成员数/连带连线/草稿态/终点缺席）
 * → 确认后先摘连线再删实体。不删 spec.nodes（节点库定义保留，可能被契约引用）。
 */
export async function removeSelectionInteractive(
  spec: WorkflowSpecDto,
  agents: AgentMeta[],
  targets: RemovalTarget[],
): Promise<boolean> {
  const valid = targets.filter((t) => spec.stages.some((s) => s.id === t.stageId))
  const bandIds = new Set(valid.filter((t) => t.type === 'band').map((t) => t.stageId))
  const stageTargets = valid.filter((t) => t.type === 'band')
  const memberTargets = valid.filter((t) => t.type === 'node' && !bandIds.has(t.stageId))
  if (!stageTargets.length && !memberTargets.length) return false

  const forbiddenNotes: string[] = []
  const draftNotes: string[] = []
  const brokenAll: BrokenBinding[] = []
  let removesTerminal = false

  for (const t of stageTargets) {
    const plan = planStageRemoval(spec, agents, t.stageId)
    if (!plan) continue
    brokenAll.push(...plan.brokenBindings)
    if (plan.hasTerminalMember) removesTerminal = true
  }
  const memberPlans: { target: RemovalTarget; plan: ReturnType<typeof planMemberRemoval> }[] = []
  for (const t of memberTargets) {
    const plan = planMemberRemoval(spec, agents, t.stageId, t.slug || '')
    if (plan.kind === 'forbidden') {
      forbiddenNotes.push(plan.reason)
      continue
    }
    memberPlans.push({ target: t, plan })
    brokenAll.push(...plan.brokenBindings)
    if (plan.leavesDraft) draftNotes.push(`组「${t.stageId}」${plan.draftReason || '将变为草稿'}（保存校验将拒绝，需补成员）`)
    if (plan.removesTerminal) removesTerminal = true
  }
  if (!stageTargets.length && !memberPlans.length) {
    if (forbiddenNotes.length) ElMessage.warning([...new Set(forbiddenNotes)].join('；'))
    return false
  }

  const lines: string[] = []
  if (stageTargets.length) {
    const totalMembers = stageTargets.reduce((n, t) => n + (planStageRemoval(spec, agents, t.stageId)?.memberCount || 0), 0)
    lines.push(`删除 ${stageTargets.length} 个组（含 ${totalMembers} 个成员）`)
  }
  if (memberPlans.length) lines.push(`从组内移除 ${memberPlans.length} 个成员`)
  if (brokenAll.length) lines.push(`连带清除 ${brokenAll.length} 条下游连线：\n${formatBindings(brokenAll)}`)
  if (draftNotes.length) lines.push(`⚠ ${draftNotes.join('；')}`)
  if (removesTerminal && !hasActiveTerminalAfter(spec, stageTargets, memberPlans)) {
    lines.push('⚠ 移除后将没有终点节点（🏁）——最终决策将无写入者')
  }

  try {
    await ElMessageBox.confirm(lines.join('\n'), '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      customClass: 'ta-msgbox-preline',
    })
  } catch {
    return false
  }

  for (const b of [...new Map(brokenAll.map((b) => [`${b.consumerNodeId}|${b.slot}|${b.value}`, b])).values()]) {
    removeConnection(spec, b.consumerNodeId, b.slot, b.value)
  }
  for (const t of stageTargets) applyStageRemoval(spec, agents, t.stageId)
  for (const { target } of memberPlans) applyMemberRemoval(spec, agents, target.stageId, target.slug || '')
  if (forbiddenNotes.length) ElMessage.warning([...new Set(forbiddenNotes)].join('；'))
  return true
}

/** 估算删除后是否仍有终点：被删组/成员之外是否还引用着 terminal 节点 */
function hasActiveTerminalAfter(
  spec: WorkflowSpecDto,
  stageTargets: RemovalTarget[],
  memberPlans: { target: RemovalTarget }[],
): boolean {
  const removedStageIds = new Set(stageTargets.map((t) => t.stageId))
  const removedMemberKeys = new Set(memberPlans.map((m) => `${m.target.stageId}|${m.target.slug}`))
  const stillReferenced = new Set<string>()
  for (const stage of spec.stages) {
    if (removedStageIds.has(stage.id)) continue
    if (stage.mode === 'debate') {
      ;[...(stage.sides || []), stage.judge]
        .filter((s): s is string => Boolean(s))
        .forEach((slug) => {
          if (!removedMemberKeys.has(`${stage.id}|${slug}`)) stillReferenced.add(slug)
        })
    } else if (stage.mode === 'single' && stage.node) {
      if (!removedMemberKeys.has(`${stage.id}|${stage.node}`)) stillReferenced.add(stage.node)
    } else {
      ;(stage.nodes || []).forEach((n) => {
        if (!removedMemberKeys.has(`${stage.id}|${n.ref}`)) stillReferenced.add(n.ref)
      })
    }
  }
  return spec.nodes.some(
    (n) => n.terminal && (n.type === 'judge' || n.type === 'terminal') && stillReferenced.has(n.slug),
  )
}

/**
 * 重排执行序：预检向前引用失效（模拟移动 + 全量绑定复验）→ 无失效直接移动；
 * 有失效弹确认列出，确认后摘除失效声明再移动。band ↑↓ / 属性面板 / 表单共用。
 */
export async function reorderStageInteractive(
  spec: WorkflowSpecDto,
  agents: AgentMeta[],
  from: number,
  to: number,
): Promise<boolean> {
  if (from === to) return false
  const broken = detectReorderBreakage(spec, agents, from, to)
  if (broken.length) {
    try {
      await ElMessageBox.confirm(
        `移动后以下连线将违反「序号靠前 → 序号靠后」规则，确认后自动移除：\n${formatBindings(broken)}`,
        '调整执行顺序',
        { type: 'warning', confirmButtonText: '移动并移除连线', cancelButtonText: '取消' },
      )
    } catch {
      return false
    }
    for (const b of broken) removeConnection(spec, b.consumerNodeId, b.slot, b.value)
  }
  applyStageMove(spec, from, to)
  return true
}
