<template>
  <div class="canvas-stage" :class="{ readonly }" @dragover="onDragOver" @drop="onDrop">
    <VueFlow
      :nodes-connectable="!effectiveReadonly"
      :edges-updatable="false"
      :delete-key-code="null"
      :min-zoom="0.2"
      :max-zoom="1.8"
      @connect="onConnect"
      @node-drag-start="onNodeDragStart"
      @node-drag="onNodeDrag"
      @node-drag-stop="onNodeDragStop"
      @node-click="onNodeClick"
      @edge-click="onEdgeClick"
      @pane-click="onPaneClick"
    >
      <Background :gap="20" pattern-color="#c8c9cc" />
      <Controls position="bottom-left" />
      <MiniMap position="bottom-right" pannable zoomable :node-class-name="minimapClass" />

      <Panel position="top-left" class="canvas-toolbar">
        <el-button
          size="small"
          type="primary"
          plain
          :disabled="effectiveReadonly"
          @click="addStrategyGroup('parallel_batch')"
        >
          + 并行
        </el-button>
        <el-button
          size="small"
          type="primary"
          plain
          :disabled="effectiveReadonly"
          @click="addStrategyGroup('debate')"
        >
          + 公平辩论
        </el-button>
        <el-button size="small" @click="autoLayout">整理布局</el-button>
        <el-button size="small" @click="fitAll">适应视图</el-button>
        <span class="canvas-hint">左侧拖入智能体 / 模块；连线从序号小的组连向序号大的组；点选后 Delete 删除；Shift 框选</span>
      </Panel>

      <template #node-ncard="nodeProps">
        <NodeCard v-bind="nodeProps" />
      </template>
      <template #node-sband="nodeProps">
        <StageBand v-bind="nodeProps" @resize-end="onBandResizeEnd" @reorder="onBandReorder" />
      </template>
      <template #edge-binding="edgeProps">
        <BindingEdge v-bind="edgeProps" :removable="!effectiveReadonly" @remove="onEdgeRemove" />
      </template>
    </VueFlow>

    <!-- 空画布引导（pointer-events 穿透，不影响 drop） -->
    <div v-if="!spec.stages.length" class="canvas-empty-guide">
      <div class="guide-icon">🧩</div>
      <div class="guide-title">空画布</div>
      <p>从左侧拖出策略模块（并行 / 公平辩论）或直接拖入智能体自动建组；<br />
        序号 1 的组即执行起点；搭好后保留一个终点节点（🏁）才能产出交易决策</p>
    </div>

    <!-- 终点缺失提示（validator 要求 ≥1 个 terminal:true 的 judge/terminal 节点） -->
    <el-alert
      v-if="missingTerminal"
      type="warning"
      :closable="false"
      show-icon
      class="canvas-terminal-alert"
      title="没有终点节点（🏁）：拖入裁决 / 终端类型智能体并在属性面板打开「设为终点」，否则保存校验将拒绝"
    />

    <!-- 选中集悬浮操作条（键盘 Delete 的可发现入口） -->
    <div v-if="selectedCount > 0 && !effectiveReadonly" class="canvas-selection-bar">
      <span>已选 {{ selectedCount }} 项</span>
      <el-button size="small" type="danger" plain @click="deleteSelection">删除</el-button>
      <el-button size="small" text @click="clearSelection">取消</el-button>
    </div>

    <PropertyPanel
      :spec="spec"
      :selection="selection"
      :agents="agents"
      :readonly="readonly"
      @change="onChange"
      @close="selection = null"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { VueFlow, Panel, useVueFlow } from '@vue-flow/core'
import type { Node, Edge, Connection } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import NodeCard from './NodeCard.vue'
import StageBand from './StageBand.vue'
import BindingEdge from './BindingEdge.vue'
import PropertyPanel from './PropertyPanel.vue'
import { PALETTE_MIME } from './AgentPalette.vue'
import type { NodeCardData } from './NodeCard.vue'
import type { BandData } from './StageBand.vue'
import {
  ALL_UPSTREAM,
  bandNodeId,
  bandOutPorts,
  buildBindingGraph,
  canConnect,
  consumerInSlots,
  effectiveStateKey,
  memberNodeId,
  nodeOutPorts,
  parseNodeId,
  removeConnection,
  applyConnection,
  stageMemberSlugs,
  stageMembers,
  type AgentMeta,
  type DanglingBinding,
} from './edgeRules'
import { addAgentToStage, removeSelectionInteractive, reorderStageInteractive, type RemovalTarget } from './stageAddInteraction'
import {
  bandAtPoint,
  blankGroupOf,
  createStageForAgent,
  GROUP_ADD_HINTS,
  hasActiveTerminal,
  insertIndexAtPoint,
  type GroupModuleMode,
} from './specMutation'
import type { StageSpecDto, WorkflowSpecDto } from '@/api/workflows'

