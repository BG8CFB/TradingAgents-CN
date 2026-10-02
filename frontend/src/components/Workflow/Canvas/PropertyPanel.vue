<template>
  <transition name="ppanel-slide">
    <div v-if="panelTarget" class="ppanel">
      <div class="ppanel-head">
        <span class="ppanel-title">{{ panelTarget.title }}</span>
        <el-button size="small" text circle :aria-label="'关闭属性面板'" @click="emit('close')">✕</el-button>
      </div>

      <!-- ── 节点选中：双区（工作流实例 / 全局定义只读）── -->
      <template v-if="panelTarget.kind === 'node'">
        <div class="ppanel-section">
          <div class="ppanel-section-title">工作流实例区（仅影响本工作流）</div>
          <template v-if="inputsEditable">
            <div class="ppanel-field-label">inputs 连线（槽 → 上游）</div>
            <BindingEditor
              :model-value="inputsModel"
              :upstream-keys="upstreamKeys"
              :disabled="readonly"
              @update:model-value="onInputsUpdate"
            />
          </template>
          <div v-else class="ppanel-muted">{{ inputsMutedReason }}</div>

          <el-button
            v-if="removable"
            size="small"
            type="danger"
            plain
            :disabled="readonly"
            class="ppanel-remove"
            @click="removeFromWorkflow"
          >
            从组内移除
          </el-button>
          <div v-else class="ppanel-muted ppanel-remove-hint">
            自动纳入的分析师成员不可单独删除；可切换为指定成员模式后调整
          </div>

          <div class="ppanel-field-label ppanel-terminal-label">终点（最终决策写入者）</div>
          <el-switch
            v-if="canBeTerminal"
            :model-value="isTerminalNode"
            :disabled="readonly"
            aria-label="设为终点节点"
            @update:model-value="(v: string | number | boolean) => onTerminalSwitch(v === true)"
          />
          <span v-else class="ppanel-muted">仅裁决（judge）/ 终端（terminal）类型可设为终点</span>
        </div>

        <div class="ppanel-section">
          <div class="ppanel-section-title">全局定义区（NodeSpec，智能体库维护）</div>
          <el-descriptions :column="1" size="small" border>
            <el-descriptions-item label="slug">{{ nodeSlug }}</el-descriptions-item>
            <el-descriptions-item label="type">{{ nodeDef?.type || '—' }}</el-descriptions-item>
            <el-descriptions-item label="execution">{{ nodeDef?.execution || '—' }}</el-descriptions-item>
            <el-descriptions-item label="memory">{{ nodeDef?.memory || '—' }}</el-descriptions-item>
            <el-descriptions-item label="report_keys">
              {{ (nodeDef?.report_keys || agentReportKeys).join('、') || '—' }}
            </el-descriptions-item>
          </el-descriptions>
          <router-link to="/settings/agents" class="ppanel-link">在智能体库中编辑 →</router-link>
        </div>
      </template>

      <!-- ── 组选中：执行顺序 + 组属性 + 组输入 + 删除 ── -->
      <template v-else>
        <div class="ppanel-section">
          <div class="ppanel-section-title">执行顺序</div>
          <div class="ppanel-order">
            <span>第 {{ stageIndex + 1 }} 位 / 共 {{ stageTotal }}</span>
            <el-button size="small" text :disabled="readonly || stageIndex <= 0" @click="moveStage(-1)">↑</el-button>
            <el-button
              size="small"
              text
              :disabled="readonly || stageIndex >= stageTotal - 1"
              @click="moveStage(1)"
            >
              ↓
            </el-button>
          </div>
          <div class="ppanel-muted">连线只允许从序号靠前的组连向序号靠后的组；移动时自动检测失效连线</div>
        </div>

        <div class="ppanel-section">
          <div class="ppanel-section-title">组属性</div>
          <el-form label-width="88px" label-position="left" size="small" :disabled="readonly">
            <el-form-item label="组 id">
              <span class="ppanel-muted">{{ stage?.id }}</span>
            </el-form-item>
            <el-form-item label="模式">
              <el-tag size="small" effect="plain">{{ MODE_LABEL[stage?.mode || ''] || stage?.mode }}</el-tag>
            </el-form-item>
            <el-form-item label="可选">
              <el-switch
                :model-value="stage?.optional === true"
                @update:model-value="(v: string | number | boolean) => setStage({ optional: v === true })"
              />
            </el-form-item>
            <div class="ppanel-muted ppanel-optional-hint">
              可选 = 发起分析时可按任务跳过整组；组内辩手/裁决不提供单独开关（公平辩论需全员参与）
            </div>
            <el-form-item v-if="stage?.mode === 'debate'" label="辩论轮次">
              <el-input-number
                :model-value="stage?.rounds ?? 1"
                :min="0"
                :max="10"
                size="small"
                @update:model-value="(v: number | undefined) => setStage({ rounds: typeof v === 'number' ? v : 1 })"
              />
            </el-form-item>
            <el-form-item v-if="stage?.mode === 'parallel_batch'" label="并发数">
              <el-input-number
                :model-value="stage?.concurrency ?? 3"
                :min="1"
                :max="10"
                size="small"
                @update:model-value="(v: number | undefined) => setStage({ concurrency: typeof v === 'number' ? v : 3 })"
              />
            </el-form-item>
            <el-form-item v-if="stage?.mode === 'debate'" label="state_key">
              <el-input
                :model-value="stage?.state_key"
                placeholder="如 investment_debate_state"
                @update:model-value="(v: string) => setStage({ state_key: v })"
              />
            </el-form-item>
            <el-form-item v-if="stage?.mode === 'debate'" label="报告视图">
              <el-input
                :model-value="stage?.report_view"
                placeholder="investment / risk"
                @update:model-value="(v: string) => setStage({ report_view: v })"
              />
            </el-form-item>
          </el-form>
        </div>

        <div v-if="stage?.mode === 'debate'" class="ppanel-section">
          <div class="ppanel-section-title">组输入（上游报告注入）</div>
          <BindingEditor
            :model-value="inputsModel"
            :upstream-keys="upstreamKeys"
            :disabled="readonly"
            @update:model-value="onInputsUpdate"
          />
        </div>

        <div class="ppanel-section">
          <el-button size="small" type="danger" plain :disabled="readonly" class="ppanel-remove" @click="removeGroup">
            删除组
          </el-button>
        </div>
      </template>
    </div>
  </transition>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ElMessage } from 'element-plus'
