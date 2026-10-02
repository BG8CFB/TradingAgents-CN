<template>
  <div
    class="sband"
    :class="{
      selected,
      debate: data.mode === 'debate',
      disabled: data.disabled,
      dangling: (data.dangling || []).length > 0,
    }"
    :style="{ width: `${data.width}px`, height: `${displayHeight}px` }"
  >
    <div class="sband-head">
      <span class="sband-no" :title="data.isFirst ? '起点：第一个执行的组' : `执行顺序第 ${data.index + 1}`">
        {{ data.index + 1 }}
      </span>
      <span v-if="data.isFirst" class="sband-flag start" title="起点：第一个执行的组">▶ 起点</span>
      <span v-if="data.hasTerminal" class="sband-flag end" title="终点：组内含终点节点（写入最终决策）">🏁 终点</span>
      <el-tag size="small" effect="plain">{{ data.modeLabel }}</el-tag>
      <el-tag
        v-if="data.optional"
        size="small"
        type="warning"
        effect="plain"
        title="可选组：发起分析时可在分析页关闭跳过；关闭后整组（辩手+裁决）不执行"
      >
        可选
      </el-tag>
      <span v-if="data.mode === 'debate' && typeof data.rounds === 'number'" class="sband-rounds">
        {{ data.rounds }} 轮
      </span>
      <span class="sband-fill" />
      <span class="sband-title" :title="data.stageId">{{ data.stageId }}</span>
      <span class="sband-count">{{ data.memberCount }} 成员</span>
      <el-tooltip v-if="(data.dangling || []).length" placement="bottom">
        <template #content>
          <div v-for="(d, i) in data.dangling" :key="i">in:{{ d.slot }} ← {{ d.value }}（{{ d.reason }}）</div>
        </template>
        <span class="sband-warn" :aria-label="`组输入有 ${data.dangling!.length} 条悬空绑定`">
          ⚠ {{ data.dangling!.length }}
        </span>
      </el-tooltip>
      <span v-if="data.orderControls" class="sband-ops">
        <button
          class="sband-op"
          :disabled="data.isFirst"
          title="执行顺序前移一位"
          @pointerdown.stop
          @click.stop="emit('reorder', { stageId: data.stageId, delta: -1 })"
        >
          ↑
        </button>
        <button
          class="sband-op"
          :disabled="data.isLast"
          title="执行顺序后移一位"
          @pointerdown.stop
          @click.stop="emit('reorder', { stageId: data.stageId, delta: 1 })"
        >
          ↓
        </button>
      </span>
    </div>

    <!-- 辩论封闭容器提示区（成员节点由布局排入容器区域；组内边由模式封装不显示） -->
    <div v-if="data.mode === 'debate'" class="sband-container-hint">
      公平辩论：辩手交替发言 · 裁决收束，组外只经组输入与组输出交互
    </div>

    <!-- 空组引导（成员从左侧拖入） -->
    <div v-if="emptyHint" class="sband-empty">
      <span class="sband-empty-icon">⤵</span>
      {{ emptyHint }}
    </div>

    <!-- 组输入端口（左，仅辩论段；single/batch 成员端口在各自卡片上） -->
    <div v-if="data.inSlots.length" class="sband-slots">
      <div v-for="s in data.inSlots" :key="s.slot" class="sband-slot-row">
        <Handle
          :id="`in:${s.slot}`"
          type="target"
          :position="Position.Left"
          class="sband-handle in"
          :class="{ scalar: s.scalar }"
          :title="s.slot === 'context'
            ? '通用组输入槽（成员无契约槽时兜底）：连线后 prompt 以 {{inputs.context}} 引用'
            : s.scalar ? `组输入槽 ${s.slot}（单来源）` : `组输入槽 ${s.slot}`"
          :aria-label="`组输入槽 ${s.slot}`"
        />
        <span class="sband-slot-name">{{ s.slot }}</span>
      </div>
    </div>

    <!-- 组输出端口（右：全部上游 / 裁决报告与字段 / 辩论全记录） -->
    <div class="sband-outs">
      <div v-for="p in data.outPorts" :key="p.id" class="sband-port-row">
        <span class="sband-port-name" :title="p.key">{{ p.label }}</span>
        <Handle
          :id="p.id"
          type="source"
          :position="Position.Right"
          class="sband-handle out"
          :class="{ all: p.kind === 'all' }"
          :title="p.key"
          :aria-label="`组输出 ${p.label}`"
        />
      </div>
    </div>

    <!-- 高度调整手柄（右下角；纯视觉状态不进 spec） -->
    <div
      v-if="data.resizable"
      class="sband-resize"
      title="拖动调整区域高度"
      @pointerdown="onResizeStart"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import type { DanglingBinding, InSlot, OutPort } from './edgeRules'

