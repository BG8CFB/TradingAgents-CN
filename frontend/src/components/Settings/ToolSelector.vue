<template>
  <div class="tool-selector">
    <div class="tool-selector__header">
      <el-input v-model="search" size="small" clearable placeholder="搜索工具名称或描述">
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
      <div class="tool-selector__summary">
        <span>已选 {{ selected.length }} / {{ tools.length }}</span>
        <el-link type="primary" :underline="false" @click="emit('update:modelValue', [])">清空</el-link>
      </div>
    </div>

    <div class="tool-selector__body">
      <div class="tool-selector__list">
        <el-scrollbar :height="listHeight">
          <el-empty v-if="!filteredTools.length && !loading" :description="emptyText" :image-size="60" />
          <div
            v-for="tool in filteredTools"
            :key="tool.value"
            class="tool-item"
            @click="toggle(tool.value)"
          >
            <div class="tool-item__head">
              <el-checkbox :model-value="selected.includes(tool.value)" @change.stop="" />
              <div class="tool-item__title">
                <span class="tool-item__name">{{ tool.label }}</span>
                <el-tag
                  v-if="tool.kind"
                  size="small"
                  :type="kindColor(tool.kind)"
                  class="tool-kind-tag"
                >
                  {{ kindLabel(tool.kind) }}
                </el-tag>
                <el-tag
                  v-if="tool.availabilityStatus && tool.availabilityStatus !== 'unknown'"
                  size="small"
                  :type="availabilityColor(tool.availabilityStatus)"
                >
                  {{ AVAILABILITY_LABELS[tool.availabilityStatus] }}
                </el-tag>
              </div>
            </div>
            <div v-if="tool.description" class="tool-item__desc">{{ tool.description }}</div>
            <div v-else class="tool-item__desc muted">暂无描述</div>
          </div>
        </el-scrollbar>
      </div>

      <div class="tool-selector__selected">
        <div class="tool-selector__selected-head">
          <span>已选 {{ selected.length }}</span>
          <el-link type="primary" :underline="false" @click="emit('update:modelValue', [])">清空</el-link>
        </div>
        <el-scrollbar :height="listHeight">
          <div v-if="!selected.length" class="muted empty-hint">{{ emptyHint }}</div>
          <div v-for="value in selected" :key="value" class="tool-selected-item">
            <div class="tool-selected-item__title">
              <span>{{ resolveLabel(value) }}</span>
              <el-link type="danger" :underline="false" @click="toggle(value)">移除</el-link>
            </div>
            <div class="tool-selected-item__desc">
              {{ resolveOption(value)?.description || '无描述' }}
            </div>
          </div>
        </el-scrollbar>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Search } from '@element-plus/icons-vue'
import {
  AVAILABILITY_LABELS,
  AVAILABILITY_COLORS,
  type AvailabilityStatus,
  type ToolKind,
} from '@/types/tools'

export interface ToolOption {
  label: string
  value: string
  description?: string
  kind?: ToolKind
  availabilityStatus?: AvailabilityStatus
}

const props = withDefaults(
  defineProps<{
    tools: ToolOption[]
    modelValue: string[]
    loading?: boolean
    listHeight?: string
    emptyText?: string
    /** 未选择时的语义提示（如"未勾选 = 默认全部可用"） */
    emptyHint?: string
  }>(),
  {
    loading: false,
    listHeight: '260px',
    emptyText: '暂无工具',
    emptyHint: '未选择',
  },
)

const emit = defineEmits<{ (e: 'update:modelValue', value: string[]): void }>()

const search = ref('')
const selected = computed(() => props.modelValue || [])

const filteredTools = computed(() => {
  const q = (search.value || '').trim().toLowerCase()
  if (!q) return props.tools
  return props.tools.filter(
    (t) =>
      t.label.toLowerCase().includes(q) ||
      (t.description ? t.description.toLowerCase().includes(q) : false),
  )
})

const toggle = (value: string) => {
  emit(
    'update:modelValue',
    selected.value.includes(value)
      ? selected.value.filter((v) => v !== value)
      : [...selected.value, value],
  )
}

const resolveOption = (value: string) => props.tools.find((t) => t.value === value)
const resolveLabel = (value: string) => resolveOption(value)?.label || value

const KIND_LABELS: Record<ToolKind, string> = {
  datasource: '数据',
  builtin: '内置',
  skill: '技能',
  mcp: 'MCP',
}
const KIND_COLORS: Record<ToolKind, 'primary' | 'success' | 'warning' | 'danger' | 'info'> = {
  datasource: 'primary',
  builtin: 'success',
  skill: 'danger',
  mcp: 'warning',
}
const kindLabel = (kind: ToolKind) => KIND_LABELS[kind] || kind
const kindColor = (kind: ToolKind) => KIND_COLORS[kind] || 'info'
const availabilityColor = (status: AvailabilityStatus) =>
  AVAILABILITY_COLORS[status] as 'primary' | 'success' | 'warning' | 'danger' | 'info'
</script>

<style lang="scss" scoped>
.tool-selector {
  padding: 10px;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  background: var(--el-fill-color-blank);
}

.tool-selector__header {
  display: grid;
  grid-template-columns: 2fr auto;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}

.tool-selector__summary {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  color: var(--el-text-color-secondary);
}

.tool-selector__body {
  display: grid;
  grid-template-columns: 1.3fr 1fr;
  gap: 12px;
}

.tool-selector__list,
.tool-selector__selected {
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  padding: 8px;
  background: var(--el-fill-color-blank);
  min-height: 280px;
}

.tool-item {
  padding: 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: background-color 0.15s ease;

  &:hover {
    background-color: var(--el-fill-color-light);
  }
}

.tool-item__head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.tool-item__title {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.tool-item__name {
  font-weight: 600;
}

.tool-kind-tag {
  flex-shrink: 0;
}

.tool-item__desc {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.muted {
  color: var(--el-text-color-secondary);
}

.empty-hint {
  padding: 8px;
  font-size: 12px;
}

.tool-selector__selected-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.tool-selected-item {
  padding: 8px;
  border-radius: 6px;

  &:not(:last-child) {
    border-bottom: 1px solid var(--el-border-color-light);
  }
}

.tool-selected-item__title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  font-weight: 600;
}

.tool-selected-item__desc {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin: 4px 0;
  line-height: 1.4;
}
</style>
