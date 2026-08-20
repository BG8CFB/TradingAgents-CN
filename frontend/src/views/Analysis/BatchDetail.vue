<template>
  <div class="batch-detail">
    <!-- 顶栏 -->
    <div class="batch-header">
      <el-button text class="back-btn" @click="goBack">← 返回</el-button>
      <div class="batch-title">
        <span class="title-text">批量分析详情</span>
        <span v-if="batchId" class="batch-id" :title="batchId">{{ batchId.slice(0, 8) }}…</span>
      </div>
      <span v-if="createdAtText" class="created-at">提交时间：{{ createdAtText }}</span>
    </div>

    <!-- 加载失败 -->
    <el-alert
      v-if="loadError"
      type="error"
      :title="loadError"
      :closable="false"
      show-icon
      class="batch-alert"
    >
      <el-button size="small" @click="init">重试</el-button>
    </el-alert>

    <div v-if="!loadError" v-loading="loading" class="batch-body">
      <!-- 汇总卡 -->
      <el-card shadow="never" class="summary-card">
        <div class="summary-layout">
          <div class="summary-progress">
            <el-progress
              type="circle"
              :percentage="donePercentage"
              :width="110"
              :status="allDone ? 'success' : undefined"
            >
              <template #default>
                <div class="progress-inner">
                  <span class="progress-num">{{ doneCount }}/{{ totalCount }}</span>
                  <span class="progress-label">已完成</span>
                </div>
              </template>
            </el-progress>
          </div>
          <div class="summary-status">
            <div class="status-tags">
              <el-tag
                v-for="item in statusCountList"
                :key="item.status"
                :type="STATUS_META[item.status]?.tag ?? 'info'"
                :effect="item.count > 0 ? 'light' : 'plain'"
                class="status-tag"
              >
                {{ STATUS_META[item.status]?.label ?? item.status }}：{{ item.count }}
              </el-tag>
            </div>
            <div v-if="polling" class="polling-hint">
              <el-icon class="is-loading"><Loading /></el-icon>
              每 5 秒自动刷新，全部完成后停止
            </div>
            <div v-else-if="allDone" class="polling-hint done">全部任务已结束</div>
          </div>
          <div class="summary-actions">
            <el-button
              type="primary"
              :disabled="completedCount === 0"
              :loading="downloadingAll"
              @click="downloadAll"
            >
              全部下载{{ completedCount > 0 ? `（${completedCount}）` : '' }}
            </el-button>
          </div>
        </div>
      </el-card>

      <!-- 空状态 -->
      <el-empty v-if="!loading && totalCount === 0" description="该批次下暂无任务" />

      <!-- 任务卡片网格 -->
      <el-row v-else :gutter="16" class="task-grid">
        <el-col
          v-for="task in tasks"
          :key="task.task_id"
          :xs="24"
          :sm="12"
          :md="8"
        >
          <el-card shadow="never" class="task-card" :class="{ 'is-terminal': isTerminal(task.status) }">
            <div class="card-head">
              <div class="card-title">
                <span class="symbol" :title="symbolText(task)">{{ symbolText(task) }}</span>
                <span v-if="task.stock_name" class="stock-name" :title="task.stock_name">{{ task.stock_name }}</span>
              </div>
              <el-tag :type="STATUS_META[task.status]?.tag ?? 'info'" size="small" effect="light">
                <el-icon v-if="task.status === 'running'" class="is-loading tag-icon"><Loading /></el-icon>
                {{ STATUS_META[task.status]?.label ?? task.status }}
              </el-tag>
            </div>

            <div class="card-body">
              <!-- 进度：非终态显示步骤提示，终态显示结果摘要 -->
              <div v-if="task.status === 'unknown'" class="card-line muted">状态获取失败，等待下次刷新…</div>
              <div v-else-if="!isTerminal(task.status)" class="card-line muted">
                {{ task.current_step || '排队等待中…' }}
              </div>
              <div v-else-if="task.status === 'completed'" class="card-line muted">
                分析完成，可下载报告或查看详情
              </div>
              <div v-else-if="task.status === 'failed'" class="card-line error" :title="task.error_message || ''">
                {{ truncate(task.error_message || '分析失败', 40) }}
              </div>
              <div v-else class="card-line muted">任务已取消</div>
              <div class="card-line muted">
                <template v-if="durationText(task)">耗时 {{ durationText(task) }}</template>
                <template v-else>耗时 --</template>
              </div>
            </div>

            <div class="card-actions">
              <el-button class="card-btn" @click="goTaskDetail(task.task_id)">查看详情</el-button>
              <el-button
                class="card-btn"
                type="primary"
                :disabled="task.status !== 'completed'"
                @click="downloadOne(task)"
              >
                下载报告
              </el-button>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import { analysisApi } from '@/api/analysis'
