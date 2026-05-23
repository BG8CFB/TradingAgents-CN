<template>
  <div class="market-sync">
    <!-- 手动触发同步 -->
    <el-card shadow="hover" class="sync-card">
      <template #header>
        <div class="card-header">
          <span class="header-title">
            <el-icon><Refresh /></el-icon>
            手动同步
          </span>
        </div>
      </template>
      <el-form inline>
        <el-form-item label="数据域">
          <el-select v-model="syncDomain" placeholder="选择域" style="width: 180px">
            <el-option v-for="d in validDomains" :key="d.value" :label="d.label" :value="d.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="模式">
          <el-radio-group v-model="syncMode">
            <el-radio value="incremental">增量</el-radio>
            <el-radio value="full">全量</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="syncing" @click="handleSync">触发同步</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 同步状态 -->
    <el-card shadow="hover" class="sync-card" style="margin-top: 20px">
      <template #header>
        <div class="card-header">
          <span class="header-title">
            <el-icon><Clock /></el-icon>
            同步状态
          </span>
          <el-button size="small" :loading="loadingStatus" @click="loadStatus" link type="primary">
            <el-icon><Refresh /></el-icon>
          </el-button>
        </div>
      </template>
      <el-table :data="checkpoints" stripe v-loading="loadingStatus" style="width: 100%">
        <el-table-column prop="domain" label="数据域" width="160">
          <template #default="{ row }">{{ domainLabel(row.domain) }}</template>
        </el-table-column>
        <el-table-column prop="source" label="数据源" width="120" />
        <el-table-column prop="last_sync_date" label="最后同步日期" width="140" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'success' ? 'success' : 'danger'" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="record_count" label="记录数" width="100" />
        <el-table-column prop="duration_ms" label="耗时(ms)" width="100" />
      </el-table>
      <el-pagination
        class="pagination"
        v-model:current-page="page"
        :page-size="20"
        :total="total"
        layout="total, prev, pager, next"
        @current-change="loadStatus"
      />
    </el-card>

    <!-- 同步事件 -->
    <el-card shadow="hover" class="sync-card" style="margin-top: 20px">
      <template #header>
        <div class="card-header">
          <span class="header-title">
            <el-icon><Document /></el-icon>
            同步事件
          </span>
          <el-button size="small" :loading="loadingEvents" @click="loadEvents" link type="primary">
            <el-icon><Refresh /></el-icon>
          </el-button>
        </div>
      </template>
      <el-table :data="events" stripe v-loading="loadingEvents" style="width: 100%">
        <el-table-column prop="event_type" label="事件类型" width="140" />
        <el-table-column prop="domain" label="数据域" width="140">
          <template #default="{ row }">{{ domainLabel(row.domain) }}</template>
        </el-table-column>
        <el-table-column prop="source" label="数据源" width="120" />
        <el-table-column prop="record_count" label="记录数" width="80" />
        <el-table-column prop="fallback_from" label="回退源" width="120" />
        <el-table-column prop="error_message" label="错误信息" min-width="200" />
        <el-table-column label="时间" width="180">
          <template #default="{ row }">{{ new Date(row.updated_at).toLocaleString('zh-CN') }}</template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Clock, Document } from '@element-plus/icons-vue'
import {
  triggerSync, getSyncStatus, getSyncEvents,
  type SyncCheckpoint, type SyncEvent,
  DOMAIN_LABELS,
} from '@/api/marketData'
import type { MarketCode } from '@/api/marketData'

const props = defineProps<{ market: MarketCode }>()

const validDomains = computed(() => {
  const all = [
    { value: 'basic_info', label: '基础信息' },
    { value: 'daily_quotes', label: '日K线' },
    { value: 'daily_indicators', label: '每日指标' },
    { value: 'adj_factors', label: '复权因子' },
    { value: 'financial_data', label: '财务数据' },
    { value: 'trade_calendar', label: '交易日历' },
  ]
  if (props.market !== 'cn') {
    all.push({ value: 'corporate_actions', label: '公司行为' })
  }
  return all
})

function domainLabel(domain: string) { return DOMAIN_LABELS[domain] || domain }

const syncDomain = ref('daily_quotes')
const syncMode = ref('incremental')
const syncing = ref(false)

const loadingStatus = ref(false)
const checkpoints = ref<SyncCheckpoint[]>([])
const page = ref(1)
const total = ref(0)

const loadingEvents = ref(false)
const events = ref<SyncEvent[]>([])

async function handleSync() {
  syncing.value = true
  try {
    await triggerSync(props.market, syncDomain.value, syncMode.value)
    ElMessage.success('同步任务已触发')
    loadStatus()
    loadEvents()
  } catch {
    ElMessage.error('触发同步失败')
  } finally {
    syncing.value = false
  }
}

async function loadStatus() {
  loadingStatus.value = true
  try {
    const res = await getSyncStatus(props.market, { page: page.value, page_size: 20 })
    if (res.success) {
      checkpoints.value = res.data?.items || []
      total.value = res.data?.total || 0
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

onMounted(() => { loadStatus(); loadEvents() })
</script>

<style scoped lang="scss">
.market-sync {
  .sync-card {
    .card-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      .header-title {
        display: flex;
        align-items: center;
        gap: 6px;
        font-weight: 600;
        font-size: 15px;
      }
    }
  }
  .pagination { margin-top: 16px; justify-content: center; }
}
</style>
