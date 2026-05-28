<template>
  <div class="sync-manager">
    <!-- 同步操作面板 -->
    <div class="panel sync-ops">
      <div class="panel-header">
        <div class="panel-title">
          <div class="title-icon ops"><el-icon :size="18"><Promotion /></el-icon></div>
          数据同步调度器
        </div>
      </div>
      <div class="panel-body">
        <p class="ops-description">
          手动触发底层数据域的同步任务。当调度策略开启时，系统会自动执行增量更新；如果历史数据缺失或结构变更，请执行全量同步。
        </p>
        <!-- 操作行 -->
        <div class="ops-row">
          <div class="ops-field">
            <label class="ops-label">选择数据域 (Domain)</label>
            <el-select v-model="syncDomain" class="ops-select" effect="dark">
              <el-option label="所有数据域 (顺序执行)" value="__all__" />
              <el-option v-for="d in validDomains" :key="d.value" :label="d.label" :value="d.value" />
            </el-select>
          </div>
          <div class="ops-field">
            <label class="ops-label">执行模式 (Mode)</label>
            <div class="mode-switch">
              <el-tooltip content="仅拉取自上次成功同步以来的新数据，速度极快，适合日常调度" placement="top">
                <div class="mode-option" :class="{ active: syncMode === 'incremental' }" @click="syncMode = 'incremental'">
                  <el-icon><Timer /></el-icon> 增量更新
                </div>
              </el-tooltip>
              <el-tooltip content="清空当前域的本地存量并重新从远端拉取所有历史数据，耗时较长" placement="top">
                <div class="mode-option" :class="{ active: syncMode === 'full' }" @click="syncMode = 'full'">
                  <el-icon><CopyDocument /></el-icon> 全量覆盖
                </div>
              </el-tooltip>
            </div>
          </div>
          <div class="ops-field action">
            <el-button type="primary" :loading="syncing" @click="handleSync" round size="large" class="sync-btn">
              <el-icon><VideoPlay /></el-icon>
              {{ syncing ? '任务执行中...' : '立即下发同步指令' }}
            </el-button>
          </div>
        </div>

        <!-- 快捷操作 -->
        <div class="quick-ops">
          <el-button plain round @click="handleSyncAll" :loading="syncingAll" type="danger">
            <el-icon><Warning /></el-icon>
            强制全局初始化
          </el-button>
          <span class="quick-hint">危险操作：将清空当前市场所有数据并重新拉取（通常用于首次部署）</span>
        </div>
      </div>
    </div>

    <!-- 同步进度提示 -->
    <div v-if="syncProgress.show" class="sync-progress panel">
      <div class="progress-body">
        <el-icon :size="16" class="spin"><Loading /></el-icon>
        <span>{{ syncProgress.text }}</span>
        <el-tag size="small" type="info">{{ syncProgress.done }}/{{ syncProgress.total }}</el-tag>
      </div>
    </div>

    <!-- 双列：同步记录 + 事件日志 -->
    <div class="sync-columns">
      <!-- 同步记录 -->
      <div class="panel">
        <div class="panel-header">
          <div class="panel-title">
            <div class="title-icon status"><el-icon :size="18"><Clock /></el-icon></div>
            同步记录
          </div>
          <el-button size="small" :loading="loadingStatus" @click="loadStatus" link type="primary">
            <el-icon><Refresh /></el-icon>
          </el-button>
        </div>
        <div class="panel-body">
          <div v-if="checkpoints.length > 0" class="checkpoint-list">
            <div v-for="cp in checkpoints" :key="`${cp.domain}-${cp.source}`" class="checkpoint-item">
              <div class="cp-left">
                <div class="cp-dot" :class="cp.status === 'success' ? 'success' : 'error'"></div>
                <div class="cp-info">
                  <div class="cp-domain">{{ domainLabel(cp.domain) }}</div>
                  <div class="cp-source">{{ cp.source?.toUpperCase() || '--' }}</div>
                </div>
              </div>
              <div class="cp-right">
                <div class="cp-meta">
                  <span class="cp-date">{{ cp.last_sync_date || '--' }}</span>
                  <span v-if="cp.record_count" class="cp-records">{{ cp.record_count.toLocaleString() }} 条</span>
                  <span v-if="cp.duration_ms" class="cp-duration">{{ cp.duration_ms }}ms</span>
                </div>
                <el-tag :type="cp.status === 'success' ? 'success' : 'danger'" size="small" round effect="light">
                  {{ cp.status === 'success' ? '成功' : '失败' }}
                </el-tag>
              </div>
            </div>
          </div>
          <div v-else class="empty-compact">
            <p>暂无同步记录</p>
          </div>

          <div class="pagination-wrap" v-if="totalCheckpoints > 20">
            <el-pagination
              v-model:current-page="page"
              :page-size="20"
              :total="totalCheckpoints"
              layout="total, prev, pager, next"
              small
              @current-change="loadStatus"
            />
          </div>
        </div>
      </div>

      <!-- 事件日志 -->
      <div class="panel">
        <div class="panel-header">
          <div class="panel-title">
            <div class="title-icon event"><el-icon :size="18"><Document /></el-icon></div>
            事件日志
          </div>
          <el-button size="small" :loading="loadingEvents" @click="loadEvents" link type="primary">
            <el-icon><Refresh /></el-icon>
          </el-button>
        </div>
        <div class="panel-body">
          <div v-if="events.length > 0" class="event-list">
            <div v-for="ev in events" :key="ev.updated_at + ev.domain" class="event-item">
              <div class="event-left">
                <div class="event-dot" :class="eventTypeClass(ev.event_type)"></div>
                <div class="event-info">
                  <div class="event-type-row">
                    <span class="event-type">{{ eventTypeLabel(ev.event_type) }}</span>
                    <span class="event-domain">{{ domainLabel(ev.domain) }}</span>
                  </div>
                  <div class="event-detail">
                    <span v-if="ev.source">{{ ev.source.toUpperCase() }}</span>
                    <span v-if="ev.record_count">{{ ev.record_count }} 条</span>
                    <span v-if="ev.fallback_from" class="fallback">从 {{ ev.fallback_from }} 降级</span>
                  </div>
                  <div v-if="ev.error_message" class="event-error">{{ ev.error_message }}</div>
                </div>
              </div>
              <div class="event-time">{{ formatTime(ev.updated_at) }}</div>
            </div>
          </div>
          <div v-else class="empty-compact">
            <p>暂无同步事件</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Clock, Document, Promotion, Loading, Timer, CopyDocument, VideoPlay, Warning } from '@element-plus/icons-vue'