/**
 * 画布编辑器（§5.3）：策略组自由摆放 + 辩论封闭容器 + 连线 = inputs 声明。
 * 执行顺序 = 组序号（spec.stages 数组序，后端唯一权威），与画布位置解耦；
 * spec 为唯一数据源（父级 draft 对象），画布变更直接改 spec 后 emit change。
 */

const props = defineProps<{
  spec: WorkflowSpecDto
  /** 智能体库元数据（pool 成员枚举 + 端口派生），由父级经 agentMetaFromList 转换 */
  agents: AgentMeta[]
  readonly?: boolean
}>()

const emit = defineEmits<{
  (e: 'change'): void
  /** 点击泳道段/成员节点选中阶段、点击空白清除（palette 点击添加的目标） */
  (e: 'stage-select', stageId: string | null): void
}>()

const agents = computed(() => props.agents)

// §5.3 移动端声明：画布编辑仅桌面（≥1024px + 精确指针）；小屏只读平移缩放查看
const isDesktop = ref(typeof window !== 'undefined' && window.matchMedia('(min-width: 1024px)').matches)
const effectiveReadonly = computed(() => props.readonly || !isDesktop.value)

const {
  setNodes,
  setEdges,
  getNodes,
  getSelectedNodes,
  getSelectedEdges,
  findNode,
  fitView,
  screenToFlowCoordinate,
} = useVueFlow()

// ── 布局（位置记忆跨重建保留；组可自由摆放，首建默认垂直堆叠）──────────────

const LAYOUT = { bandWidth: 980, padTop: 104, colW: 264, rowH: 116, gapY: 70, maxCols: 3 }
const positions = ref<Record<string, { x: number; y: number }>>({})
/** 用户手动调整过的组高度（纯视觉记忆，不进 spec；取 max(自动高度, 手动高度)） */
const stageHeights = ref<Record<string, number>>({})
interface BandRect {
  stageId: string
  x: number
  y: number
  width: number
  height: number
}
const bandRects: BandRect[] = []
const edgeIndex = new Map<string, { target: string; slot: string; value: string }>()

// ── 防重叠占位（成员卡与组框都不互相压盖）──────────────────────────────────

/** 成员卡占位尺寸（NodeCard 190-240 宽，取中间近似值做碰撞检测） */
const CARD_W = 220
const CARD_H = 84

function rectsOverlap(
  a: { x: number; y: number; w: number; h: number },
  b: { x: number; y: number; w: number; h: number },
): boolean {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y
}

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), Math.max(lo, hi))

/** 组内某成员的占位矩形（无位置记忆时返回 null） */
function memberRect(stageId: string, slug: string): { x: number; y: number; w: number; h: number } | null {
  const p = positions.value[memberNodeId(stageId, slug)]
  return p ? { x: p.x, y: p.y, w: CARD_W, h: CARD_H } : null
}

/**
 * 组内找一个不与已有成员卡重叠的落位：期望位置 clamp 进组矩形（顶部避开组头），
 * 被占用则按格距右移顺延、超宽换行下移。组不存在时原样返回。
 */
function freeSpotInBand(stageId: string, want: { x: number; y: number }): { x: number; y: number } {
  const rect = bandRects.find((b) => b.stageId === stageId)
  const stage = props.spec.stages.find((s) => s.id === stageId)
  if (!rect || !stage) return want
  // 避让集 = 当前视觉槽位全集：无记忆成员的默认分配槽 ∪ 有记忆成员的记忆矩形
  const occupied: { x: number; y: number; w: number; h: number }[] = []
  for (const p of defaultMemberPositions(stage, { x: rect.x, y: rect.y }).values()) {
    occupied.push({ x: p.x, y: p.y, w: CARD_W, h: CARD_H })
  }
  for (const slug of memberSlugsOf(stage)) {
    const r = memberRect(stageId, slug)
    if (r) occupied.push(r)
  }
  let x = clamp(want.x, rect.x + 8, rect.x + rect.width - CARD_W - 8)
  let y = clamp(want.y, rect.y + 48, rect.y + rect.height)
  let guard = 0
  while (occupied.some((o) => rectsOverlap({ x, y, w: CARD_W, h: CARD_H }, o)) && guard++ < 100) {
    x += LAYOUT.colW
    if (x + CARD_W > rect.x + rect.width - 8) {
      x = rect.x + 70
      y += LAYOUT.rowH
    }
  }
  return { x, y }
}

function onBandResizeEnd(payload: { stageId: string; height: number }) {
  stageHeights.value[payload.stageId] = payload.height
  rebuild()
}

