<template>
  <div class="editor-page">
    <!-- 顶栏 -->
    <div class="page-header">
      <div class="page-title">
        <el-button size="small" text @click="goBack">
          <el-icon><ArrowLeft /></el-icon>&nbsp;返回
        </el-button>
        <h2 class="title">{{ spec?.name || slug }}</h2>
        <el-tag v-if="isBuiltin" size="small" type="info" effect="plain">内置 · 只读</el-tag>
        <span class="slug-hint">{{ slug }}</span>
      </div>
      <div class="page-actions">
        <el-radio-group v-model="viewMode" size="small" class="view-toggle">
          <el-radio-button value="form">表单</el-radio-button>
          <el-radio-button value="canvas">画布</el-radio-button>
        </el-radio-group>
        <el-button size="small" :loading="loading" @click="fetchDetail">
          <el-icon><Refresh /></el-icon>&nbsp;刷新
        </el-button>
        <el-button v-if="isBuiltin" size="small" type="primary" :loading="copying" @click="copyBuiltin">
          复制为自定义副本
        </el-button>
        <template v-else>
          <el-button size="small" :loading="validating" @click="validateSpec">校验</el-button>
          <el-button size="small" type="primary" :loading="saving" :disabled="!dirty" @click="save">
            保存
          </el-button>
        </template>
      </div>
    </div>

    <!-- 内置只读横幅 -->
    <el-alert
      v-if="isBuiltin"
      type="info"
      :closable="false"
      show-icon
      class="page-alert"
      title="内置工作流（只读）— 复制为自定义副本后可编辑"
    />

    <!-- 校验错误面板 -->
    <el-alert
      v-if="validationErrors.length"
      type="error"
      :closable="false"
      show-icon
      class="page-alert"
      :title="`校验未通过（${validationErrors.length} 条）`"
    >
      <div v-for="err in validationErrors" :key="err" class="err-line">{{ err }}</div>
    </el-alert>

    <div v-loading="loading" class="editor-body">
      <el-empty v-if="!loading && !spec" description="工作流不存在或已删除" />

      <template v-if="spec">
        <!-- 画布视图（§5.3）：连线 = inputs 声明的图形化编辑，与表单编辑同一份 spec；
             侧边智能体库（行业标准交互）：拖到组 / 空白处建组，模块拖出空区域 -->
        <el-card v-if="viewMode === 'canvas'" shadow="never" class="edit-card canvas-card">
          <template #header>
            <div class="card-head-row">
              <span class="card-title">自由画布 · 连线即输入声明 · 按序号执行</span>
              <span class="canvas-head-hints">
                <el-tag v-if="!readonly && selectedStageId" size="small" type="success" effect="plain">
                  已选段：{{ selectedStageId }}
                </el-tag>
                <span class="canvas-loading-hint">{{ agentsMeta.length ? '' : '智能体库加载中…' }}</span>
              </span>
            </div>
          </template>
          <div class="canvas-layout">
            <AgentPalette
              v-if="!readonly"
              class="canvas-palette"
              :agents="agentsMeta"
              :used-slugs="usedSlugs"
              :library-slugs="librarySlugs"
              @select="onPaletteSelect"
              @module-select="onPaletteModuleSelect"
            />
            <CanvasStage
              class="canvas-flow"
              :spec="spec"
              :agents="agentsMeta"
              :readonly="readonly"
              @change="markDirty"
              @stage-select="onStageSelect"
            />
          </div>
        </el-card>

        <template v-else>
        <!-- 基本信息 -->
        <el-card shadow="never" class="edit-card">
          <template #header><span class="card-title">基本信息</span></template>
          <el-form label-width="100px" label-position="left" :disabled="readonly">
            <el-row :gutter="16">
              <el-col :span="8">
                <el-form-item label="名称" required>
                  <el-input v-model="spec.name" placeholder="显示名称" @input="markDirty" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="描述">
                  <el-input v-model="spec.description" placeholder="工作流用途说明" @input="markDirty" />
                </el-form-item>
              </el-col>
              <el-col :span="4">
                <el-form-item label="启用">
                  <el-switch v-model="spec.enabled" @change="markDirty" />
                </el-form-item>
              </el-col>
            </el-row>
          </el-form>
        </el-card>

        <!-- 阶段序列 -->
        <el-card shadow="never" class="edit-card">
          <template #header>
            <div class="card-head-row">
              <span class="card-title">组序列（按序号执行）</span>
              <el-dropdown v-if="!readonly" @command="addStage">
                <el-button size="small" text type="primary"> + 添加组 </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="parallel_batch">并行组（成员同时执行）</el-dropdown-item>
                    <el-dropdown-item command="debate">公平辩论组（轮流辩论 + 裁决）</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </template>
          <el-empty v-if="!spec.stages.length" description="暂无阶段" :image-size="60" />
          <div
            v-for="(stage, idx) in spec.stages"
            :key="idx"
            class="stage-block"
            :class="{ 'is-optional': stage.optional }"
          >
            <div class="stage-head">
              <span class="stage-order">{{ idx + 1 }}</span>
              <el-input v-model="stage.id" class="stage-id" placeholder="stage id" :disabled="readonly" @input="markDirty" />
              <el-tag size="small" effect="plain">{{ MODE_LABEL[stage.mode] || stage.mode }}</el-tag>
              <el-checkbox
                v-model="stage.optional"
                :disabled="readonly"
                title="勾选后，发起分析时可在分析页按任务跳过该组（默认不跳过）"
                @change="markDirty"
              >
                可关闭
              </el-checkbox>
              <div class="stage-ops">
                <el-button size="small" text :disabled="idx === 0 || readonly" @click="moveStage(idx, -1)">↑</el-button>
                <el-button
                  size="small"
                  text
                  :disabled="idx === spec.stages.length - 1 || readonly"
                  @click="moveStage(idx, 1)"
                >
                  ↓
                </el-button>
                <el-button size="small" text type="danger" :disabled="readonly" @click="removeStage(idx)">
                  删除
                </el-button>
              </div>
            </div>

            <el-form label-width="90px" label-position="left" class="stage-form" :disabled="readonly">
              <!-- 批阶段 -->
              <template v-if="stage.mode === 'parallel_batch'">
                <el-form-item label="节点来源">
                  <el-radio-group
                    :model-value="stage.pool ? 'pool' : 'nodes'"
                    @update:model-value="(v: string | number | boolean | undefined) => switchBatchSource(stage, String(v))"
                  >
                    <el-radio value="pool">自动（全部分析师自动加入）</el-radio>
                    <el-radio value="nodes">指定成员</el-radio>
                  </el-radio-group>
                </el-form-item>
                <el-form-item v-if="!stage.pool" label="节点列表">
                  <el-select
                    :model-value="(stage.nodes || []).map((n) => n.ref)"
                    multiple
                    filterable
                    allow-create
                    placeholder="选择成员（智能体库 + 节点库；分析师自动按裸引用处理）"
                    style="width: 100%"
                    @update:model-value="(v: string[]) => setBatchNodes(stage, v)"
                  >
                    <el-option v-for="opt in batchCandidates" :key="opt" :value="opt" :label="opt" />
                  </el-select>
                </el-form-item>
                <el-form-item label="并发数">
                  <el-input-number v-model="stage.concurrency" :min="1" :max="20" @change="markDirty" />
                </el-form-item>
              </template>

              <!-- 辩论阶段 -->
              <template v-else-if="stage.mode === 'debate'">
                <el-row :gutter="16">
                  <el-col :span="12">
                    <el-form-item label="辩手" required>
                      <el-select
                        :model-value="stage.sides || []"
                        multiple
                        filterable
                        placeholder="至少 2 方（任意类型智能体均可）"
                        style="width: 100%"
                        @update:model-value="(v: string[]) => setDebateSides(stage, v)"
                      >
                        <el-option v-for="opt in sideCandidates" :key="opt" :value="opt" :label="opt" />
                      </el-select>
                    </el-form-item>
                  </el-col>
                  <el-col :span="12">
                    <el-form-item label="judge" required>
                      <el-select
                        :model-value="stage.judge || ''"
                        filterable
                        placeholder="judge / terminal 节点（terminal 随裁决转移）"
                        style="width: 100%"
                        @update:model-value="(v: string) => setDebateJudge(stage, v)"
                      >
                        <el-option v-for="opt in judgeCandidates" :key="opt" :value="opt" :label="opt" />
                      </el-select>
                    </el-form-item>
                  </el-col>
                </el-row>
                <el-row :gutter="16">
                  <el-col :span="8">
                    <el-form-item label="附加轮数">
                      <el-input-number v-model="stage.rounds" :min="0" :max="10" @change="markDirty" />
                      <span class="form-hint">总发言轮 = rounds + 1</span>
                    </el-form-item>
                  </el-col>
                  <el-col :span="8">
                    <el-form-item label="状态键">
                      <el-input
                        :model-value="stage.state_key"
                        placeholder="risk_debate_state"
                        @update:model-value="(v: string) => onStateKeyInput(stage, v)"
                      />
                    </el-form-item>
                  </el-col>
                  <el-col :span="8">
                    <el-form-item label="报告视图">
                      <el-select v-model="stage.report_view" @change="markDirty">
                        <el-option value="investment" label="investment（多空投资）" />
                        <el-option value="risk" label="risk（风险评估）" />
                        <el-option value="generic" label="generic（通用 N 方）" />
                      </el-select>
                    </el-form-item>
                  </el-col>
                </el-row>
                <el-form-item label="组输入">
                  <BindingEditor
                    :model-value="stage.inputs || {}"
                    :upstream-keys="upstreamKeysBefore(idx)"
                    :disabled="readonly"
                    @update:model-value="(v) => setStageInputs(stage, v)"
                  />
                </el-form-item>
              </template>

              <!-- 单智能体阶段 -->
              <template v-else>
                <el-form-item label="节点" required>
                  <el-select
                    :model-value="stage.node || ''"
                    filterable
                    placeholder="节点库内节点 / 库内任意智能体"
                    style="width: 100%"
                    @update:model-value="(v: string) => setSingleNode(stage, v)"
                  >
                    <el-option v-for="opt in singleCandidates" :key="opt" :value="opt" :label="opt" />
                  </el-select>
                </el-form-item>
                <el-form-item label="输入连线">
                  <BindingEditor
                    :model-value="stage.inputs || {}"
                    :upstream-keys="upstreamKeysBefore(idx)"
                    :disabled="readonly"
                    @update:model-value="(v) => setStageInputs(stage, v)"
                  />
                </el-form-item>
              </template>
            </el-form>
          </div>
        </el-card>

        <!-- 节点库（本工作流的执行属性） -->
        <el-card shadow="never" class="edit-card">
          <template #header>
            <div class="card-head-row">
              <span class="card-title">节点库（本工作流执行属性；提示词在智能体管理维护）</span>
              <el-button v-if="!readonly" size="small" text type="primary" @click="addNodeVisible = true">
                + 添加节点
              </el-button>
            </div>
          </template>
          <el-empty v-if="!spec.nodes.length" description="暂无节点" :image-size="60" />
          <div v-for="node in spec.nodes" :key="node.slug" class="node-block">
            <div class="node-head">
              <el-input v-model="node.slug" class="node-slug" placeholder="slug" :disabled="readonly" @input="markDirty" />
              <el-tag size="small" effect="plain">{{ node.type }}</el-tag>
              <el-checkbox
                :model-value="node.terminal === true"
                :disabled="readonly"
                @update:model-value="(v: string | number | boolean) => { node.terminal = v === true; markDirty() }"
              >
                terminal
              </el-checkbox>
              <div class="node-ops">
                <el-button size="small" text type="danger" :disabled="readonly" @click="removeNode(node)">
                  删除
                </el-button>
              </div>
            </div>
            <el-form label-width="90px" label-position="left" class="node-form" :disabled="readonly">
              <el-row :gutter="16">
                <el-col :span="6">
                  <el-form-item label="类型">
                    <el-select v-model="node.type" @change="onNodeTypeChange(node)">
                      <el-option v-for="t in NODE_TYPES" :key="t" :value="t" :label="t" />
                    </el-select>
                  </el-form-item>
                </el-col>
                <el-col :span="6">
                  <el-form-item label="记忆槽">
                    <el-select v-model="node.memory" clearable placeholder="无" @change="markDirty">
                      <el-option v-for="m in MEMORY_SLOTS" :key="m" :value="m" :label="m" />
                    </el-select>
                  </el-form-item>
                </el-col>
                <el-col :span="6">
                  <el-form-item label="node_name">
                    <el-input v-model="node.node_name" placeholder="英文执行节点名" @input="markDirty" />
                  </el-form-item>
                </el-col>
                <el-col :span="6">
                  <el-form-item label="event_key">
                    <el-input v-model="node.event_key" placeholder="事件流 agent_key" @input="markDirty" />
                  </el-form-item>
                </el-col>
              </el-row>
              <el-form-item label="报告键">
                <el-input
                  :model-value="(node.report_keys || []).join(', ')"
                  placeholder="逗号分隔，如 trader_investment_plan"
                  @update:model-value="(v: string) => { node.report_keys = splitKeys(v); markDirty() }"
                />
              </el-form-item>
            </el-form>
          </div>
        </el-card>

        <!-- 终端契约 -->
        <el-card shadow="never" class="edit-card">
          <template #header><span class="card-title">终端契约</span></template>
          <el-form label-width="110px" label-position="left" :disabled="readonly">
            <el-row :gutter="16">
              <el-col :span="8">
                <el-form-item label="决策字段" required>
                  <el-input v-model="spec.terminal.decision_field" placeholder="final_trade_decision" @input="markDirty" />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="总结节点" required>
                  <el-select v-model="spec.terminal.summary_node" filterable @change="markDirty">
                    <el-option v-for="opt in allNodeSlugs" :key="opt" :value="opt" :label="opt" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="信号回退链">
                  <el-input
                    :model-value="(spec.terminal.signal_fallback || []).join(', ')"
                    placeholder="逗号分隔（点路径可用）"
                    @update:model-value="setSignalFallback"
                  />
                </el-form-item>
              </el-col>
            </el-row>
          </el-form>
        </el-card>

        <!-- 从智能体库添加节点（派生 NodeSpec 预填节点卡） -->
        <el-dialog
          v-model="addNodeVisible"
          title="从智能体库添加节点（自动派生类型 / 执行锚 / 报告键）"
          width="560px"
          append-to-body
        >
          <AgentPalette
            :agents="agentsMeta"
            :used-slugs="usedSlugs"
            :library-slugs="librarySlugs"
            :draggable="false"
            @select="onAddNodeFromLibrary"
          />
          <template #footer>
            <el-button @click="addNodeVisible = false">关闭</el-button>
            <el-button type="primary" plain @click="addNodeBlank">手动新建空白节点</el-button>
          </template>
        </el-dialog>
        </template>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Refresh } from '@element-plus/icons-vue'