import BindingEditor from '@/components/Workflow/BindingEditor.vue'
import type { InputBinding, WorkflowSpecDto } from '@/api/workflows'
import { effectiveStateKey, nodeOutPorts, stageMemberSlugs, type AgentMeta } from './edgeRules'
import { hasActiveTerminal, migrateStateKeyRefs } from './specMutation'
import { removeSelectionInteractive, reorderStageInteractive } from './stageAddInteraction'

/**
 * 画布属性面板（§5.3 双区）：选中节点 = 工作流实例区（含终点开关/移除）+ 全局定义区
 * （只读，库中维护）；选中的组 = 执行顺序 + 组属性 + 组输入 + 删除。
 */

const props = defineProps<{
  spec: WorkflowSpecDto
  selection: { type: 'node' | 'band'; stageId: string; slug?: string } | null
  agents: AgentMeta[]
  readonly?: boolean
}>()

const emit = defineEmits<{
  (e: 'change'): void
  (e: 'close'): void
}>()

/** 组模式中文名（与画布/运行侧统一叫法：单智能体） */
const MODE_LABEL: Record<string, string> = {
  parallel_batch: '并行',
  debate: '公平辩论',
  single: '单智能体',
}

const stage = computed(() => props.spec.stages.find((s) => s.id === props.selection?.stageId))
const nodeSlug = computed(() => props.selection?.slug || '')
const nodeDef = computed(() => props.spec.nodes.find((n) => n.slug === nodeSlug.value))
const agentReportKeys = computed(
  () => props.agents.find((a) => a.slug === nodeSlug.value)?.report_keys || [],
)