import { reportsApi } from '@/api/reports'
import { request } from '@/api/request'

/**
 * 批次接口返回结构（后端 QueueService.get_batch，Redis hash 原样返回）：
 * { id, user, status, submitted: number, created_at: number(unix 秒), tasks: string[] }
 * tasks 仅为 task_id 字符串数组，不含各任务状态——因此轮询时对每个任务
 * 追加轻量的 getTaskStatus 查询（不拉 getTaskResult 重接口）。
 */
interface BatchInfo {
  id?: string
  status?: string
  submitted?: number
  created_at?: number | string
  tasks?: string[]
}

/** 卡片任务（字段来自 getTaskStatus 的 data，均为可选，缺失不显示） */
interface BatchTask {
  task_id: string
  status: string
  symbol?: string
  stock_symbol?: string
  stock_code?: string
  stock_name?: string
  current_step?: string
  error_message?: string
  created_at?: number | string
  completed_at?: number | string
}

const STATUS_META: Record<string, { label: string; tag: 'success' | 'danger' | 'info' | 'warning' }> = {
  queued: { label: '排队中', tag: 'info' },
  pending: { label: '等待中', tag: 'info' },
  running: { label: '分析中', tag: 'warning' },
  completed: { label: '已完成', tag: 'success' },
  failed: { label: '失败', tag: 'danger' },
  cancelled: { label: '已取消', tag: 'info' },
  // 单任务状态查询失败且无历史状态时的占位（灰色徽标），不计入终态、不停止轮询
  unknown: { label: '未知', tag: 'info' },
}

const TERMINAL_STATUSES = ['completed', 'failed', 'cancelled']
const POLL_INTERVAL_MS = 5000
/** 单轮任务状态查询的并发分批大小 */
const TASK_FETCH_CHUNK = 8

const route = useRoute()
const router = useRouter()

const loading = ref(true)
const loadError = ref('')
const batch = ref<BatchInfo | null>(null)
const tasks = ref<BatchTask[]>([])
const polling = ref(false)
const downloadingAll = ref(false)

let pollTimer: ReturnType<typeof setInterval> | null = null

const batchId = computed(() => route.params.batchId as string)
// 总数固定取批次 tasks 数组长度：单任务查询失败保留占位卡片，不会因过滤而减少
const totalCount = computed(() => batch.value?.tasks?.length ?? tasks.value.length)
const doneCount = computed(() => tasks.value.filter(t => t.status === 'completed').length)
const terminalCount = computed(() => tasks.value.filter(t => isTerminal(t.status)).length)
const completedCount = computed(() => doneCount.value)
const allDone = computed(() => totalCount.value > 0 && terminalCount.value === totalCount.value)
// 口径统一：环内数字与百分比都用 completed/总数，部分终态（失败/取消）只推进计数不推进进度环
const donePercentage = computed(() =>
  totalCount.value === 0 ? 0 : Math.min(100, Math.round((doneCount.value / totalCount.value) * 100)))

const statusCountList = computed(() =>
  Object.keys(STATUS_META).map(status => ({
    status,
    count: tasks.value.filter(t => t.status === status).length,
  })))

const createdAtText = computed(() => {
  const v = batch.value?.created_at
  if (v === undefined || v === null || v === '') return ''
  const d = new Date(typeof v === 'number' ? v * 1000 : v)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString()
})

function isTerminal(status: string): boolean {
  return TERMINAL_STATUSES.includes(status)
}

