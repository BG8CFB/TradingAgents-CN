<template>
  <div class="task-detail">
    <!-- 顶栏 -->
    <div class="task-header">
      <el-button text class="back-btn" @click="goBack">← 返回</el-button>

      <div class="task-title">
        <span class="symbol" :title="symbolText">{{ symbolText }}</span>
        <span v-if="stockName" class="stock-name" :title="stockName">{{ stockName }}</span>
        <!-- 状态未加载完成时显示占位，避免闪现"未知" -->
        <el-skeleton-item v-if="!taskStatus" variant="text" class="status-skeleton" />
        <el-tag v-else :type="statusTagType" size="small">{{ statusLabel }}</el-tag>
      </div>

      <span class="elapsed" :title="'起算时间：' + startedAtText">已耗时 {{ elapsedText }}</span>

      <div class="actions">
        <el-button
          v-if="isActive"
          type="danger"
          plain
          :loading="cancelling"
          @click="handleCancel"
        >
          取消任务
        </el-button>
        <el-button v-if="taskStatus === 'completed'" disabled>下载报告</el-button>
        <el-button
          v-if="taskStatus === 'cancelled'"
          type="primary"
          plain
          @click="restartAnalysis"
        >
          重新发起分析
        </el-button>
      </div>
    </div>

    <!-- 错误 / 取消提示 -->
    <el-alert
      v-if="taskStatus === 'failed'"
      type="error"
      :title="errorMessage || '分析过程中发生错误'"
      :closable="false"
      show-icon
      class="task-alert"
    />
    <el-alert
      v-else-if="taskStatus === 'cancelled'"
      type="info"
      title="任务已取消"
      :closable="false"
      show-icon
      class="task-alert"
    />

    <!-- WS 断连提示（live 且曾连上后断开；进度由 5s 轮询兜底） -->
    <el-alert
      v-if="wsDisconnected"
      type="warning"
      title="连接中断，重连中…"
      :closable="false"
      show-icon
      class="task-alert ws-alert"
    />

    <!-- 加载失败 -->
    <el-alert
      v-if="loadError"
      type="error"
      :title="loadError"
      :closable="false"
      show-icon
      class="task-alert"
    >
      <el-button size="small" @click="init">重试</el-button>
    </el-alert>

    <!-- 三区主体 -->
    <el-container v-if="!loadError" v-loading="loading" class="task-body">
      <el-aside width="280px" class="task-aside">
        <TaskDetailSidebar :overview="overview" :loading="loading" />
      </el-aside>

      <el-main class="task-main">
        <!-- 阶段化进度 -->
        <el-card shadow="never" class="progress-card">
          <div class="progress-head">
            <span class="step-name">{{ currentStepName || defaultStepName }}</span>
            <span class="progress-percent">{{ progressPercentage }}%</span>
          </div>
          <el-progress
            :percentage="progressPercentage"
            :status="progressStatus"
            :stroke-width="10"
          />
          <div v-if="statusMessage" class="status-message">{{ statusMessage }}</div>
        </el-card>

        <!-- 实时过程 / 分析报告 -->
        <el-card shadow="never" class="tabs-card">
          <el-tabs v-model="activeTab">
            <el-tab-pane label="实时过程" name="process">
              <!-- live：store 已由 loadLatestAndConnect 启动（WS+历史回填），不传 taskId 避免面板重复 start -->
              <ProcessPanel v-if="isActive" />
              <!-- 终态：store 已由 loadReplay 填充，事件定格展示 -->
              <ProcessPanel v-else replay />
            </el-tab-pane>
            <el-tab-pane label="分析报告" name="report">
              <!-- Task 7: 报告面板挂载点 -->
              <div class="tab-placeholder" :data-mount="`report:${taskId}`">
                {{ taskStatus === 'completed' ? '报告待接入' : '任务完成后在此展示报告' }}
              </div>
            </el-tab-pane>
          </el-tabs>
        </el-card>
      </el-main>
    </el-container>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { analysisApi, type TaskOverview } from '@/api/analysis'
import TaskDetailSidebar from '@/components/Analysis/TaskDetailSidebar.vue'
import ProcessPanel from '@/components/Analysis/ProcessPanel.vue'
import { useAnalysisProcessStore } from '@/stores/analysisProcess'

const processStore = useAnalysisProcessStore()

const route = useRoute()
const router = useRouter()
const taskId = route.params.taskId as string

const overview = ref<TaskOverview | null>(null)
const loading = ref(true)
const loadError = ref('')
const taskStatus = ref('')
const activeTab = ref<'process' | 'report'>('process')
const errorMessage = ref('')

// 进度（来自 getTaskStatus：progress_percentage / current_step_name / message）
const progressPercentage = ref(0)
const currentStepName = ref('')
const statusMessage = ref('')