const panelTarget = computed(() => {
  if (!props.selection || !stage.value) return null
  if (props.selection.type === 'band') {
    return { kind: 'band' as const, title: `组 · ${stage.value.id}` }
  }
  const meta = props.agents.find((a) => a.slug === props.selection?.slug)
  return {
    kind: 'node' as const,
    title: nodeDef.value?.node_name || meta?.name || nodeSlug.value,
  }
})

// 实例区可编辑输入：single 节点（stage.inputs）。辩论成员由组输入统一注入
// （组面板「组输入」可编辑）；并行组成员为纯生产者（NodeRef.inputs 编译期
// 被丢弃，执行期不消费）不提供编辑，避免「编辑了但无效」的假口子
const editableRef = computed(() => {
  const st = stage.value
  if (!st || props.selection?.type !== 'node') return null
  return st.mode === 'single' ? { kind: 'stage' as const } : null
})

const inputsEditable = computed(() => editableRef.value !== null)

// 输入不可编辑的原因（按模式区分，指引用户到正确的编辑位置）
const inputsMutedReason = computed(() => {
  const st = stage.value
  if (!st || props.selection?.type !== 'node') return ''
  if (st.mode === 'debate') return '辩论组成员由组输入统一注入；选中组可在「组输入」中编辑连线'
  if (st.mode === 'parallel_batch') {
    return st.pool
      ? '自动纳入的分析师成员（pool），纯生产者——仅产出报告供下游引用'
      : '并行组成员是纯生产者，不消费上游输入；连线请连到辩论组或单智能体组成员'
  }
  return ''
})

const inputsModel = computed<Record<string, InputBinding>>(() => {
  const st = stage.value
  if (!st || props.selection?.type !== 'node' || st.mode !== 'single') return {}
  return st.inputs || {}
})

function onInputsUpdate(val: Record<string, InputBinding>) {
  const st = stage.value
  if (!st || st.mode !== 'single') return
  st.inputs = { ...val }
  emit('change')
}

// 上游候选键（建议列表）：上游组成员报告键 + 辩论组输出（裁决字段 / state）
const upstreamKeys = computed<string[]>(() => {
  if (!stage.value) return []
  const keys: string[] = []
  for (const st of props.spec.stages) {
    if (st.id === stage.value!.id) break
    if (st.mode === 'debate') {
      const judgeDef = props.spec.nodes.find((n) => n.slug === st.judge)
      keys.push(...(judgeDef?.report_keys || []))
      const stateKey = effectiveStateKey(st)
      keys.push(`${stateKey}.judge_decision`, stateKey)
    } else {
      const members = st.mode === 'parallel_batch' && st.pool
        ? props.agents.filter((a) => a.phase === 1).map((a) => a.slug)
        : st.mode === 'single' && st.node
          ? [st.node]
          : (st.nodes || []).map((n) => n.ref)
      for (const slug of members) {
        keys.push(...nodeOutPorts(props.spec, slug, props.agents).map((p) => p.key))
      }
    }
  }
  keys.push('all_upstream')
  return [...new Set(keys)]
})

// 可移除：显式 batch 成员 / 辩论 side 与裁决 / single 成员（裁决与单成员移除后组变草稿，
// 确认弹窗会警示；pool 动态成员不可删）
const removable = computed(() => {
  const st = stage.value
  if (!st || props.selection?.type !== 'node') return false
  if (st.mode === 'parallel_batch') {
    if (st.pool) return false
    return (st.nodes || []).some((n) => n.ref === nodeSlug.value)
  }
  if (st.mode === 'debate') {
    return (st.sides || []).includes(nodeSlug.value) || st.judge === nodeSlug.value
  }
  return st.mode === 'single' && st.node === nodeSlug.value
})

async function removeFromWorkflow() {
  const st = stage.value
  if (!st || !nodeSlug.value) return
  const changed = await removeSelectionInteractive(props.spec, props.agents, [
    { type: 'node', stageId: st.id, slug: nodeSlug.value },
  ])
  if (changed) {
    emit('change')
    emit('close')
  }
}

// ── 终点开关（terminal:true = 最终决策写入者；validator 要求至少一个）────────