import { workflowApi, agentApi, type InputBinding, type NodeSpecDto, type StageSpecDto, type WorkflowSpecDto } from '@/api/workflows'
import BindingEditor from '@/components/Workflow/BindingEditor.vue'
import AgentPalette from '@/components/Workflow/Canvas/AgentPalette.vue'
import CanvasStage from '@/components/Workflow/Canvas/CanvasStage.vue'
import { agentMetaFromList, stageMemberSlugs, type AgentMeta } from '@/components/Workflow/Canvas/edgeRules'
import { addAgentToStage, removeSelectionInteractive, reorderStageInteractive } from '@/components/Workflow/Canvas/stageAddInteraction'
import {
  applyReplaceJudge,
  applyReplaceSingle,
  blankGroupOf,
  ensureNodeSpec,
  GROUP_ADD_HINTS,
  type GroupModuleMode,
  migrateStateKeyRefs,
  transferTerminal,
} from '@/components/Workflow/Canvas/specMutation'

const MODE_LABEL: Record<string, string> = {
  parallel_batch: '并行',
  debate: '公平辩论',
  single: '单智能体',
}
const NODE_TYPES = ['analyst', 'debater', 'judge', 'trader', 'summarizer', 'terminal']
const MEMORY_SLOTS = ['bull', 'bear', 'invest_judge', 'trader', 'risk_manager']

