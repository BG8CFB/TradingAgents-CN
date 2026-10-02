<template>
  <BaseEdge :id="id" :path="path" :style="edgeStyle" />
  <EdgeLabelRenderer style="z-index: 1">
    <div
      class="bedge-label"
      :class="{ selected, hover }"
      :style="{ transform: `translate(-50%, -50%) translate(${centerX}px, ${centerY}px)` }"
      @mouseenter="hover = true"
      @mouseleave="hover = false"
    >
      <span class="bedge-key" :title="data?.bindingKey">{{ data?.bindingKey }}</span>
      <button
        v-if="removable"
        v-show="hover || selected"
        class="bedge-del"
        :aria-label="`删除连线 ${data?.bindingKey}`"
        title="删除连线"
        @click.stop="emit('remove', id)"
      >
        ×
      </button>
    </div>
  </EdgeLabelRenderer>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { BaseEdge, EdgeLabelRenderer, getBezierPath, Position } from '@vue-flow/core'

/** 连线 = inputs 声明（§5.3）：label 显示绑定键，悬停出 × 删除（删除即移除声明） */

const props = defineProps<{
  id: string
  sourceX: number
  sourceY: number
  targetX: number
  targetY: number
  sourcePosition?: Position
  targetPosition?: Position
  selected?: boolean
  removable?: boolean
  data?: { bindingKey?: string; kind?: string }
}>()

const emit = defineEmits<{ (e: 'remove', edgeId: string): void }>()

const hover = ref(false)

const pathResult = computed(() =>
  getBezierPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    sourcePosition: props.sourcePosition || Position.Right,
    targetX: props.targetX,
    targetY: props.targetY,
    targetPosition: props.targetPosition || Position.Left,
  }),
)

const path = computed(() => pathResult.value[0])
const centerX = computed(() => pathResult.value[1] ?? (props.sourceX + props.targetX) / 2)
const centerY = computed(() => pathResult.value[2] ?? (props.sourceY + props.targetY) / 2)

const edgeStyle = computed(() => {
  if (props.data?.kind === 'all') return { strokeDasharray: '6 4' }
  if (props.data?.kind === 'field' || props.data?.kind === 'state') {
    return { strokeWidth: 1.5 }
  }
  return undefined
})
</script>

<style lang="scss" scoped>
.bedge-label {
  position: absolute;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 1px 6px;
  border-radius: 6px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  font-size: 10px;
  color: var(--el-text-color-secondary);
  pointer-events: all;
  cursor: default;

  &.selected {
    border-color: var(--el-color-primary);
    color: var(--el-color-primary);
  }
}

.bedge-key {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bedge-del {
  border: none;
  background: var(--el-color-danger);
  color: #fff;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  font-size: 11px;
  line-height: 1;
  cursor: pointer;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
</style>