const MODE_LABEL: Record<string, string> = {
  parallel_batch: '并行',
  debate: '公平辩论',
  single: '单智能体',
}

/** 重建前收割当前节点位置（拖动自由排布不被 spec 变更重置） */
function harvestPositions() {
  for (const n of getNodes.value) {
    if (n.position) positions.value[n.id] = { ...n.position }
  }
}

/** 组成员 slug 全集（debate：辩手+裁决；batch：pool 展开或显式枚举；single：node） */
function memberSlugsOf(stage: StageSpecDto): string[] {
  if (stage.mode === 'debate') return stageMemberSlugs(stage)
  return stageMembers(props.spec, stage, agents.value).map((m) => m.slug)
}

/** 组自动高度（成员行数推导；用户手动调高取 max） */
function stageHeightOf(stage: StageSpecDto): number {
  const rows =
    stage.mode === 'debate'
      ? 2
      : Math.max(1, Math.ceil(stageMembers(props.spec, stage, agents.value).length / LAYOUT.maxCols))
  return Math.max(LAYOUT.padTop + rows * LAYOUT.rowH + 16, stageHeights.value[stage.id] || 0)
}

function defaultMemberPositions(stage: StageSpecDto, bandPos: { x: number; y: number }): Map<string, { x: number; y: number }> {
  const map = new Map<string, { x: number; y: number }>()
  const members = stageMembers(props.spec, stage, agents.value)
  // 已有位置记忆的成员不参与默认分配，但其占位要让新成员避让（不压盖）
  const taken: { x: number; y: number; w: number; h: number }[] = []
  for (const m of stageMembers(props.spec, stage, agents.value)) {
    const r = memberRect(stage.id, m.slug)
    if (r) taken.push(r)
  }
  const place = (slug: string, x: number, y: number) => {
    let cx = x
    let cy = y
    let guard = 0
    while (taken.some((o) => rectsOverlap({ x: cx, y: cy, w: CARD_W, h: CARD_H }, o)) && guard++ < 100) {
      cx += LAYOUT.colW
      if (cx + CARD_W > bandPos.x + LAYOUT.bandWidth - 8) {
        cx = bandPos.x + 70
        cy += LAYOUT.rowH
      }
    }
    const pos = { x: cx, y: cy }
    taken.push({ ...pos, w: CARD_W, h: CARD_H })
    map.set(memberNodeId(stage.id, slug), pos)
  }

  if (stage.mode === 'debate') {
    const sides = stage.sides || []
    const offset = Math.max(0, (LAYOUT.bandWidth - 140 - sides.length * LAYOUT.colW) / 2)
    sides.forEach((s, i) => place(s, bandPos.x + 70 + offset + i * LAYOUT.colW, bandPos.y + LAYOUT.padTop + 10))
    if (stage.judge) {
      const jx = bandPos.x + 70 + Math.max(0, (LAYOUT.bandWidth - 140 - LAYOUT.colW) / 2)
      place(stage.judge, jx, bandPos.y + LAYOUT.padTop + 10 + LAYOUT.rowH)
    }
    return map
  }
  members.forEach((m, i) =>
    place(
      m.slug,
      bandPos.x + 70 + (i % LAYOUT.maxCols) * LAYOUT.colW,
      bandPos.y + LAYOUT.padTop + Math.floor(i / LAYOUT.maxCols) * LAYOUT.rowH,
    ),
  )
  return map
}

/** 清理已删除组/成员的位置与高度记忆（防孤儿键膨胀） */
function pruneMemories() {
  const liveIds = new Set<string>()
  for (const stage of props.spec.stages) {
    liveIds.add(bandNodeId(stage.id))
    for (const slug of memberSlugsOf(stage)) liveIds.add(memberNodeId(stage.id, slug))
  }
  for (const id of Object.keys(positions.value)) {
    if (!liveIds.has(id)) delete positions.value[id]
  }
  const liveStages = new Set(props.spec.stages.map((s) => s.id))
  for (const id of Object.keys(stageHeights.value)) {
    if (!liveStages.has(id)) delete stageHeights.value[id]
  }
}