const route = useRoute()
const router = useRouter()
const slug = computed(() => String(route.params.slug || ''))

const loading = ref(false)
const saving = ref(false)
const validating = ref(false)
const copying = ref(false)
const spec = ref<WorkflowSpecDto | null>(null)
const isBuiltin = ref(false)
const dirty = ref(false)
const validationErrors = ref<string[]>([])

// 双视图（P6）：表单 / 画布编辑同一份 spec draft；画布优先（默认入口）
const viewMode = ref<'form' | 'canvas'>('canvas')
const agentsMeta = ref<AgentMeta[]>([])
/** 画布中当前选中的泳道段（palette 点击添加的目标） */
const selectedStageId = ref<string | null>(null)

const fetchAgentsMeta = async () => {
  try {
    const res = await agentApi.list()
    agentsMeta.value = agentMetaFromList(res.data.agents || [])
  } catch (error) {
    console.error('智能体库加载失败（画布端口将降级）', error)
    agentsMeta.value = []
  }
}

const readonly = computed(() => isBuiltin.value)

// ── 画布 palette 添加（点击流；拖放落在 CanvasStage 内部处理）──
const onStageSelect = (stageId: string | null) => {
  selectedStageId.value = stageId
}

const onPaletteSelect = async (agent: AgentMeta) => {
  if (!spec.value || readonly.value) return
  if (!selectedStageId.value) {
    ElMessage.info('先点击画布中的组选中目标，或直接把智能体拖到画布')
    return
  }
  const changed = await addAgentToStage(spec.value, selectedStageId.value, agent)
  if (changed) markDirty()
}

