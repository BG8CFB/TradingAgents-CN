<template>
  <div class="ncard" :class="{ selected, locked: data.locked, dangling: (data.dangling || []).length > 0 }">
    <div class="ncard-head">
      <span class="ncard-icon">{{ typeIcon }}</span>
      <div class="ncard-title">
        <div class="ncard-name" :title="data.label">{{ data.label }}</div>
        <div class="ncard-sub">{{ data.sub }}</div>
      </div>
      <span v-if="data.typeBadge" class="ncard-badge type">{{ data.typeBadge }}</span>
      <span v-if="data.terminal" class="ncard-badge terminal" title="终点节点：写入最终决策字段">🏁</span>
      <span v-if="data.execBadge" class="ncard-badge exec" :title="`执行模式：${data.execBadge}`">
        {{ data.execBadge === 'tool_loop' ? '⚙' : '💬' }}
      </span>
      <el-tooltip v-if="(data.dangling || []).length" placement="top">
        <template #content>
          <div v-for="(d, i) in data.dangling" :key="i">in:{{ d.slot }} ← {{ d.value }}（{{ d.reason }}）</div>
        </template>
        <span class="ncard-badge dangling" :aria-label="`有 ${data.dangling!.length} 条悬空绑定`">
          ⚠ {{ data.dangling!.length }}
        </span>
      </el-tooltip>
      <span v-if="data.locked" class="ncard-lock" title="该工作流必选">🔒</span>
    </div>

    <!-- 输入端口（左）：按槽逐个显示；连线写入 inputs 声明的对应槽 -->
    <div v-if="data.inSlots.length" class="ncard-slots">
      <div v-for="s in data.inSlots" :key="s.slot" class="slot-row">
        <Handle
          :id="`in:${s.slot}`"
          type="target"
          :position="Position.Left"
          class="ncard-handle in"
          :class="{ scalar: s.scalar }"
          :connectable-start="!data.locked"
          :title="s.slot === 'context'
            ? '通用输入槽（无契约槽时兜底）：连线后 prompt 以 {{inputs.context}} 引用'
            : s.scalar ? `槽 ${s.slot}（单来源）` : `槽 ${s.slot}`"
          :aria-label="`输入槽 ${s.slot}`"
        />
        <span class="slot-name">{{ s.slot }}</span>
      </div>
    </div>
    <!-- 纯生产者（并行组成员）：仅产出报告供下游引用，不消费上游输入 -->
    <div v-else-if="data.producerOnly" class="ncard-producer">
      纯生产者 · 不消费输入
    </div>

    <!-- 输出端口（右）：主输出 = 报告键；all/field/state 端口由泳道段承载 -->
    <div v-if="data.outPorts.length" class="ncard-outs">
      <div v-for="p in data.outPorts" :key="p.id" class="port-row">
        <span class="port-name" :title="p.key">{{ p.label }}</span>
        <Handle
          :id="p.id"
          type="source"
          :position="Position.Right"
          class="ncard-handle out"
          :title="p.key"
          :aria-label="`输出 ${p.label}`"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import type { DanglingBinding, InSlot, OutPort } from './edgeRules'

/** 画布节点卡片（§5.3）：图标 + 名称 + type/execution 徽标 + 槽端口 */

export interface NodeCardData {
  label: string
  sub?: string
  typeBadge?: string
  execBadge?: string
  /** 终点节点（terminal:true——最终决策写入者） */
  terminal?: boolean
  /** 纯生产者（并行组成员）：不消费上游输入，卡片显示提示而非输入槽 */
  producerOnly?: boolean
  inSlots: InSlot[]
  outPorts: OutPort[]
  /** 输入声明解析失败（无对应画布边）：红色警示角标 + hover 明细 */
  dangling?: DanglingBinding[]
  locked?: boolean
}

const props = defineProps<{
  id: string
  data: NodeCardData
  selected?: boolean
}>()

const TYPE_ICONS: Record<string, string> = {
  analyst: '📊',
  debater: '🗣',
  judge: '⚖',
  trader: '💰',
  summarizer: '📝',
  terminal: '🏁',
}

const typeIcon = computed(() => TYPE_ICONS[props.data.typeBadge || ''] || '🔵')
</script>

<style lang="scss" scoped>
.ncard {
  min-width: 190px;
  max-width: 240px;
  border: 1px solid var(--el-border-color);
  border-radius: 10px;
  background: var(--el-bg-color);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
  padding: 8px 10px;
  font-size: 12px;
  transition: border-color 0.15s ease;

  &.selected {
    border-color: var(--el-color-primary);
    box-shadow: 0 0 0 2px var(--el-color-primary-light-7);
  }

  &.locked {
    background: var(--el-fill-color-light);
  }

  &.dangling {
    border-color: var(--el-color-danger);
    border-style: dashed;
  }
}

.ncard-head {
  display: flex;
  align-items: center;
  gap: 6px;
}

.ncard-icon {
  font-size: 15px;
}

.ncard-title {
  flex: 1;
  min-width: 0;
}

.ncard-name {
  font-weight: 600;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ncard-sub {
  color: var(--el-text-color-secondary);
  font-size: 10px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ncard-badge {
  flex-shrink: 0;
  padding: 0 5px;
  border-radius: 4px;
  font-size: 10px;
  line-height: 16px;

  &.type {
    background: var(--el-color-primary-light-9);
    color: var(--el-color-primary);
  }

  &.exec {
    background: var(--el-fill-color);
    color: var(--el-text-color-secondary);
  }

  &.terminal {
    background: var(--el-color-danger-light-9);
    color: var(--el-color-danger);
  }

  &.dangling {
    background: var(--el-color-danger-light-9);
    color: var(--el-color-danger);
    cursor: help;
  }
}

.ncard-lock {
  flex-shrink: 0;
  font-size: 11px;
}

.ncard-slots,
.ncard-outs {
  margin-top: 6px;
  border-top: 1px dashed var(--el-border-color-lighter);
  padding-top: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.ncard-producer {
  margin-top: 6px;
  border-top: 1px dashed var(--el-border-color-lighter);
  padding-top: 6px;
  font-size: 10px;
  color: var(--el-text-color-placeholder);
}

.slot-row,
.port-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 14px;
}

.port-row {
  justify-content: flex-end;
}

.slot-name,
.port-name {
  font-size: 10px;
  color: var(--el-text-color-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 150px;
}

.ncard-handle {
  width: 9px;
  height: 9px;
  border: 1.5px solid var(--el-color-primary);
  background: var(--el-bg-color);

  &.in {
    margin-left: -15px;
  }

  &.out {
    margin-right: -15px;
  }

  &.scalar {
    border-color: var(--el-color-warning);
  }

  &:hover {
    width: 12px;
    height: 12px;
  }
}
</style>