function rebuild() {
  harvestPositions()
  const nodes: Node[] = []
  const edges: Edge[] = []
  edgeIndex.clear()
  bandRects.length = 0
  const stageCount = props.spec.stages.length

  // 无位置记忆的组默认垂直堆叠，且起点让开全部已记忆组（防新组压住用户挪走的组）
  let stackY = 0
  for (const stage of props.spec.stages) {
    const remembered = positions.value[bandNodeId(stage.id)]
    if (remembered) stackY = Math.max(stackY, remembered.y + stageHeightOf(stage))
  }

  // 悬空绑定按消费方节点聚合（成员卡/band 各自显示警示角标）
  const { edges: bindingEdges, dangling } = buildBindingGraph(props.spec, agents.value)
  const danglingByNode = new Map<string, DanglingBinding[]>()
  for (const d of dangling) {
    const list = danglingByNode.get(d.nodeId)
    if (list) list.push(d)
    else danglingByNode.set(d.nodeId, [d])
  }

  props.spec.stages.forEach((stage, idx) => {
    const bId = bandNodeId(stage.id)
    const rememberedPos = positions.value[bId]
    const bandPos = rememberedPos || { x: 0, y: stackY }
    if (!rememberedPos) positions.value[bId] = { ...bandPos }
    const memberSlugs = memberSlugsOf(stage)
    // 高度：自动行数推导 ∪ 包住全部成员（落点定位的成员可能低于自动行数）
    let height = stageHeightOf(stage)
    for (const slug of memberSlugs) {
      const p = positions.value[memberNodeId(stage.id, slug)]
      if (p) height = Math.max(height, p.y - bandPos.y + CARD_H + 16)
    }
    if (!rememberedPos) stackY += height + LAYOUT.gapY
    bandRects.push({ stageId: stage.id, x: bandPos.x, y: bandPos.y, width: LAYOUT.bandWidth, height })

    const memberPos = defaultMemberPositions(stage, bandPos)

    const slotsOf = (slug: string): string[] => {
      const meta = agents.value.find((a) => a.slug === slug)
      return meta?.template_slots || []
    }
    const declaredOf = (slug: string): Record<string, unknown> | undefined => {
      if (stage.mode === 'single') return stage.inputs
      const ref = (stage.nodes || []).find((n) => n.ref === slug)
      return ref?.inputs
    }
    // 辩论组输入槽常显（未连线也能看到口、可发起连线）：成员契约槽并集 ∪ 已声明键；
    // 成员全无契约时兜底通用槽 context（prompt 以 {{inputs.context}} 引用）。
    // 非辩论组输入口在成员卡片上，band 不显示。
    let bandInputs: string[] = []
    if (stage.mode === 'debate') {
      const contract = new Set<string>()
      for (const slug of [...(stage.sides || []), stage.judge].filter((s): s is string => Boolean(s))) {
        for (const s of slotsOf(slug)) contract.add(s)
      }
      bandInputs = [...contract, ...Object.keys(stage.inputs || {}).filter((k) => !contract.has(k))]
      if (!bandInputs.length) bandInputs = ['context']
    }

    const outPortList = bandOutPorts(props.spec, stage)
    nodes.push({
      id: bId,
      type: 'sband',
      position: { ...bandPos },
      draggable: !effectiveReadonly.value,
      selectable: true,
      // 节点 zIndex 两层族：band = idx+1（1..N），成员 = N+idx+1——成员族整体高于
      // 全部 band 族，后组区域框不再盖住前组成员卡（Vue Flow 节点按 zIndex 排序）
      zIndex: idx + 1,
      data: {
        index: idx,
        stageId: stage.id,
        mode: stage.mode,
        modeLabel: MODE_LABEL[stage.mode] || stage.mode,
        optional: stage.optional,
        rounds: stage.rounds,
        memberCount: memberSlugs.length,
        width: LAYOUT.bandWidth,
        height,
        inSlots: bandInputs.map((slot) => ({ slot, scalar: ['judge_decision'].includes(slot) })),
        outPorts: outPortList,
        dangling: danglingByNode.get(bId) || [],
        resizable: !effectiveReadonly.value,
        isFirst: idx === 0,
        isLast: idx === props.spec.stages.length - 1,
        hasTerminal: memberSlugs.some(
          (slug) => props.spec.nodes.find((n) => n.slug === slug)?.terminal === true,
        ),
        orderControls: !effectiveReadonly.value,
      } satisfies BandData,
    })

    // 成员节点
    for (const slug of memberSlugs) {
      const id = memberNodeId(stage.id, slug)
      const def = props.spec.nodes.find((n) => n.slug === slug)
      const meta = agents.value.find((a) => a.slug === slug)
      const isDebateMember = stage.mode === 'debate'
      // 动态成员仅指 pool 自动纳入的分析师（只读展示）；其余成员均可自由摆位
      const isDynamic = stage.mode === 'parallel_batch' && !!stage.pool
      // 输入槽：辩论成员由组输入统一注入（卡片不显示）；single 成员无契约且未声明时
      // 兜底通用槽 context；并行组成员为纯生产者（编译器丢弃 NodeRef.inputs）不消费输入
      const memberInSlots = isDebateMember
        ? []
        : consumerInSlots(slotsOf(slug), declaredOf(slug) as Record<string, never> | undefined)
      if (stage.mode === 'single' && !memberInSlots.length) memberInSlots.push({ slot: 'context', scalar: false })
      const data: NodeCardData = {
        label: def?.node_name || meta?.name || slug,
        sub: slug,
        typeBadge: def?.type || (meta?.phase === 1 ? 'analyst' : undefined),
        execBadge: def?.execution,
        terminal: def?.terminal === true,
        producerOnly: stage.mode === 'parallel_batch',
        inSlots: memberInSlots,
        // 辩论成员（辩手与裁决）不直接对外输出：组输出统一走 band 端口（公平辩论封闭容器）
        outPorts: isDebateMember ? [] : nodeOutPorts(props.spec, slug, agents.value),
        dangling: danglingByNode.get(id) || [],
        // 仅 pool 动态成员锁定（自动生成的只读展示）；显式成员/辩手/单智能体均可自由摆位
        locked: isDynamic,
      }
      const pos = memberPos.get(id) || { x: bandPos.x + 70, y: bandPos.y + LAYOUT.padTop }
      nodes.push({
        id,
        type: 'ncard',
        position: positions.value[id] || pos,
        draggable: !effectiveReadonly.value && !data.locked,
        selectable: true,
        zIndex: stageCount + idx + 1,
        data,
      })
      if (!positions.value[id]) positions.value[id] = pos
    }
  })

  // 边不设 zIndex：Vue Flow 边层（svg）恒在节点层（div）之下且无法翻转——
  // 线的可见性靠 band 背景半透明化保证（StageBand 样式），勿在此逐边抬层级
  for (const be of bindingEdges) {
    const slot = be.targetHandle.startsWith('in:') ? be.targetHandle.slice(3) : be.targetHandle
    edgeIndex.set(be.id, { target: be.target, slot, value: be.bindingKey })
    const kind = edgeKind(be.bindingKey)
    edges.push({
      id: be.id,
      source: be.source,
      target: be.target,
      sourceHandle: be.sourceHandle,
      targetHandle: be.targetHandle,
      type: 'binding',
      data: { bindingKey: be.bindingKey, kind },
    })
  }

  setNodes(nodes)
  setEdges(edges)
  pruneMemories()
}

