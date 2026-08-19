<template>
  <el-dialog v-model="visible" title="报告详情" width="70%">
    <template v-if="sections && sections.length > 0">
      <el-tabs v-model="active">
        <el-tab-pane v-for="(sec, idx) in sections" :key="sec.key || idx" :label="sec.title" :name="String(idx)">
          <div v-if="typeof sec.content === 'string'" class="markdown-content" v-html="renderMarkdown(sec.content)"></div>
          <div v-else class="json-content"><pre>{{ JSON.stringify(sec.content, null, 2) }}</pre></div>
        </el-tab-pane>
      </el-tabs>
    </template>
    <template v-else>
      <el-empty description="暂无内容" />
    </template>

    <!-- 内嵌分析过程面板（回放模式） -->
    <div v-if="showProcess && taskId" class="process-section">
      <el-divider content-position="left">分析过程（回放）</el-divider>
      <ProcessPanel :task-id="taskId" replay class="embedded-process-panel" />
    </div>

    <template #footer>
      <el-button v-if="taskId" @click="showProcess = !showProcess">
        {{ showProcess ? '收起过程' : '查看过程' }}
      </el-button>
      <el-button @click="emit('close')">关闭</el-button>
    </template>
  </el-dialog>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { renderMarkdown } from '@/utils/markdown'
import ProcessPanel from '@/components/Analysis/ProcessPanel.vue'
const props = defineProps<{ modelValue: boolean; sections: Array<{ key?: string; title: string; content: string }>; taskId?: string }>()
const emit = defineEmits(['update:modelValue','close'])
const visible = computed({ get: () => props.modelValue, set: (v: boolean) => emit('update:modelValue', v) })
const active = ref('0')
const showProcess = ref(false)
</script>
<style scoped>
.process-section { margin-top: 8px; }
.embedded-process-panel { height: 480px; }
</style>