// 轮询与计时
let pollTimer: ReturnType<typeof setInterval> | null = null
let tickTimer: ReturnType<typeof setInterval> | null = null
let pollSeq = 0

const cancelling = ref(false)
const nowMs = ref(Date.now())

const ACTIVE_STATUSES = ['pending', 'processing', 'running']
const isActive = computed(() => ACTIVE_STATUSES.includes(taskStatus.value))

const STATUS_META: Record<string, { label: string; tag: 'success' | 'danger' | 'info' | 'warning' | 'primary' }> = {
  pending: { label: '待处理', tag: 'warning' },
  processing: { label: '处理中', tag: 'warning' },
  running: { label: '运行中', tag: 'primary' },
  completed: { label: '已完成', tag: 'success' },
  failed: { label: '失败', tag: 'danger' },
  cancelled: { label: '已取消', tag: 'info' },
}
const statusLabel = computed(() => STATUS_META[taskStatus.value]?.label ?? (taskStatus.value || '未知'))
const statusTagType = computed(() => STATUS_META[taskStatus.value]?.tag ?? 'warning')

const symbolText = computed(() => overview.value?.task.symbol || taskId)
const stockName = computed(() => overview.value?.stock_info?.name || '')

// WS 断连提示：仅 live 模式且"曾连上后断开"时显示（避免首连阶段闪现），进度由 5s 轮询兜底
const wsEverConnected = ref(false)
watch(() => processStore.connected, (c) => {
  if (c) wsEverConnected.value = true
})
watch(() => processStore.mode, () => {
  // 切换模式（如 stop 后 idle）重置，避免下次 live 复用旧标记
  if (processStore.mode !== 'live') wsEverConnected.value = false
})
const wsDisconnected = computed(() =>
  processStore.mode === 'live' && wsEverConnected.value && !processStore.connected)

function parseTs(v?: string | null): number | null {
  if (!v) return null
  // 兼容 "YYYY-MM-DD HH:mm:ss"（空格分隔无时区）：统一成 ISO 的 "T" 分隔，规避各浏览器 Date.parse 差异
  const t = Date.parse(v.replace(' ', 'T'))
  return Number.isNaN(t) ? null : t
}
const startedAtMs = computed(() => parseTs(overview.value?.task.started_at))
const completedAtMs = computed(() => parseTs(overview.value?.task.completed_at))
// 后端可能不带 completed_at（如 failed/cancelled），进入终态时本地补记时间戳用于耗时定格
const finalizedAtMs = ref<number | null>(null)
watch(taskStatus, (s) => {
  if (s && !ACTIVE_STATUSES.includes(s) && finalizedAtMs.value === null) {
    finalizedAtMs.value = Date.now()
  }
})
const startedAtText = computed(() =>
  startedAtMs.value ? new Date(startedAtMs.value).toLocaleString() : '未开始'
)