function edgeKind(value: string): string {
  if (value === ALL_UPSTREAM) return 'all'
  if (/^[\w-]+\.[\w-]+$/.test(value)) return 'field'
  const isState = props.spec.stages.some((s) => effectiveStateKey(s) === value)
  return isState ? 'state' : 'report'
}

// ── 交互 ───────────────────────────────────────────────────────────────────

function onConnect(params: Connection) {
  if (effectiveReadonly.value) return
  if (!params.sourceHandle || !params.targetHandle) return
  const decision = canConnect(
    { spec: props.spec, agents: agents.value },
    params.source,
    params.sourceHandle,
    params.target,
    params.targetHandle,
  )
  if (!decision.ok || !decision.value) {
    ElMessage.warning(decision.reason || '连线被拒绝')
    return
  }
  if (applyConnection(props.spec, params.target, params.targetHandle.slice(3), decision.value)) {
    emit('change')
  }
}

function onEdgeRemove(edgeId: string) {
  if (effectiveReadonly.value) return
  const info = edgeIndex.get(edgeId)
  if (!info) return
  if (removeConnection(props.spec, info.target, info.slot, info.value)) {
    emit('change')
  }
}

// ── 拖动（组可自由搬动并带动成员；成员跨组 = 中心点落入其它组，空白落下纯移动）──

/** 被拖 band 的上一帧位置（逐帧增量跟随成员用） */
let bandDragLast: { bandId: string; x: number; y: number } | null = null

function onNodeDragStart(event: { node: Node }) {
  const parsed = parseNodeId(event.node.id)
  bandDragLast =
    parsed?.kind === 'band'
      ? { bandId: event.node.id, x: event.node.position.x, y: event.node.position.y }
      : null
}

function onNodeDrag(event: { node: Node; nodes: Node[] }) {
  if (effectiveReadonly.value || !bandDragLast || event.node.id !== bandDragLast.bandId) return
  const dx = event.node.position.x - bandDragLast.x
  const dy = event.node.position.y - bandDragLast.y
  bandDragLast.x = event.node.position.x
  bandDragLast.y = event.node.position.y
  const parsed = parseNodeId(event.node.id)
  if (!parsed || (dx === 0 && dy === 0)) return
  const stage = props.spec.stages.find((s) => s.id === parsed.stageId)
  if (!stage) return
  // 多选拖动时 Vue Flow 已移动被选成员（event.nodes）——跳过防双重位移
  const draggedIds = new Set(event.nodes.map((n) => n.id))
  for (const slug of memberSlugsOf(stage)) {
    const id = memberNodeId(stage.id, slug)
    if (draggedIds.has(id)) continue
    const n = findNode(id)
    if (n) n.position = { x: n.position.x + dx, y: n.position.y + dy }
  }
}