/** palette 点击策略模块：末尾建空组（成员由用户拖入） */
const onPaletteModuleSelect = (mode: GroupModuleMode) => {
  if (!spec.value || readonly.value) return
  spec.value.stages.push(blankGroupOf(spec.value, mode))
  ElMessage.success(GROUP_ADD_HINTS[mode])
  markDirty()
}

const allNodeSlugs = computed(() => (spec.value?.nodes || []).map((n) => n.slug))
const nodesByKind = computed(() => {
  const grouped: Record<string, string[]> = { debater: [], judge: [], terminal: [] }
  for (const n of spec.value?.nodes || []) {
    const nodeType = n.type
    if (nodeType && nodeType in grouped) grouped[nodeType].push(n.slug)
  }
  return grouped
})

/**
 * 画布可见成员（palette「已在流」标记）：各阶段显式成员并集。
 * 只认 spec 里写定的引用——spec.nodes 孤留（成员已移除但定义还在节点库）不算在流，
 * pool 组动态纳入的分析师也不算（拖入会触发「切换为指定成员」确认弹窗，不静默重复）。
 */
const usedSlugs = computed(() => {
  const s = spec.value
  if (!s) return []
  const used = new Set<string>()
  for (const stage of s.stages) for (const slug of stageMemberSlugs(stage)) used.add(slug)
  return [...used]
})