function symbolText(task: BatchTask): string {
  return task.symbol || task.stock_symbol || task.stock_code || task.task_id.slice(0, 8)
}

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max)}…` : text
}

/** 耗时：终态且 created_at/completed_at 均可解析时计算；解析失败不显示具体值 */
function durationText(task: BatchTask): string {
  if (!isTerminal(task.status) || !task.created_at || !task.completed_at) return ''
  const start = toDate(task.created_at)
  const end = toDate(task.completed_at)
  if (!start || !end || end <= start) return ''
  const sec = Math.round((end.getTime() - start.getTime()) / 1000)
  if (sec < 60) return `${sec}s`
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min}m${sec % 60}s`
  return `${Math.floor(min / 60)}h${min % 60}m`
}

function toDate(v: number | string): Date | null {
  // 兼容 unix 秒（number / 数字字符串）与 ISO 字符串两种真实返回
  const d = typeof v === 'number' ? new Date(v < 1e12 ? v * 1000 : v) : new Date(v)
  return Number.isNaN(d.getTime()) ? null : d
}

async function fetchBatch(): Promise<BatchInfo> {
  // 后端该端点直接返回批次对象（无 success/data 包装），响应拦截器原样透传
  return (await request.get(`/api/analysis/batches/${encodeURIComponent(batchId.value)}`)) as BatchInfo
}

/** 各任务最近一次成功获取的状态：单次查询失败时用于占位兜底 */
const lastKnownStatus = new Map<string, string>()

async function fetchTask(taskId: string): Promise<BatchTask> {
  try {
    const res = await analysisApi.getTaskStatus(taskId)
    const d = (res.data ?? {}) as Record<string, unknown>
    const status = String(d.status ?? 'queued')
    lastKnownStatus.set(taskId, status)
    return {
      task_id: taskId,
      status,
      symbol: d.symbol as string | undefined,
      stock_symbol: d.stock_symbol as string | undefined,
      stock_code: d.stock_code as string | undefined,
      stock_name: (d.stock_name as string | undefined) || (d.name as string | undefined),
      current_step: (d.current_step as string | undefined) || (d.current_step_name as string | undefined),
      error_message: d.error_message as string | undefined,
      created_at: (d.created_at as number | string | undefined),
      completed_at: (d.completed_at as number | string | undefined),
    }
  } catch {
    // 单个任务状态查询失败不阻断整页：保留占位卡片，沿用上次已知状态（无则 unknown，不计终态）
    return { task_id: taskId, status: lastKnownStatus.get(taskId) ?? 'unknown' }
  }
}

/** 轮次序号：batchId 变化重置时递增，使仍在途的旧轮次结果作废 */
let loadSeq = 0
/** 当前轮次是否已有一次 loadOnce 在途（防重复触发）；null 表示空闲 */
let loadInFlightSeq: number | null = null

async function loadOnce(): Promise<boolean> {
  // 同一轮次进行中：重复触发（定时器/手动）直接返回，不发起新请求
  if (loadInFlightSeq === loadSeq) return false
  loadInFlightSeq = loadSeq
  const mySeq = loadSeq
  try {
    const info = await fetchBatch()
    if (mySeq !== loadSeq) return false // 轮次已过期，丢弃结果
    batch.value = info
    const ids = info.tasks ?? []
    const list: BatchTask[] = []
    // 分批并行（每批 8 个），避免大批次一次性打满后端
    for (let i = 0; i < ids.length; i += TASK_FETCH_CHUNK) {
      if (mySeq !== loadSeq) return false
      const chunk = ids.slice(i, i + TASK_FETCH_CHUNK)
      list.push(...(await Promise.all(chunk.map(fetchTask))))
    }
    if (mySeq !== loadSeq) return false
    // fetchTask 失败也返回占位（unknown/上次状态），因此 list 与 ids 一一对应
    tasks.value = list
    return allDone.value
  } finally {
    if (loadInFlightSeq === mySeq) loadInFlightSeq = null
  }
}