/** 策略组容器：并行 / 公平辩论 / 单智能体的区域框，可自由摆放；序号 = 执行顺序 */

export interface BandData {
  index: number
  stageId: string
  mode: 'parallel_batch' | 'debate' | 'single'
  modeLabel: string
  optional?: boolean
  rounds?: number
  disabled?: boolean
  memberCount: number
  width: number
  height: number
  inSlots: InSlot[]
  outPorts: OutPort[]
  /** 组输入中解析失败的声明（无对应画布边）：红色警示角标 + hover 明细 */
  dangling?: DanglingBinding[]
  /** 空组引导文案（成员未就位时中央提示） */
  emptyHint?: string
  /** 允许调整高度（readonly 时隐藏手柄） */
  resizable?: boolean
  /** 第一个执行的组（起点标记） */
  isFirst?: boolean
  /** 最后一个组（↓ 禁用边界） */
  isLast?: boolean
  /** 组内含 terminal:true 成员（终点标记） */
  hasTerminal?: boolean
  /** 显示执行顺序调整按钮（非 readonly） */
  orderControls?: boolean
}

const props = defineProps<{
  data: BandData
  selected?: boolean
}>()

const emit = defineEmits<{
  /** 高度调整结束（提交给画布层记忆；纯视觉状态不写 spec） */
  (e: 'resize-end', payload: { stageId: string; height: number }): void
  /** 执行顺序调整（delta = ±1；连线失效检测在画布层交互入口完成） */
  (e: 'reorder', payload: { stageId: string; delta: -1 | 1 }): void
}>()

const EMPTY_HINTS: Record<string, string> = {
  parallel_batch: '从左侧拖入智能体，任意类型均可并行执行',
  debate: '从左侧拖入辩手（任意类型 · 至少 2 方）与 1 名裁决',
  single: '从左侧拖入唯一成员',
}
const emptyHint = computed(
  () => (props.data.memberCount === 0 ? props.data.emptyHint || EMPTY_HINTS[props.data.mode] : ''),
)

// ── 高度调整（拖动中本地预览，pointerup 提交）──────────────────────────────
const displayHeight = ref(props.data.height)
let resizeStart: { y: number; height: number } | null = null

// 节点实例被 Vue Flow 复用时跟随外部高度（拖动中不回写）
watch(
  () => props.data.height,
  (h) => {
    if (!resizeStart) displayHeight.value = h
  },
)

function onResizeMove(ev: PointerEvent) {
  if (!resizeStart) return
  displayHeight.value = Math.max(props.data.height, resizeStart.height + ev.clientY - resizeStart.y)
}
function onResizeEnd() {
  window.removeEventListener('pointermove', onResizeMove)
  window.removeEventListener('pointerup', onResizeEnd)
  if (resizeStart && displayHeight.value !== props.data.height) {
    emit('resize-end', { stageId: props.data.stageId, height: displayHeight.value })
  }
  resizeStart = null
}
function onResizeStart(ev: PointerEvent) {
  ev.stopPropagation()
  ev.preventDefault()
  resizeStart = { y: ev.clientY, height: displayHeight.value }
  window.addEventListener('pointermove', onResizeMove)
  window.addEventListener('pointerup', onResizeEnd)
}
</script>