/** 已入节点库但不在画布上的 slug（palette「已入库」灰标，区别于「已在流」；仍可拖入） */
const librarySlugs = computed(() => {
  const s = spec.value
  if (!s) return []
  const used = new Set(usedSlugs.value)
  return s.nodes.map((n) => n.slug).filter((slug) => !used.has(slug))
})

/** 表单选择器候选 = 节点库 ∪ 智能体库（选库内项时自动派生 NodeSpec；与画布矩阵一致） */
const batchCandidates = computed(() => {
  const s = new Set(allNodeSlugs.value)
  for (const a of agentsMeta.value) s.add(a.slug)
  return [...s]
})
/** 辩手候选：任意类型（validator 对 sides 无 type 约束）；裁决类型走裁决位不进辩手列表 */
const sideCandidates = computed(() => {
  const judgeish = new Set([...nodesByKind.value.judge, ...nodesByKind.value.terminal])
  const s = new Set(allNodeSlugs.value)
  for (const a of agentsMeta.value) if (a.kind !== 'judge' && a.kind !== 'terminal') s.add(a.slug)
  return [...s].filter((slug) => !judgeish.has(slug))
})
const judgeCandidates = computed(() => {
  const s = new Set([...nodesByKind.value.judge, ...nodesByKind.value.terminal])
  for (const a of agentsMeta.value) if (a.kind === 'judge' || a.kind === 'terminal') s.add(a.slug)
  return [...s]
})
const singleCandidates = computed(() => {
  const s = new Set(allNodeSlugs.value)
  for (const a of agentsMeta.value) s.add(a.slug)
  return [...s]
})