const isTerminalNode = computed(() => nodeDef.value?.terminal === true)
const canBeTerminal = computed(() => ['judge', 'terminal'].includes(nodeDef.value?.type || ''))

function onTerminalSwitch(on: boolean) {
  const def = nodeDef.value
  if (!def || props.readonly) return
  if (on) {
    // 单一写入者语义：开启即转移（清掉其它节点的 terminal 标记）
    for (const n of props.spec.nodes) {
      if (n.slug !== def.slug && n.terminal) n.terminal = false
    }
    def.terminal = true
  } else {
    def.terminal = false
    if (!hasActiveTerminal(props.spec)) {
      ElMessage.warning('当前没有终点节点（🏁）——保存校验将拒绝，请至少保留一个')
    }
  }
  emit('change')
}

// ── 组：执行顺序 / 删除 ────────────────────────────────────────────────────

const stageIndex = computed(() => props.spec.stages.findIndex((s) => s.id === stage.value?.id))
const stageTotal = computed(() => props.spec.stages.length)

async function moveStage(delta: -1 | 1) {
  const from = stageIndex.value
  if (from < 0 || props.readonly) return
  const changed = await reorderStageInteractive(props.spec, props.agents, from, from + delta)
  if (changed) emit('change')
}

async function removeGroup() {
  if (!stage.value || props.readonly) return
  const changed = await removeSelectionInteractive(props.spec, props.agents, [
    { type: 'band', stageId: stage.value.id },
  ])
  if (changed) {
    emit('change')
    emit('close')
  }
}

function setStage(update: Partial<{ optional: boolean; rounds: number; concurrency: number; state_key: string; report_view: string }>) {
  if (!stage.value || props.readonly) return
  // state_key 改名：先迁移全 spec 的绑定引用（旧键由当前值推导），再写入新值——存量连线跟随不断线
  if (typeof update.state_key === 'string' && update.state_key.trim() !== (stage.value.state_key || '')) {
    migrateStateKeyRefs(props.spec, stage.value.id, update.state_key)
  }
  const next: typeof update = { ...update }
  if (typeof next.state_key === 'string') next.state_key = next.state_key.trim() || undefined
  Object.assign(stage.value, next)
  // 持终点节点的组标记可选：跳过该组的任务将缺少最终决策字段（只警示不禁止）
  if (update.optional === true) {
    const st = stage.value
    const hasTerminal = stageMemberSlugs(st).some(
      (slug) => props.spec.nodes.find((n) => n.slug === slug)?.terminal === true,
    )
    if (hasTerminal) {
      ElMessage.warning('该组持有终点节点（最终决策写入者）：标记可选后，跳过该组的任务将缺少最终决策字段')
    }
  }
  emit('change')
}
</script>

<style lang="scss" scoped>
.ppanel {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 380px;
  max-height: calc(100% - 24px);
  overflow-y: auto;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
  padding: 12px 14px;
  z-index: 10;
}

.ppanel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.ppanel-title {
  font-weight: 600;
  font-size: 14px;
}

.ppanel-section {
  border-top: 1px dashed var(--el-border-color-lighter);
  padding-top: 10px;
  margin-top: 10px;

  &:first-of-type {
    border-top: none;
    margin-top: 0;
    padding-top: 0;
  }
}

.ppanel-section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
  margin-bottom: 8px;
}

.ppanel-field-label {
  font-size: 12px;
  margin-bottom: 6px;
}

.ppanel-muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.6;
}

.ppanel-remove {
  margin-top: 10px;
}

.ppanel-order {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}

.ppanel-terminal-label {
  margin-top: 12px;
}

.ppanel-remove-hint {
  margin-top: 10px;
}

.ppanel-optional-hint {
  margin: -6px 0 6px;
}

.ppanel-link {
  display: inline-block;
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-color-primary);
  text-decoration: none;
}

.ppanel-slide-enter-active,
.ppanel-slide-leave-active {
  transition: transform 0.18s ease, opacity 0.18s ease;
}

.ppanel-slide-enter-from,
.ppanel-slide-leave-to {
  transform: translateX(16px);
  opacity: 0;
}
</style>