async function onNodeDragStop(event: { node: Node; nodes: Node[] }) {
  if (effectiveReadonly.value) return
  bandDragLast = null
  const parsed = parseNodeId(event.node.id)
  if (!parsed) return

  if (parsed.kind === 'band') {
    // 组拖动落定：提交位置记忆 + 同步 bandRects（不 rebuild，保选中态）
    for (const node of event.nodes) {
      const p = parseNodeId(node.id)
      if (p?.kind !== 'band') continue
      positions.value[node.id] = { ...node.position }
      const rect = bandRects.find((b) => b.stageId === p.stageId)
      if (rect) {
        rect.x = node.position.x
        rect.y = node.position.y
      }
      const stage = props.spec.stages.find((s) => s.id === p.stageId)
      if (stage) {
        for (const slug of memberSlugsOf(stage)) {
          const n = findNode(memberNodeId(p.stageId, slug))
          if (n) positions.value[n.id] = { ...n.position }
        }
      }
    }
    return
  }

  // 成员拖动落定（多选时逐个处理；single 目标会弹确认，串行防并发弹窗）
  for (const node of event.nodes) {
    await handleMemberDragStop(node)
  }
}

async function handleMemberDragStop(node: Node) {
  const parsed = parseNodeId(node.id)
  if (!parsed || parsed.kind !== 'node') return
  const sourceStage = props.spec.stages.find((s) => s.id === parsed.stageId)
  if (!sourceStage || sourceStage.mode !== 'parallel_batch' || sourceStage.pool) return
  // 显式枚举成员才允许跨组移动；中心点落入其它组（上层优先，与视觉层级同口径）触发，空白 = 纯移动落定
  const centerX = node.position.x + 90
  const centerY = node.position.y + 40
  const target = bandAtPoint(
    bandRects.filter((b) => b.stageId !== parsed.stageId),
    { x: centerX, y: centerY },
  )
  if (!target) return
  const targetStage = props.spec.stages.find((s) => s.id === target.stageId)
  if (!targetStage) return

  const refIdx = (sourceStage.nodes || []).findIndex((n) => n.ref === parsed.slug)
  if (refIdx < 0) return
  const ref = sourceStage.nodes![refIdx]

  if (targetStage.mode === 'debate') {
    // 任意类型可当辩手（validator 对 sides 无 type 约束）
    if (targetStage.judge === parsed.slug) {
      ElMessage.warning('该智能体是本组裁决，不可兼任辩手')
      return
    }
    sourceStage.nodes!.splice(refIdx, 1)
    targetStage.sides = [...(targetStage.sides || []), parsed.slug]
    ElMessage.success(`已将 ${parsed.slug} 追加为辩论组辩手`)
  } else if (targetStage.mode === 'parallel_batch') {
    if (targetStage.pool) {
      ElMessage.warning('目标并行组是自动模式，无需指定成员')
      return
    }
    sourceStage.nodes!.splice(refIdx, 1)
    targetStage.nodes = [...(targetStage.nodes || []), ref]
    ElMessage.success(`已将 ${parsed.slug} 移入组 ${targetStage.id}`)
  } else {
    // single 组：与 palette 拖入同语义——确认后更换唯一成员；取消则成员留在源组
    const meta = agents.value.find((a) => a.slug === parsed.slug)
    if (!meta) return
    const replaced = await addAgentToStage(props.spec, target.stageId, meta)
    if (!replaced) return
    sourceStage.nodes!.splice(refIdx, 1)
    ElMessage.success(`已将 ${parsed.slug} 设为组 ${targetStage.id} 的唯一成员`)
  }
  // 保留落点（clamp 进目标组并避开已有成员），否则 rebuild 会把它排回组顶默认位。
  // 记忆键随组走：node.id 还是源组键，须删旧键并写目标组键，否则成孤儿被 prune
  delete positions.value[node.id]
  positions.value[memberNodeId(target.stageId, parsed.slug)] = freeSpotInBand(target.stageId, node.position)
  emit('change')
}

// ── palette 拖放（行业标准交互：拖到泳道段加入 / 空白落点建段）────────────────

function onDragOver(event: DragEvent) {
  // 仅放行智能体拖拽源（自定义 mime），不影响节点拖拽/文件拖入等场景；
  // readonly 不 preventDefault → 浏览器天然禁 drop
  if (effectiveReadonly.value) return
  if (!event.dataTransfer?.types?.includes(PALETTE_MIME)) return
  event.preventDefault()
  event.dataTransfer.dropEffect = 'copy'
}