/** 拓扑序在 stage[idx] 之前的阶段产出键（连线候选） */
const upstreamKeysBefore = (idx: number): string[] => {
  if (!spec.value) return []
  const keys = new Set<string>()
  for (const stage of spec.value.stages.slice(0, idx)) {
    if (stage.mode === 'parallel_batch') {
      keys.add('all_upstream')
      if (stage.pool) keys.add('phase1 分析师报告（market_report 等）')
      for (const ref of stage.nodes || []) keys.add(`${ref.ref} 的报告键`)
    } else if (stage.mode === 'debate') {
      if (stage.state_key) keys.add(stage.state_key)
      for (const s of stage.sides || []) keys.add(`${s} 的报告键`)
    } else if (stage.node) {
      const node = spec.value.nodes.find((n) => n.slug === stage.node)
      for (const rk of node?.report_keys || []) keys.add(rk)
    }
  }
  return [...keys]
}

const markDirty = () => {
  dirty.value = true
}

/**
 * 表单模式 state_key 编辑：改名时先迁移全 spec 的绑定引用（旧键由当前值推导），
 * 存量连线跟随不断线；清空 = 回落到 stage id 兜底键（与画布解析同口径）。
 */
const onStateKeyInput = (stage: StageSpecDto, v: string) => {
  if (!spec.value) return
  if (v.trim() !== (stage.state_key || '')) migrateStateKeyRefs(spec.value, stage.id, v)
  stage.state_key = v.trim() || undefined
  markDirty()
}

const splitKeys = (v: string): string[] =>
  v.split(',').map((s) => s.trim()).filter(Boolean)

const setSignalFallback = (v: string) => {
  if (!spec.value) return
  spec.value.terminal.signal_fallback = splitKeys(v)
  markDirty()
}

const goBack = () => router.push('/settings/workflows')

const fetchDetail = async () => {
  loading.value = true
  validationErrors.value = []
  try {
    const res = await workflowApi.get(slug.value)
    spec.value = res.data.workflow
    isBuiltin.value = res.data.builtin
    dirty.value = false
  } catch (error) {
    console.error('获取工作流失败', error)
    spec.value = null
  } finally {
    loading.value = false
  }
}

// ── 阶段操作 ──
/** 表单模式「+ 添加组」：空组只有并行/辩论两种（单个智能体在画布直接拖空白建组） */
const addStage = (mode: GroupModuleMode) => {
  if (!spec.value) return
  spec.value.stages.push(blankGroupOf(spec.value, mode))
  ElMessage.success(GROUP_ADD_HINTS[mode])
  markDirty()
}

/** 删除组：统一走 removeSelectionInteractive（连带摘除下游连线声明 + 影响面警示） */
const removeStage = async (idx: number) => {
  if (!spec.value) return
  const stageId = spec.value.stages[idx]?.id
  if (!stageId) return
  const changed = await removeSelectionInteractive(spec.value, agentsMeta.value, [
    { type: 'band', stageId },
  ])
  if (changed) markDirty()
}

/** 组顺序调整：统一走 reorderStageInteractive（预检向前引用失效，确认后自动摘除连线） */
const moveStage = async (idx: number, delta: number) => {
  if (!spec.value) return
  const changed = await reorderStageInteractive(spec.value, agentsMeta.value, idx, idx + delta)
  if (changed) markDirty()
}

const switchBatchSource = (stage: StageSpecDto, source: string) => {
  if (source === 'pool') {
    stage.pool = 'phase1_analysts'
    stage.nodes = []
  } else {
    stage.pool = undefined
    stage.nodes = stage.nodes?.length ? stage.nodes : []
  }
  markDirty()
}

/**
 * 批阶段成员 diff 更新：新增非分析师成员自动派生 NodeSpec（analyst 裸引用
 * 即可命中 phase1 池）；保留原 NodeRef 的 inputs 声明。
 */
const setBatchNodes = (stage: StageSpecDto, refs: string[]) => {
  if (!spec.value) return
  const prev = new Set((stage.nodes || []).map((n) => n.ref))
  for (const ref of refs) {
    if (prev.has(ref)) continue
    const agent = agentsMeta.value.find((a) => a.slug === ref)
    if (agent && agent.kind !== 'analyst') ensureNodeSpec(spec.value, agent)
  }
  stage.nodes = refs.map((ref) => (stage.nodes || []).find((n) => n.ref === ref) || { ref })
  markDirty()
}