<style lang="scss" scoped>
.sband {
  border: 1px solid var(--el-border-color-light);
  border-radius: 14px;
  /* 半透明：Vue Flow 边层（svg）恒在节点层（div）之下且 zIndex 无法翻转，
     不透明组背景会遮住穿过组区域的连线——组只做视觉组织，不遮线 */
  background: var(--el-fill-color-blank);
  background: color-mix(in srgb, var(--el-fill-color-blank) 62%, transparent);
  position: relative;

  &.debate {
    border-style: dashed;
    background: var(--el-color-warning-light-9);
    background: color-mix(in srgb, var(--el-color-warning-light-9) 62%, transparent);
  }

  &.selected {
    border-color: var(--el-color-primary);
    box-shadow: 0 0 0 2px var(--el-color-primary-light-8);
  }

  &.disabled {
    opacity: 0.55;
  }

  &.dangling {
    border-color: var(--el-color-danger);
  }
}

.sband-warn {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--el-color-danger);
  cursor: help;
}

.sband-head {
  position: absolute;
  top: 10px;
  left: 14px;
  right: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.sband-no {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--el-color-primary);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.sband-flag {
  flex-shrink: 0;
  font-size: 10px;
  line-height: 1;
  padding: 3px 6px;
  border-radius: 4px;

  &.start {
    color: var(--el-color-success);
    background: var(--el-color-success-light-9);
    border: 1px solid var(--el-color-success-light-5);
  }

  &.end {
    color: var(--el-color-danger);
    background: var(--el-color-danger-light-9);
    border: 1px solid var(--el-color-danger-light-5);
  }
}

.sband-title {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sband-ops {
  display: inline-flex;
  gap: 2px;
  flex-shrink: 0;
}

.sband-op {
  width: 20px;
  height: 20px;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  background: var(--el-bg-color);
  color: var(--el-text-color-regular);
  font-size: 11px;
  line-height: 1;
  cursor: pointer;

  &:hover:not(:disabled) {
    border-color: var(--el-color-primary);
    color: var(--el-color-primary);
  }

  &:disabled {
    cursor: not-allowed;
    opacity: 0.4;
  }
}

.sband-rounds {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.sband-fill {
  flex: 1;
}

.sband-count {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.sband-container-hint {
  position: absolute;
  top: 40px;
  left: 30px;
  right: 30px;
  text-align: center;
  font-size: 10px;
  color: var(--el-text-color-secondary);
  border-top: 1px dashed var(--el-border-color);
  padding-top: 3px;
}

.sband-empty {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-size: 12px;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-light);
  border: 1px dashed var(--el-border-color);
  border-radius: 8px;
  padding: 10px 18px;
  pointer-events: none;
  white-space: nowrap;

  .sband-empty-icon {
    margin-right: 4px;
  }
}

.sband-slots,
.sband-outs {
  position: absolute;
  top: 58px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.sband-slots {
  left: 14px;
}

.sband-outs {
  right: 14px;
}

.sband-slot-row,
.sband-port-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 14px;
}

.sband-port-row {
  justify-content: flex-end;
}

.sband-slot-name,
.sband-port-name {
  font-size: 10px;
  color: var(--el-text-color-secondary);
  max-width: 130px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sband-handle {
  width: 10px;
  height: 10px;
  border: 1.5px solid var(--el-color-primary);
  background: var(--el-bg-color);

  &.in {
    margin-left: -20px;
  }

  &.out {
    margin-right: -20px;
  }

  &.all {
    border-style: dashed;
    border-color: var(--el-color-success);
  }

  &.scalar {
    border-color: var(--el-color-warning);
  }

  &:hover {
    width: 13px;
    height: 13px;
  }
}

.sband-resize {
  position: absolute;
  right: 2px;
  bottom: 2px;
  width: 18px;
  height: 18px;
  cursor: ns-resize;
  border-radius: 4px;
  background:
    linear-gradient(135deg, transparent 50%, var(--el-border-color-dark) 50%) no-repeat center / 8px 8px,
    linear-gradient(135deg, transparent 65%, var(--el-border-color) 65%) no-repeat 2px 8px / 8px 8px;

  &:hover {
    background-color: var(--el-fill-color-light);
  }
}
</style>