const elapsedText = computed(() => {
  const start = startedAtMs.value
  if (start === null) return '—'
  // 终态定格在完成时刻（缺 completed_at 时用本地补记的终态时间兜底）；进行中随 tick 响应更新
  const end = isActive.value
    ? nowMs.value
    : (completedAtMs.value ?? finalizedAtMs.value ?? nowMs.value)
  const sec = Math.max(0, Math.floor((end - start) / 1000))
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = sec % 60
  const mm = String(m).padStart(2, '0')
  const ss = String(s).padStart(2, '0')
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`
})

const progressStatus = computed(() => {
  if (taskStatus.value === 'completed') return 'success'
  if (taskStatus.value === 'failed') return 'exception'
  return undefined
})
const defaultStepName = computed(() => {
  if (taskStatus.value === 'completed') return '分析完成'
  if (taskStatus.value === 'failed') return '分析失败'
  if (taskStatus.value === 'cancelled') return '任务已取消'
  return '等待任务启动…'
})

function stopTimers() {
  // 递增序号使在途的 getTaskStatus 回包作废，防止取消/终止后旧响应把状态翻回 processing
  pollSeq++
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  if (tickTimer) {
    clearInterval(tickTimer)
    tickTimer = null
  }
}

function startTick() {
  if (tickTimer) return
  tickTimer = setInterval(() => {
    nowMs.value = Date.now()
  }, 1000)
}

async function loadOverview() {
  loadError.value = ''
  loading.value = true
  try {
    const res = await analysisApi.getTaskOverview(taskId)
    overview.value = res.data
    if (res.data.task.status) taskStatus.value = res.data.task.status
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    loadError.value = `任务信息加载失败：${msg}`
  } finally {
    loading.value = false
  }
}

// 轮询状态兜底（竞态保护：序号过期响应直接丢弃）
function startPolling() {
  if (pollTimer) return
  pollSeq = 0
  pollTimer = setInterval(async () => {
    try {
      const seq = ++pollSeq
      const res = await analysisApi.getTaskStatus(taskId)
      if (seq !== pollSeq) return
      const data = res.data
      if (!data?.status) return
      taskStatus.value = data.status
      const pct = Number(data.progress_percentage ?? data.progress ?? 0)
      progressPercentage.value = Math.min(100, Math.max(0, pct || 0))
      // 以最新回包整体覆盖，避免上一轮残留的步骤名/状态文案在字段缺失时悬挂
      currentStepName.value = data.current_step_name || ''
      statusMessage.value = data.message || ''

      if (data.status === 'completed') {
        progressPercentage.value = 100
        stopTimers()
        processStore.stop() // 断开 WS，已收到的事件保留（切回过程 tab 仍可查看）
        activeTab.value = 'report'
      } else if (data.status === 'failed') {
        errorMessage.value = data.error_message || ''
        stopTimers()
        processStore.stop()
      } else if (data.status === 'cancelled') {
        stopTimers()
        processStore.stop() // 事件流定格
      }
    } catch {
      // 单次轮询失败不打断，下一周期重试
    }
  }, 5000)
}

async function init() {
  await loadOverview()
  if (loadError.value) return
  if (isActive.value) {
    startTick()
    startPolling()
    // running 主入口：连 WS + desc 首拉回填历史（不阻塞首屏，面板渲染 store 响应式更新）
    void processStore.loadLatestAndConnect(taskId)
  } else {
    // 终态（completed/failed/cancelled）：纯回放，事件定格展示
    void processStore.loadReplay(taskId)
    if (taskStatus.value === 'completed') {
      activeTab.value = 'report'
    }
  }
}

function goBack() {
  router.back()
}

async function handleCancel() {
  try {
    await ElMessageBox.confirm('确定取消该分析任务？取消后无法恢复。', '取消任务', {
      type: 'warning',
      confirmButtonText: '确定取消',
      cancelButtonText: '再想想',
    })
  } catch {
    return // 用户放弃
  }
  cancelling.value = true
  try {
    const res = await analysisApi.cancelTask(taskId)
    if (res.success) {
      ElMessage.success('任务已取消')
      taskStatus.value = 'cancelled'
      stopTimers()
      processStore.stop() // 事件流定格
      await loadOverview()
    } else {
      ElMessage.error(res.message || '取消失败，请重试')
    }
  } catch (e: unknown) {
    ElMessage.error(e instanceof Error ? e.message : '取消失败，请重试')
  } finally {
    cancelling.value = false
  }
}

function restartAnalysis() {
  router.push('/analysis/single')
}

onMounted(init)
onBeforeUnmount(() => {
  stopTimers()
  processStore.stop()
})
</script>

<style scoped>
.task-detail {
  padding: 16px;
  height: 100%;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
}

/* ── 顶栏 ── */
.task-header {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.back-btn {
  padding: 4px 8px;
}

.task-title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.symbol {
  font-size: 18px;
  font-weight: 700;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stock-name {
  color: var(--el-text-color-secondary);
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-skeleton {
  width: 48px;
  height: 22px;
}

.elapsed {
  color: var(--el-text-color-secondary);
  font-variant-numeric: tabular-nums;
}

/* 操作组统一右对齐、等高 */
.actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
}

.actions .el-button {
  height: 32px;
  margin: 0;
}

.task-alert {
  margin-top: 12px;
}

/* ── 主体 ── */
.task-body {
  flex: 1;
  min-height: 0;
  margin-top: 12px;
}

.task-aside {
  min-height: 0;
  overflow-y: auto;
}

.task-main {
  padding: 0 0 0 12px;
  min-height: 0;
  overflow-y: auto;
}

.progress-card {
  margin-bottom: 12px;
}

.progress-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  gap: 12px;
}

.step-name {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.progress-percent {
  color: var(--el-text-color-secondary);
  font-variant-numeric: tabular-nums;
}

.status-message {
  margin-top: 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  word-break: break-all;
}

.tabs-card {
  min-height: 240px;
}

.tab-placeholder {
  padding: 32px 0;
  text-align: center;
  color: var(--el-text-color-placeholder);
}

/* ── 窄屏：<1200px 左栏折叠为顶部摘要 ── */
@media (max-width: 1199px) {
  .task-body {
    flex-direction: column;
  }

  .task-aside {
    width: 100% !important;
    overflow: visible;
  }

  /* 侧栏两卡片并排成摘要行 */
  .task-aside :deep(.task-sidebar) {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 12px;
  }

  .task-aside :deep(.sidebar-card) {
    margin-bottom: 0;
  }

  .task-main {
    padding-left: 0;
    margin-top: 12px;
  }
}
</style>