/** 辩手多选：任意类型可当辩手（validator 仅要求命中 nodes 库）；裁决不兼任由选择器候选保证 */
const setDebateSides = (stage: StageSpecDto, sides: string[]) => {
  if (!spec.value) return
  const existing = new Set(stage.sides || [])
  for (const s of sides) {
    if (existing.has(s)) continue
    const agent = agentsMeta.value.find((a) => a.slug === s)
    if (agent) ensureNodeSpec(spec.value, agent)
  }
  stage.sides = sides
  markDirty()
}

/** 更换裁决：库内项派生 NodeSpec；terminal 标记随旧裁决转移（decision 写入职责） */
const setDebateJudge = (stage: StageSpecDto, judge: string) => {
  if (!spec.value || stage.judge === judge) return
  const agent = agentsMeta.value.find((a) => a.slug === judge)
  if (agent) {
    applyReplaceJudge(spec.value, stage.id, agent)
  } else {
    transferTerminal(spec.value, stage.judge || '', judge)
    stage.judge = judge
  }
  markDirty()
}

/** 单智能体组成员：任意类型可当唯一成员（分析师会退化为单轮产出） */
const setSingleNode = (stage: StageSpecDto, node: string) => {
  if (!spec.value || stage.node === node) return
  const agent = agentsMeta.value.find((a) => a.slug === node)
  if (agent) {
    applyReplaceSingle(spec.value, stage.id, agent)
  } else {
    stage.node = node
  }
  markDirty()
}

const setStageInputs = (stage: StageSpecDto, inputs: Record<string, InputBinding>) => {
  stage.inputs = inputs
  markDirty()
}

// ── 节点操作 ──
/** 从智能体库派生节点（执行属性按 registry 权威锚预填；重复选择幂等） */
const addNodeVisible = ref(false)
const onAddNodeFromLibrary = (agent: AgentMeta) => {
  if (!spec.value) return
  if (ensureNodeSpec(spec.value, agent)) {
    ElMessage.success(`已派生节点 ${agent.slug}（type=${agent.kind}）`)
    markDirty()
  } else {
    ElMessage.info(`${agent.slug} 已在节点库`)
  }
}

/** 手动新建空白节点（无库对应的自定义执行节点） */
const addNodeBlank = () => {
  if (!spec.value) return
  let i = spec.value.nodes.length + 1
  while (spec.value.nodes.some((n) => n.slug === `my-node-${i}`)) i++
  spec.value.nodes.push({
    slug: `my-node-${i}`,
    type: 'debater',
    execution: 'single_turn',
    memory: null,
    node_name: '',
    event_key: '',
    report_keys: [],
    terminal: false,
  })
  markDirty()
  addNodeVisible.value = false
}

const removeNode = async (node: NodeSpecDto) => {
  if (!spec.value) return
  try {
    await ElMessageBox.confirm(
      `确定删除节点「${node.slug}」吗？引用它的阶段会因 ref 未命中而校验失败。`,
      '删除确认',
      { type: 'warning' },
    )
    spec.value.nodes = spec.value.nodes.filter((n) => n.slug !== node.slug)
    markDirty()
  } catch (error) {
    if (error !== 'cancel') console.error(error)
  }
}

const onNodeTypeChange = (node: NodeSpecDto) => {
  node.execution = node.type === 'analyst' ? 'tool_loop' : 'single_turn'
  markDirty()
}

// ── 校验与保存 ──
const validateSpec = async (): Promise<boolean> => {
  if (!spec.value) return false
  validating.value = true
  try {
    const res = await workflowApi.validate(spec.value)
    validationErrors.value = res.data?.errors || []
    if (res.data?.valid) {
      ElMessage.success('校验通过')
      return true
    }
    ElMessage.warning(`校验未通过：${validationErrors.value.length} 条错误`)
    return false
  } catch (error) {
    console.error('校验请求失败', error)
    return false
  } finally {
    validating.value = false
  }
}

const save = async () => {
  if (!spec.value) return
  const valid = await validateSpec()
  if (!valid) return
  saving.value = true
  try {
    await workflowApi.update(slug.value, spec.value)
    ElMessage.success('工作流已保存')
    dirty.value = false
  } catch (error) {
    console.error('保存工作流失败', error)
  } finally {
    saving.value = false
  }
}

