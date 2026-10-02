<template>
  <div class="workflow-selector">
    <el-select
      :model-value="modelValue"
      :loading="loading"
      placeholder="选择分析工作流"
      size="large"
      style="width: 100%"
      @update:model-value="onSelect"
    >
      <el-option
        v-for="item in selectable"
        :key="item.slug"
        :value="item.slug"
        :label="item.name || item.slug"
      >
        <div class="wf-option">
          <span class="wf-option__name">
            {{ item.name || item.slug }}
            <el-tag v-if="item.is_default" size="small" type="success" effect="plain">默认</el-tag>
          </span>
          <span class="wf-option__meta">{{ item.stages.length }} 个阶段 · {{ item.slug }}</span>
        </div>
      </el-option>
    </el-select>
    <div v-if="currentDescription" class="wf-desc">{{ currentDescription }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { workflowApi, type WorkflowListItem } from '@/api/workflows'

/** 分析页工作流选择器：仅列出 enabled 且校验通过的工作流；缺省选中默认工作流 */

const props = defineProps<{
  modelValue: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', slug: string): void
}>()

const loading = ref(false)
const items = ref<WorkflowListItem[]>([])

const selectable = computed(() => items.value.filter((i) => i.enabled && i.valid))

const currentDescription = computed(() => {
  const current = selectable.value.find((i) => i.slug === props.modelValue)
  return current?.description || ''
})

const onSelect = (slug: string) => {
  emit('update:modelValue', slug)
}

onMounted(async () => {
  loading.value = true
  try {
    const res = await workflowApi.list()
    items.value = res.data?.workflows || []
    // 未选中时回落默认工作流；默认缺失（异常配置）时取第一个可选项
    if (!props.modelValue) {
      const fallback =
        items.value.find((i) => i.is_default && i.enabled && i.valid) ||
        selectable.value[0]
      if (fallback) emit('update:modelValue', fallback.slug)
    }
  } catch (error) {
    console.error('获取工作流列表失败', error)
    ElMessage.error('获取工作流列表失败')
  } finally {
    loading.value = false
  }
})
</script>

<style lang="scss" scoped>
.workflow-selector {
  width: 100%;
}

.wf-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.wf-option__name {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wf-option__meta {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  flex-shrink: 0;
}

.wf-desc {
  margin-top: 6px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.5;
}
</style>