import {
  triggerSync, getSyncStatus, getSyncEvents, getSourceConfig,
  type SyncCheckpoint, type SyncEvent,
  DOMAIN_LABELS,
} from '@/api/marketData'
import type { MarketCode } from '@/api/marketData'

const props = defineProps<{ market: MarketCode }>()

const availableDomains = ref<string[]>([])

async function loadDomains() {
  try {
    const res = await getSourceConfig(props.market)
    if (res.success && res.data?.capability_matrix) {
      availableDomains.value = Object.keys(res.data.capability_matrix)
    }
  } catch { /* 静默 */ }
}

const validDomains = computed(() =>
  availableDomains.value.map(d => ({ value: d, label: DOMAIN_LABELS[d] || d }))
)

function domainLabel(domain: string) { return DOMAIN_LABELS[domain] || domain }
function formatTime(iso: string) {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function eventTypeClass(type: string) {
  if (type === 'SYNC_SUCCESS') return 'success'
  if (type === 'SYNC_FAILED') return 'error'
  if (type === 'SOURCE_FALLBACK') return 'warning'
  if (type === 'CIRCUIT_OPEN') return 'error'
  if (type === 'CIRCUIT_CLOSE') return 'success'
  return 'info'
}

function eventTypeLabel(type: string) {
  const map: Record<string, string> = {
    SOURCE_FALLBACK: '数据源降级',
    CIRCUIT_OPEN: '熔断打开',
    CIRCUIT_CLOSE: '熔断恢复',
    SYNC_FAILED: '同步失败',
    SYNC_SUCCESS: '同步成功',
  }
  return map[type] || type
}

const syncDomain = ref<string>('__all__')
const syncMode = ref<'incremental' | 'full'>('incremental')
const syncing = ref(false)
const syncingAll = ref(false)

const syncProgress = ref({ show: false, text: '', done: 0, total: 0 })

const loadingStatus = ref(false)
const checkpoints = ref<SyncCheckpoint[]>([])
const page = ref(1)
const totalCheckpoints = ref(0)

const loadingEvents = ref(false)
const events = ref<SyncEvent[]>([])

async function handleSync() {
  syncing.value = true
  try {
    if (syncDomain.value === '__all__') {
      await doSyncAll(syncMode.value)
    } else {
      await triggerSync(props.market, syncDomain.value, syncMode.value)
      ElMessage.success(`${domainLabel(syncDomain.value)} 同步已触发`)
      loadStatus()
      loadEvents()
    }
  } catch {
    ElMessage.error('触发同步失败')
  } finally {
    syncing.value = false
  }
}

async function handleSyncAll() {
  syncingAll.value = true
  try {
    await doSyncAll('full')
  } finally {
    syncingAll.value = false
  }
}

async function doSyncAll(mode: 'incremental' | 'full') {
  const domains = validDomains.value.map(d => d.value)
  syncProgress.value = { show: true, text: '正在同步...', done: 0, total: domains.length }

  let successCount = 0
  for (let i = 0; i < domains.length; i++) {
    syncProgress.value.text = `正在同步 ${domainLabel(domains[i])}...`
    syncProgress.value.done = i
    try {
      await triggerSync(props.market, domains[i], mode)
      successCount++
    } catch { /* 继续下一个 */ }
  }

  syncProgress.value.show = false
  ElMessage.success(`${successCount}/${domains.length} 个数据域同步已触发`)
  loadStatus()
  loadEvents()
}

async function loadStatus() {
  loadingStatus.value = true
  try {
    const res = await getSyncStatus(props.market, { page: page.value, page_size: 20 })
    if (res.success) {
      checkpoints.value = res.data?.items || []
      totalCheckpoints.value = res.data?.total || 0
    }
  } catch { /* 静默 */ } finally {
    loadingStatus.value = false
  }
}

async function loadEvents() {
  loadingEvents.value = true
  try {
    const res = await getSyncEvents(props.market, { page: 1, page_size: 20 })
    if (res.success) {
      events.value = res.data?.items || []
    }
  } catch { /* 静默 */ } finally {
    loadingEvents.value = false
  }
}

watch(() => props.market, () => {
  checkpoints.value = []
  events.value = []
  loadDomains()
  loadStatus()
  loadEvents()
})

onMounted(() => { loadDomains(); loadStatus(); loadEvents() })
</script>

<style scoped lang="scss">
.sync-manager {
  display: flex;
  flex-direction: column;
  gap: 20px;
  animation: fadeIn 0.4s ease-out;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

.panel {
  background: var(--el-bg-color);
  border-radius: 16px;
  border: 1px solid var(--el-border-color-lighter);
  overflow: hidden;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.02);
  transition: box-shadow 0.3s ease;
  
  &:hover {
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.06);
  }
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 24px 14px;
  border-bottom: 1px solid var(--el-border-color-extra-light);
  background: var(--el-bg-color);

  .panel-title {
    display: flex;
    align-items: center;
    gap: 10px;
    font-weight: 600;
    font-size: 15px;
    color: var(--el-text-color-primary);
  }

  .title-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border-radius: 9px;

    &.ops { background: #fff3e0; color: #B76E79; }
    &.status { background: #e8f5e9; color: #7CB342; }
    &.event { background: #e3f2fd; color: #C5A55A; }
  }
}

.panel-body {
  padding: 20px 24px;
}

/* ── 同步操作 ── */
.ops-description {
  margin: 0 0 20px 0;
  font-size: 13px;
  color: var(--el-text-color-regular);
  line-height: 1.6;
}

.ops-row {
  display: flex;
  align-items: flex-end;
  gap: 24px;
  flex-wrap: wrap;
}

.ops-field {
  display: flex;
  flex-direction: column;
  gap: 8px;

  .ops-label {
    font-size: 13px;
    font-weight: 600;
    color: var(--el-text-color-primary);
  }

  .ops-select {
    width: 240px;
  }

  &.action {
    margin-left: auto;
    
    .sync-btn {
      padding: 0 24px;
      font-weight: 600;
      letter-spacing: 0.5px;
    }
  }
}

.mode-switch {
  display: flex;
  gap: 4px;
  padding: 4px;
  background: var(--el-fill-color-lighter);
  border-radius: 10px;

  .mode-option {
    padding: 8px 18px;
    border-radius: 8px;
    cursor: pointer;
    font-size: 13px;
    font-weight: 500;
    color: var(--el-text-color-regular);
    transition: all 0.2s ease;
    user-select: none;

    &:hover { color: var(--el-color-primary); }

    &.active {
      background: var(--el-bg-color);
      color: var(--el-color-primary);
      font-weight: 600;
      box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
    }
  }
}

.quick-ops {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--el-border-color-extra-light);

  .quick-hint {
    font-size: 12px;
    color: var(--el-text-color-placeholder);
  }
}

/* ── 同步进度 ── */
.sync-progress {
  .progress-body {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 20px;
    font-size: 14px;
    color: var(--el-color-primary);
    font-weight: 500;

    .spin {
      animation: spin 1s linear infinite;
    }
  }
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* ── 双列布局 ── */
.sync-columns {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

/* ── 同步记录列表 ── */
.checkpoint-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 480px;
  overflow-y: auto;
  padding-right: 4px;

  &::-webkit-scrollbar { width: 4px; }
  &::-webkit-scrollbar-thumb { background: var(--el-border-color); border-radius: 2px; }
}

.checkpoint-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid var(--el-border-color-lighter);
  transition: background 0.15s ease;

  &:hover { background: var(--el-fill-color-lighter); }

  .cp-left {
    display: flex;
    align-items: center;
    gap: 10px;

    .cp-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;

      &.success { background: #7CB342; box-shadow: 0 0 6px rgba(124, 179, 66, 0.4); }
      &.error { background: #E57373; box-shadow: 0 0 6px rgba(229, 115, 115, 0.4); }
    }

    .cp-info {
      .cp-domain { font-weight: 600; font-size: 13px; color: var(--el-text-color-primary); }
      .cp-source { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 1px; }
    }
  }

  .cp-right {
    display: flex;
    align-items: center;
    gap: 10px;

    .cp-meta {
      display: flex;
      gap: 6px;
      font-size: 12px;
      color: var(--el-text-color-secondary);
      text-align: right;
    }
  }
}

/* ── 事件列表 ── */
.event-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 480px;
  overflow-y: auto;
  padding-right: 4px;

  &::-webkit-scrollbar { width: 4px; }
  &::-webkit-scrollbar-thumb { background: var(--el-border-color); border-radius: 2px; }
}

.event-item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 10px 14px;
  border-radius: 10px;
  border: 1px solid var(--el-border-color-lighter);
  gap: 10px;
  transition: background 0.15s ease;

  &:hover { background: var(--el-fill-color-lighter); }

  .event-left {
    display: flex;
    gap: 10px;
    flex: 1;
    min-width: 0;

    .event-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      margin-top: 5px;
      flex-shrink: 0;

      &.success { background: #7CB342; }
      &.error { background: #E57373; }
      &.warning { background: #fb8c00; }
      &.info { background: #90a4ae; }
    }

    .event-info {
      .event-type-row {
        display: flex;
        align-items: center;
        gap: 6px;

        .event-type { font-weight: 600; font-size: 13px; color: var(--el-text-color-primary); }
        .event-domain { font-size: 12px; color: var(--el-text-color-secondary); }
      }

      .event-detail {
        display: flex;
        gap: 6px;
        font-size: 12px;
        color: var(--el-text-color-secondary);
        margin-top: 3px;

        .fallback { color: #fb8c00; font-weight: 500; }
      }

      .event-error {
        font-size: 12px;
        color: var(--el-color-danger);
        margin-top: 3px;
        line-height: 1.4;
      }
    }
  }

  .event-time {
    font-size: 12px;
    color: var(--el-text-color-placeholder);
    white-space: nowrap;
    flex-shrink: 0;
  }
}

/* ── 分页 ── */
.pagination-wrap {
  display: flex;
  justify-content: center;
  margin-top: 16px;
}

/* ── 空状态 ── */
.empty-compact {
  text-align: center;
  padding: 32px 20px;
  color: var(--el-text-color-secondary);
  font-size: 14px;

  p { margin: 0; }
}

/* ── 响应式 ── */
@media (max-width: 900px) {
  .sync-columns { grid-template-columns: 1fr; }
  .ops-row { flex-direction: column; align-items: stretch; gap: 16px; }
  .ops-field { &.action { margin-left: 0; } .ops-select { width: 100%; } }
}
</style>