const copyBuiltin = async () => {
  if (!spec.value) return
  const newSlug = `${slug.value}-copy`
  try {
    await ElMessageBox.prompt('为新副本指定 slug', '复制工作流', {
      inputValue: newSlug,
      inputPattern: /^[a-z0-9][a-z0-9-_]*$/,
      inputErrorMessage: 'slug 仅限小写字母、数字、-、_',
      confirmButtonText: '复制',
      cancelButtonText: '取消',
    }).then(async ({ value }) => {
      copying.value = true
      try {
        await workflowApi.create({
          ...spec.value!,
          slug: value,
          name: `${spec.value!.name}（副本）`,
          builtin: false,
        })
        ElMessage.success('副本已创建')
        router.replace(`/settings/workflows/${value}/edit`)
      } finally {
        copying.value = false
      }
    })
  } catch (error) {
    if (error !== 'cancel') console.error('复制工作流失败', error)
  }
}

// 离开保护：未保存变更确认（路由内）；刷新/关闭由 beforeunload 承担
onBeforeRouteLeave(async () => {
  if (!dirty.value) return true
  try {
    await ElMessageBox.confirm('存在未保存的修改，离开将丢失。确定离开吗？', '未保存的修改', {
      confirmButtonText: '离开',
      cancelButtonText: '留在本页',
      type: 'warning',
    })
    return true
  } catch {
    return false
  }
})

const onBeforeUnload = (e: BeforeUnloadEvent) => {
  if (dirty.value) {
    e.preventDefault()
    e.returnValue = ''
  }
}

onMounted(() => {
  window.addEventListener('beforeunload', onBeforeUnload)
  fetchDetail()
  fetchAgentsMeta()
})

onUnmounted(() => {
  window.removeEventListener('beforeunload', onBeforeUnload)
})
</script>

<style lang="scss" scoped>
.editor-page {
  padding: 16px;
  height: 100%;
  box-sizing: border-box;
  overflow-y: auto;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.page-title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;

  .title {
    margin: 0;
    font-size: 18px;
    font-weight: 600;
  }

  .slug-hint {
    color: var(--el-text-color-secondary);
    font-size: 12px;
  }
}

.page-actions {
  display: flex;
  gap: 8px;
}

.page-alert {
  margin-top: 12px;

  .err-line {
    font-size: 12px;
    line-height: 1.8;
  }
}

.editor-body {
  margin-top: 12px;
}

.edit-card {
  margin-bottom: 12px;

  :deep(.el-card__header) {
    padding: 10px 16px;
  }
}

.card-head-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-title {
  font-size: 13px;
  font-weight: 600;
}

.stage-block {
  padding: 10px 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  margin-bottom: 10px;

  &.is-optional {
    border-style: dashed;
  }
}

.stage-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.stage-order {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background-color: var(--el-color-primary);
  color: #fff;
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stage-id {
  width: 220px;

  :deep(.el-input__inner) {
    font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
  }
}

.stage-ops,
.node-ops {
  margin-left: auto;
  display: flex;
  gap: 2px;

  .el-button {
    margin: 0;
    padding: 4px 6px;
  }
}

.stage-form,
.node-form {
  padding-left: 28px;
}

.form-hint {
  margin-left: 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

// 画布视图：侧边智能体库 + 流程画布左右布局（<1024px 隐藏 palette，仅保留画布）
.canvas-layout {
  display: flex;
  align-items: stretch;

  .canvas-palette {
    width: 240px;
    flex-shrink: 0;
  }

  .canvas-flow {
    flex: 1;
    min-width: 0;
  }
}

.canvas-head-hints {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.node-block {
  padding: 10px 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  margin-bottom: 10px;
}

.node-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.node-slug {
  width: 220px;

  :deep(.el-input__inner) {
    font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
  }
}

@media (max-width: 1024px) {
  .canvas-layout .canvas-palette {
    display: none;
  }
}

@media (max-width: 768px) {
  .stage-form,
  .node-form {
    padding-left: 0;
  }

  .stage-ops,
  .node-ops {
    margin-left: 0;
  }
}
</style>