function stopPolling() {
  polling.value = false
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function init() {
  // 递增轮次使旧轮次在途请求作废，并清理上一批次的状态缓存
  loadSeq += 1
  lastKnownStatus.clear()
  loading.value = true
  loadError.value = ''
  stopPolling()
  try {
    const done = await loadOnce()
    if (!done) {
      polling.value = true
      pollTimer = setInterval(() => {
        void loadOnce().then(doneNow => {
          if (doneNow) stopPolling()
        })
      }, POLL_INTERVAL_MS)
    }
  } catch (err: unknown) {
    loadError.value = err instanceof Error ? err.message : '批次信息加载失败'
  } finally {
    loading.value = false
  }
}

function goBack() {
  router.back()
}

function goTaskDetail(taskId: string) {
  void router.push({ name: 'AnalysisTaskDetail', params: { taskId } })
}

/** 单任务下载（blob → 触发浏览器保存），逻辑与 TaskReportPanel.download 一致 */
async function downloadReport(task: BatchTask, format = 'markdown'): Promise<void> {
  const blob = (await reportsApi.download(task.task_id, format)) as Blob
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  const dateStr = new Date().toISOString().slice(0, 10)
  a.download = `${symbolText(task)}_分析报告_${dateStr}.md`
  document.body.appendChild(a)
  a.click()
  window.URL.revokeObjectURL(url)
  document.body.removeChild(a)
}

async function downloadOne(task: BatchTask) {
  if (task.status !== 'completed') return
  try {
    await downloadReport(task)
    ElMessage.success(`已下载 ${symbolText(task)} 的分析报告`)
  } catch (err: unknown) {
    console.error('下载报告出错:', err)
    ElMessage.error(`下载报告失败: ${symbolText(task)}`)
  }
}

/** 全部下载：completed 任务串行下载，避免并发请求压垮报告生成 */
async function downloadAll() {
  if (downloadingAll.value) return
  const targets = tasks.value.filter(t => t.status === 'completed')
  if (targets.length === 0) {
    ElMessage.warning('暂无已完成的任务')
    return
  }
  downloadingAll.value = true
  let ok = 0
  try {
    for (const task of targets) {
      try {
        await downloadReport(task)
        ok += 1
      } catch (err: unknown) {
        console.error('下载报告出错:', err, task.task_id)
      }
    }
    if (ok === targets.length) {
      ElMessage.success(`已下载全部 ${ok} 份报告`)
    } else {
      ElMessage.warning(`已下载 ${ok}/${targets.length} 份报告，失败任务请单独重试`)
    }
  } finally {
    downloadingAll.value = false
  }
}

onMounted(() => {
  void init()
})

// 深浅路由复用：batchId 变化时重置轮询并重新加载
watch(batchId, (val, old) => {
  if (val && val !== old) void init()
})

onBeforeUnmount(stopPolling)
</script>

<style scoped>
.batch-detail {
  padding: 16px;
}

.batch-header {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.back-btn {
  padding: 4px 8px;
}

.batch-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}

.title-text {
  font-size: 18px;
  font-weight: 600;
}

.batch-id {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  font-family: monospace;
}

.created-at {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.batch-alert {
  margin-bottom: 16px;
}

.summary-card {
  margin-bottom: 16px;
}

.summary-layout {
  display: flex;
  align-items: center;
  gap: 32px;
  flex-wrap: wrap;
}

.progress-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  line-height: 1.3;
}

.progress-num {
  font-size: 18px;
  font-weight: 600;
}

.progress-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.summary-status {
  flex: 1;
  min-width: 220px;
}

.status-tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.status-tag {
  font-variant-numeric: tabular-nums;
}

.polling-hint {
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.polling-hint.done {
  color: var(--el-color-success);
}

.summary-actions {
  display: flex;
  align-items: center;
}

.task-grid {
  row-gap: 16px;
}

.task-card {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.task-card :deep(.el-card__body) {
  display: flex;
  flex-direction: column;
  flex: 1;
  gap: 12px;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.card-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}

.symbol {
  font-size: 16px;
  font-weight: 600;
  white-space: nowrap;
}

.stock-name {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tag-icon {
  margin-right: 2px;
  vertical-align: -2px;
}

.card-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-height: 44px;
}

.card-line {
  font-size: 13px;
  line-height: 1.5;
}

.card-line.muted {
  color: var(--el-text-color-secondary);
}

.card-line.error {
  color: var(--el-color-danger);
}

.card-actions {
  display: flex;
  gap: 8px;
}

/* 两个等宽按钮，窄屏不换行不溢出 */
.card-btn {
  flex: 1 1 0;
  min-width: 0;
  margin-left: 0 !important;
}

.card-actions .card-btn + .card-btn {
  margin-left: 0 !important;
}
</style>