async function onDrop(event: DragEvent) {
  if (effectiveReadonly.value) return
  const raw = event.dataTransfer?.getData(PALETTE_MIME)
  if (!raw) return
  event.preventDefault()
  let payload: { slug?: string; module?: GroupModuleMode } = {}
  try {
    payload = JSON.parse(raw) || {}
  } catch {
    payload = { slug: raw }
  }

  const flow = screenToFlowCoordinate({ x: event.clientX, y: event.clientY })

  // 拖出的是策略模块（并行 / 公平辩论）：落点建空组（命中组 → 其后；空白 → 末尾）
  if (payload.module) {
    const index = insertIndexAtPoint(props.spec, bandRects, flow)
    const stage = blankGroupOf(props.spec, payload.module)
    const stages = props.spec.stages
    stages.splice(index, 0, stage)
    seedBandPosition(stage, flow)
    ElMessage.success(GROUP_ADD_HINTS[payload.module])
    emit('change')
    return
  }

  const agent = agents.value.find((a) => a.slug === payload.slug)
  if (!agent) {
    ElMessage.warning(`智能体库中不存在: ${payload.slug}`)
    return
  }
  // 命中判定与视觉层级同口径（倒序取最上层组）
  const band = bandAtPoint(bandRects, flow)
  if (band) {
    // 落在组内：走三入口统一的判定/确认/执行流
    const changed = await addAgentToStage(props.spec, band.stageId, agent)
    if (changed) {
      // 落点定位：新成员卡左上角对准鼠标（clamp 进组内并避开已有成员，不压盖）
      positions.value[memberNodeId(band.stageId, agent.slug)] = freeSpotInBand(band.stageId, {
        x: flow.x - CARD_W / 2,
        y: flow.y - CARD_H / 2,
      })
      emit('change')
    }
    return
  }
  // 空白落点：按 kind 建组（末尾追加，序号最大，不破坏既有向前引用）
  const index = insertIndexAtPoint(props.spec, bandRects, flow)
  const { stage, hint } = createStageForAgent(props.spec, agent)
  const stages = props.spec.stages
  stages.splice(index, 0, stage)
  seedBandPosition(stage, flow)
  ElMessage.success(hint || `已创建${MODE_LABEL[stage.mode]}组「${stage.id}」并加入 ${agent.name}`)
  emit('change')
}

/**
 * 新建组落点写位置记忆（WYSIWYG：拖到哪出现在哪；中心对准落点）。
 * 落点压到既有组时沿 y 向下顺移到空位（随手拖入也不遮盖已有内容）。
 */
function seedBandPosition(stage: StageSpecDto, flow: { x: number; y: number }) {
  const width = LAYOUT.bandWidth
  const height = stageHeightOf(stage)
  const rect = () => ({ x, y, w: width, h: height })
  let x = flow.x - LAYOUT.bandWidth / 2
  let y = flow.y - 40
  let guard = 0
  while (guard++ < bandRects.length + 1) {
    const hit = bandRects.find((b) => rectsOverlap(rect(), { x: b.x, y: b.y, w: b.width, h: b.height }))
    if (!hit) break
    y = hit.y + hit.height + LAYOUT.gapY
  }
  positions.value[bandNodeId(stage.id)] = { x, y }
}

// ── 一键添加策略组（工具栏 / palette 模块拖出；一律空组，成员由用户拖入）──────

/** 工具栏「+ 并行 / + 公平辩论」：末尾建空组 */
function addStrategyGroup(mode: GroupModuleMode) {
  if (effectiveReadonly.value) return
  const stages = props.spec.stages
  stages.push(blankGroupOf(props.spec, mode))
  ElMessage.success(GROUP_ADD_HINTS[mode])
  emit('change')
}

// ── 选中与属性面板 ──────────────────────────────────────────────────────────

type Selection = { type: 'node' | 'band'; stageId: string; slug?: string } | null
const selection = ref<Selection>(null)

function onNodeClick(event: { node: Node }) {
  const parsed = parseNodeId(event.node.id)
  if (!parsed) return
  selection.value = parsed.kind === 'band' ? { type: 'band', stageId: parsed.stageId } : { type: 'node', stageId: parsed.stageId, slug: parsed.slug }
  emit('stage-select', parsed.stageId)
}

function onPaneClick() {
  selection.value = null
  emit('stage-select', null)
}

function onEdgeClick() {
  // 选中态由 Vue Flow store 维护（getSelectedEdges）；删除走键盘 / 悬浮条 / 边上 ×
}

// ── 选中集删除（键盘 Delete / 悬浮条共用；边直接删，节点/组走确认流）────────

const selectedCount = computed(
  () => getSelectedNodes.value.length + getSelectedEdges.value.length,
)

/** 删除确认弹窗进行中（防 Backspace 在弹窗焦点上重复触发） */
let deleting = false

