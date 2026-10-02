<template>
  <div class="binding-editor">
    <div v-for="(row, idx) in rows" :key="idx" class="binding-row">
      <el-input
        v-model="row.slot"
        class="binding-slot"
        placeholder="槽名（如 analyst_reports）"
        :disabled="disabled"
        @change="emitValue"
      />
      <span class="binding-arrow">→</span>
      <el-autocomplete
        v-model="row.bindingText"
        class="binding-value"
        placeholder="上游键 / 点路径 / all_upstream（多个用逗号分隔）"
        :disabled="disabled"
        :fetch-suggestions="suggest"
        @change="emitValue"
      />
      <el-button
        size="small"
        text
        type="danger"
        :disabled="disabled"
        @click="removeRow(idx)"
      >
        删除
      </el-button>
    </div>
    <el-button v-if="!disabled" size="small" text type="primary" @click="addRow">
      + 添加连线
    </el-button>
    <div v-if="upstreamKeys?.length" class="binding-hint">
      可用上游键：{{ (upstreamKeys || []).join('、') }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import type { InputBinding } from '@/api/workflows'

/**
 * 槽连线编辑器（workflow stage inputs）：slot → InputBinding。
 * binding 编辑态为逗号分隔文本；单值提交为 string，多值为 string[]，
 * 与后端 InputBinding = Union[str, List[str]] 对齐。
 */

const props = defineProps<{
  modelValue: Record<string, InputBinding>
  upstreamKeys?: string[]
  disabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: Record<string, InputBinding>): void
}>()

interface Row {
  slot: string
  bindingText: string
}

const rows = ref<Row[]>([])

const bindingToText = (binding: InputBinding): string =>
  Array.isArray(binding) ? binding.join(', ') : binding

const textToBinding = (text: string): InputBinding => {
  const parts = text.split(',').map((s) => s.trim()).filter(Boolean)
  return parts.length === 1 ? parts[0] : parts
}

const syncFromModel = () => {
  rows.value = Object.entries(props.modelValue || {}).map(([slot, binding]) => ({
    slot,
    bindingText: bindingToText(binding),
  }))
}

syncFromModel()
watch(() => props.modelValue, syncFromModel, { deep: true })

const emitValue = () => {
  const out: Record<string, InputBinding> = {}
  for (const row of rows.value) {
    const slot = row.slot.trim()
    if (!slot) continue
    const binding = textToBinding(row.bindingText)
    if (Array.isArray(binding) ? binding.length : binding) out[slot] = binding
  }
  emit('update:modelValue', out)
}

const addRow = () => {
  rows.value.push({ slot: '', bindingText: '' })
}

const removeRow = (idx: number) => {
  rows.value.splice(idx, 1)
  emitValue()
}

const suggest = (query: string, cb: (items: { value: string }[]) => void) => {
  const hits = (props.upstreamKeys || [])
    .filter((k) => k.toLowerCase().includes(query.toLowerCase()))
    .map((k) => ({ value: k }))
  cb(hits)
}
</script>

<style lang="scss" scoped>
.binding-editor {
  width: 100%;
}

.binding-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.binding-slot {
  width: 220px;
  flex-shrink: 0;
}

.binding-arrow {
  color: var(--el-text-color-secondary);
  flex-shrink: 0;
}

.binding-value {
  flex: 1;
  min-width: 0;
}

.binding-hint {
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.6;
}

@media (max-width: 768px) {
  .binding-row {
    flex-wrap: wrap;
  }

  .binding-slot {
    width: 100%;
  }
}
</style>
