<template>
  <div class="live-report-panel">
    <template v-if="store.reports.length > 0">
      <el-tabs v-model="activeReportKey" class="report-tabs">
        <el-tab-pane
          v-for="r in store.reports"
          :key="r.key"
          :name="r.key"
          :label="r.title"
          lazy
        >
          <!-- eslint-disable-next-line vue/no-v-html -- DOMPurify 消毒后的 markdown HTML（memoize 缓存） -->
          <div class="report-body md-bubble chat-md" v-html="cachedMarkdown(r.content)"></div>
        </el-tab-pane>
      </el-tabs>
    </template>
    <el-empty
      v-else
      :description="emptyText"
      :image-size="60"
      class="report-empty"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useAnalysisProcessStore } from '@/stores/analysisProcess'
import { cachedMarkdown } from './ChatTimeline/markdownCache'
import './ChatTimeline/md-styles.css'

const store = useAnalysisProcessStore()

const activeReportKey = ref('')

// 新报告到达且当前无选中时自动激活第一个；用户切换后跟随保持（失效时回落第一项）
watch(
  () => store.reports.map(r => r.key),
  (keys) => {
    if (keys.length === 0) {
      activeReportKey.value = ''
      return
    }
    if (!keys.includes(activeReportKey.value)) activeReportKey.value = keys[0]
  },
  { immediate: true },
)

const emptyText = computed(() =>
  store.mode === 'replay'
    ? '该任务过程未记录实时报告（旧任务或无 report_ready 事件）'
    : '进行中暂无已完成报告，完成后见分析报告',
)
</script>

<style scoped>
.live-report-panel {
  height: 100%;
  min-height: 240px;
  display: flex;
  flex-direction: column;
}

.report-tabs {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.report-tabs :deep(.el-tabs__content) {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.report-body {
  padding: 8px 4px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--el-text-color-primary);
  word-break: break-word;
}

.report-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
}
</style>