async function deleteSelection() {
  if (effectiveReadonly.value || deleting) return
  const selNodes = getSelectedNodes.value
  const selEdges = getSelectedEdges.value
  if (!selNodes.length && !selEdges.length) return
  // 边：直接移除声明（与边上 × 同语义，无需确认）
  for (const e of selEdges) onEdgeRemove(e.id)
  if (!selNodes.length) return
  const targets: RemovalTarget[] = []
  for (const n of selNodes) {
    const parsed = parseNodeId(n.id)
    if (!parsed) continue
    targets.push(
      parsed.kind === 'band'
        ? { type: 'band', stageId: parsed.stageId }
        : { type: 'node', stageId: parsed.stageId, slug: parsed.slug },
    )
  }
  deleting = true
  try {
    const changed = await removeSelectionInteractive(props.spec, agents.value, targets)
    if (changed) emit('change')
  } finally {
    deleting = false
  }
}

function clearSelection() {
  for (const n of getSelectedNodes.value) n.selected = false
  for (const e of getSelectedEdges.value) e.selected = false
}

// ── 终点缺失提示（validator 要求 ≥1 个 terminal:true 的 judge/terminal 节点）──

const missingTerminal = computed(
  () => props.spec.stages.length > 0 && !hasActiveTerminal(props.spec),
)

// ── 组重排（band 头部 ↑↓；预检向前引用失效，确认后自动摘除）────────────────

async function onBandReorder(payload: { stageId: string; delta: -1 | 1 }) {
  if (effectiveReadonly.value) return
  const from = props.spec.stages.findIndex((s) => s.id === payload.stageId)
  if (from < 0) return
  const to = from + payload.delta
  if (to < 0 || to >= props.spec.stages.length) return
  const changed = await reorderStageInteractive(props.spec, agents.value, from, to)
  if (changed) emit('change')
}

function onKeydown(ev: KeyboardEvent) {
  if (effectiveReadonly.value || deleting) return
  if (ev.key !== 'Delete' && ev.key !== 'Backspace') return
  const el = ev.target as HTMLElement | null
  if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)) return
  if (!selectedCount.value) return
  ev.preventDefault()
  void deleteSelection()
}

function minimapClass(node: Node) {
  return parseNodeId(node.id)?.kind === 'band' ? 'minimap-band' : ''
}

function autoLayout() {
  positions.value = {}
  rebuild()
  fitView({ padding: 0.12, duration: 300 })
}

function fitAll() {
  fitView({ padding: 0.12, duration: 300 })
}

function onChange() {
  emit('change')
}

watch(
  () => props.spec,
  () => rebuild(),
  { deep: true },
)

// 智能体库晚到/刷新（数组引用变化）也触发重建：pool 组成员与端口派生依赖 agents，
// 只 watch spec 会让晚到的库数据不生效（成员全缺直到下一次 spec 变更）
watch(
  () => props.agents,
  () => rebuild(),
)

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  rebuild()
  requestAnimationFrame(() => fitView({ padding: 0.12 }))
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
})
</script>

<style lang="scss">
@import '@vue-flow/core/dist/style.css';
@import '@vue-flow/core/dist/theme-default.css';
@import '@vue-flow/controls/dist/style.css';
@import '@vue-flow/minimap/dist/style.css';

/* 删除/重排确认弹窗的消息换行（ElMessageBox 挂 body，须全局样式） */
.ta-msgbox-preline .el-message-box__message {
  white-space: pre-line;
}
</style>

<style lang="scss" scoped>
.canvas-stage {
  position: relative;
  width: 100%;
  height: calc(100vh - 210px);
  min-height: 480px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  overflow: hidden;

  &.readonly {
    opacity: 0.96;
  }
}

.canvas-toolbar {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 4px 8px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}

.canvas-hint {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  margin-left: 6px;
}

.canvas-empty-guide {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  pointer-events: none;
  color: var(--el-text-color-secondary);

  .guide-icon {
    font-size: 40px;
    margin-bottom: 8px;
  }

  .guide-title {
    font-size: 15px;
    font-weight: 600;
    margin-bottom: 6px;
    color: var(--el-text-color-primary);
  }

  p {
    font-size: 12px;
    line-height: 1.8;
    margin: 0;
  }
}

:deep(.minimap-band) {
  fill: var(--el-fill-color-dark);
}

.canvas-terminal-alert {
  position: absolute;
  top: 52px;
  left: 50%;
  transform: translateX(-50%);
  width: min(640px, 80%);
  z-index: 9;
  border-radius: 8px;
}

.canvas-selection-bar {
  position: absolute;
  top: 92px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-color-danger-light-5);
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
  z-index: 9;
  font-size: 12px;
  color: var(--el-text-color-regular);
}
</style>
