<template>
  <div class="sync-management">
    <!-- 手动触发同步 -->
    <el-card header="手动同步" class="mb-4">
      <el-form inline>
        <el-form-item label="数据域">
          <el-select v-model="syncDomain" placeholder="选择域">
            <el-option label="基础信息" value="basic_info" />
            <el-option label="日K线" value="daily_quotes" />
            <el-option label="每日指标" value="daily_indicators" />
            <el-option label="复权因子" value="adj_factors" />
            <el-option label="财务数据" value="financial" />
            <el-option label="交易日历" value="trade_calendar" />
          </el-select>
        </el-form-item>
        <el-form-item label="模式">
          <el-radio-group v-model="syncMode">
            <el-radio value="incremental">增量</el-radio>
            <el-radio value="full">全量</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="syncing" @click="handleSync">
            触发同步
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 同步状态 -->
    <el-card header="同步状态">
      <el-table :data="checkpoints" stripe v-loading="loadingStatus">
        <el-table-column prop="domain" label="数据域" width="160" />
        <el-table-column prop="source" label="数据源" width="120" />
        <el-table-column prop="last_sync_date" label="最后同步日期" width="140" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'success' ? 'success' : 'danger'" size="small">
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="record_count" label="记录数" width="100" />
        <el-table-column prop="duration_ms" label="耗时(ms)" width="100" />
      </el-table>
      <el-pagination
        class="mt-4"
        v-model:current-page="page"
        :page-size="20"
        :total="total"
        layout="total, prev, pager, next"
        @current-change="loadStatus"
      />
    </el-card>

    <!-- 同步事件 -->
    <el-card header="同步事件" class="mt-4">
      <el-table :data="events" stripe v-loading="loadingEvents">
        <el-table-column prop="event_type" label="事件类型" width="140" />
        <el-table-column prop="domain" label="数据域" width="140" />
        <el-table-column prop="source" label="数据源" width="120" />
        <el-table-column prop="record_count" label="记录数" width="80" />
        <el-table-column prop="fallback_from" label="回退源" width="120" />
        <el-table-column prop="error_message" label="错误信息" min-width="200" />
        <el-table-column label="时间" width="180">
          <template #default="{ row }">
            {{ new Date(row.updated_at).toLocaleString('zh-CN') }}
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { triggerSync, getSyncStatus, getSyncEvents, type SyncCheckpoint, type SyncEvent } from '@/api/cnData'

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
    await triggerSync(syncDomain.value, syncMode.value)
    ElMessage.success('同步任务已触发')
    loadStatus()
    loadEvents()
  } catch (e: any) {
    ElMessage.error('触发同步失败')
  } finally {
    syncing.value = false
  }
}

async function loadStatus() {
  loadingStatus.value = true
  try {
    const res = await getSyncStatus({ page: page.value, page_size: 20 })
    checkpoints.value = res.data?.items || []
    total.value = res.data?.total || 0
  } catch {
    // 静默
  } finally {
    loadingStatus.value = false
  }
}

async function loadEvents() {
  loadingEvents.value = true
  try {
    const res = await getSyncEvents({ page: 1, page_size: 20 })
    events.value = res.data?.items || []
  } catch {
    // 静默
  } finally {
    loadingEvents.value = false
  }
}

onMounted(() => {
  loadStatus()
  loadEvents()
})
</script>

<style scoped>
.mb-4 { margin-bottom: 16px; }
.mt-4 { margin-top: 16px; }
</style>
