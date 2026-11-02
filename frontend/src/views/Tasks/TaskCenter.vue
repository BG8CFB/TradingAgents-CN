<template>
  <div class="task-center">
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><List /></el-icon>
        任务中心
      </h1>
      <p class="page-description">统一查看并管理分析任务：进行中 / 已完成 / 失败</p>
    </div>

    <el-card class="tabs-card" shadow="never">
      <el-tabs v-model="activeTab" @tab-click="onTabChange">
        <el-tab-pane label="全部" name="all" />
        <el-tab-pane label="进行中" name="running" />
        <el-tab-pane label="已完成" name="completed" />
        <el-tab-pane label="失败" name="failed" />
      </el-tabs>
    </el-card>

    <!-- 筛选表单 -->
    <el-card class="filter-card" shadow="never">
      <el-form :inline="true" @submit.prevent>
        <el-form-item label="时间范围">
          <el-date-picker v-model="filters.dateRange" type="daterange" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" format="YYYY-MM-DD" value-format="YYYY-MM-DD" style="width: 260px" />
        </el-form-item>
        <el-form-item label="市场">
          <el-select v-model="filters.market" clearable placeholder="全部" style="width: 120px">
            <el-option label="全部" value="" />
            <el-option label="美股" value="美股" />
            <el-option label="A股" value="A股" />
            <el-option label="港股" value="港股" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filters.status" clearable placeholder="全部" style="width: 120px">
            <el-option label="全部" value="" />
            <el-option label="进行中" value="processing" />
            <el-option label="已完成" value="completed" />
            <el-option label="失败" value="failed" />
          </el-select>
        </el-form-item>
        <el-form-item label="股票">
          <el-input v-model="filters.stock" placeholder="代码或名称" style="width: 160px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="applyFilters" :loading="loading">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 统计卡片（均基于当前页数据，与分页一致） -->
    <el-row :gutter="16" style="margin-top: 12px">
      <el-col :span="6">
        <el-card shadow="never"><div class="stat"><div class="value">{{ stats.pageTotal }}</div><div class="label">当前页</div></div></el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never"><div class="stat"><div class="value">{{ stats.completed }}</div><div class="label">已完成(页)</div></div></el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never"><div class="stat"><div class="value">{{ stats.failed }}</div><div class="label">失败(页)</div></div></el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never"><div class="stat"><div class="value">{{ stats.uniqueStocks }}</div><div class="label">股票数(页)</div></div></el-card>
      </el-col>
    </el-row>


    <el-card class="list-card" shadow="never">
      <div class="list-header">
        <div class="left">
          <el-input v-model="keyword" placeholder="搜索股票代码/名称" clearable style="width: 220px" />
          <el-button @click="refreshList" :loading="loading">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
        <div class="right">
          <el-button @click="exportSelected" :disabled="selectedRows.length===0">
            <el-icon><Download /></el-icon>
            导出所选
          </el-button>
        </div>
      </div>

      <el-table :data="filteredList" v-loading="loading" style="width: 100%" class="hidden-sm-and-down" @selection-change="onSelectionChange">
        <el-table-column type="selection" width="50" />
        <el-table-column prop="task_id" label="任务ID" width="220" />
        <el-table-column prop="stock_code" label="股票代码" width="120" />
        <el-table-column prop="stock_name" label="股票名称" width="150" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)">{{ getStatusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="progress" label="进度" width="120">
          <template #default="{ row }">
            <el-progress :percentage="row.progress || 0" :status="row.status==='failed'?'exception':(row.status==='completed'?'success':undefined)"/>
          </template>
        </el-table-column>
        <el-table-column prop="start_time" label="开始时间" width="180">
          <template #default="{ row }">
            {{ formatTime(row.start_time || row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="350" fixed="right">
          <template #default="{ row }">
            <el-button link size="small" type="primary" @click="openTaskDetail(row)">任务详情</el-button>
            <el-button v-if="row.status==='completed'" link size="small" @click="openResult(row)">查看结果</el-button>
            <el-button v-if="row.status==='completed'" link size="small" @click="openReport(row)">报告详情</el-button>
            <el-button v-if="row.status==='failed'" link size="small" @click="showErrorDetail(row)">查看错误</el-button>
            <el-button v-if="row.status==='failed'" link size="small" @click="retryTask(row)">重试</el-button>
            <el-button v-if="row.status==='processing' || row.status==='running' || row.status==='pending'" link size="small" @click="markAsFailed(row)">标记失败</el-button>
            <el-button link size="small" @click="deleteTask(row)" style="color: #E57373;">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 移动端卡片列表（与上表同数据同操作） -->
      <MobileTable
        v-model:selection="mobileSelection"
        class="hidden-md-and-up"
        :rows="filteredList"
        :columns="mobileColumns"
        row-key="task_id"
        head-prop="stock_code"
        head-right-prop="status"
        clickable
        @row-click="(row: any) => openTaskDetail(row)"
      >
        <template #headRight="{ row }">
          <el-tag :type="getStatusType(row.status)" size="small">{{ getStatusText(row.status) }}</el-tag>
        </template>
        <template #actions="{ row }">
          <el-button link size="small" type="primary" @click="openTaskDetail(row)">详情</el-button>
          <el-button v-if="row.status==='completed'" link size="small" @click="openResult(row)">结果</el-button>
          <el-button v-if="row.status==='completed'" link size="small" @click="openReport(row)">报告</el-button>
          <el-button v-if="row.status==='failed'" link size="small" @click="retryTask(row)">重试</el-button>
          <el-button link size="small" style="color: #E57373;" @click="deleteTask(row)">删除</el-button>
        </template>
      </MobileTable>

      <div class="pagination-wrapper">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[20, 50, 100]"
          :total="total"
          layout="total, sizes, prev, pager, next, jumper"
          @size-change="handleSizeChange"
          @current-change="handleCurrentChange"
        />
      </div>
    </el-card>

    <!-- 结果弹窗组件化 -->
    <TaskResultDialog
      v-model="resultVisible"
      :result="currentResult"
      @close="resultVisible=false"
      @view-report="currentRow && openReport(currentRow)"
    />

  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { List, Refresh, Download } from '@element-plus/icons-vue'
import { analysisApi, type AnalysisTask } from '@/api/analysis'
import TaskResultDialog from '@/components/Global/TaskResultDialog.vue'
import MobileTable from '@/components/Global/MobileTable.vue'
import { formatDateTime } from '@/utils/datetime'


const route = useRoute()
const router = useRouter()

const activeTab = ref<'all'|'running'|'completed'|'failed'>('all')
const loading = ref(false)
const keyword = ref('')
const currentPage = ref(1)
const pageSize = ref(20)
const total = ref(0)
const list = ref<AnalysisTask[]>([])
const selectedRows = ref<AnalysisTask[]>([])
// 移动端卡片列表的选中集（与桌面表格 selection 对应，导出用）
const mobileSelection = ref<any[]>([])
// 移动卡片列定义（与桌面表格列对应；task_id 进副标题行避免占宽）
const mobileColumns = [
  { prop: 'task_id', label: '任务ID' },
  { prop: 'stock_code', label: '代码', skip: true },
  { prop: 'stock_name', label: '名称' },
  { prop: 'status', label: '状态', skip: true },
  {
    prop: 'progress', label: '进度',
    formatter: (row: any) => `${Number(row.progress ?? 0)}%`
  },
  {
    prop: 'start_time', label: '开始时间',
    formatter: (row: any) => formatTime(String(row.start_time || row.created_at || ''))
  }
]
// 筛选与统计
const filters = ref<{ dateRange: string[]; market: string; status: string; stock: string }>({
  dateRange: [], market: '', status: '', stock: ''
})
const stats = ref({ pageTotal: 0, completed: 0, failed: 0, uniqueStocks: 0 })


// 任务进度更新走 5s 轮询（setupPolling），不再为每个运行中任务建 WebSocket 连接
let timer: ReturnType<typeof setInterval> | null = null

const setupPolling = () => {
  if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
  // 定期刷新列表（每 5 秒）
  if (activeTab.value === 'running') {
    timer = setInterval(() => loadList(), 5000)
  }
}

const statusParam = computed(() => {
  if (activeTab.value === 'all') return undefined
  if (activeTab.value === 'running') return 'processing'
  return activeTab.value
})

const loadList = async () => {
  loading.value = true
  try {
    const params: Record<string, string | number | undefined> = {
      page: currentPage.value,
      page_size: pageSize.value,
      status: filters.value.status || statusParam.value,
      stock_code: filters.value.stock || undefined
    }
    if (filters.value.market) params.market_type = filters.value.market
    if (filters.value.dateRange && filters.value.dateRange.length === 2) {
      params.start_date = filters.value.dateRange[0]
      params.end_date = filters.value.dateRange[1]
    }

    const res = await analysisApi.getHistory(params)
    const body = res?.data ?? { tasks: [], total: 0 }
    const tasks: AnalysisTask[] = body.tasks || []
    total.value = body.total ?? tasks.length

    list.value = tasks

    // 统计：全部基于当前页数据，与分页 total（全局总数）分离，避免口径混用
    const completed = tasks.filter((x: AnalysisTask) => x.status === 'completed').length
    const failed = tasks.filter((x: AnalysisTask) => x.status === 'failed').length
    const uniqueStocks = new Set(tasks.map((x: AnalysisTask) => x.stock_code || x.stock_symbol)).size
    stats.value = { pageTotal: tasks.length, completed, failed, uniqueStocks }
  } catch (e: unknown) {
    ElMessage.error((e as Error)?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

// 查询/重置
const applyFilters = () => { currentPage.value = 1; loadList() }
const resetFilters = () => { filters.value = { dateRange: [], market: '', status: '', stock: '' }; currentPage.value = 1; loadList() }

// 报告详情：跳转完整报告页（ReportDetail，含关键点位/分析概览等结构化展示）

const filteredList = computed(() => {
  let arr = list.value
  if (keyword.value) {
    const k = keyword.value.toLowerCase()
    arr = arr.filter((x:any) => (x.stock_code||'').toLowerCase().includes(k) || (x.stock_name||'').toLowerCase().includes(k) || (x.task_id||'').toLowerCase().includes(k))
  }
  return arr
})

const handleSizeChange = (size:number) => { pageSize.value = size; currentPage.value = 1; loadList() }
const handleCurrentChange = (page:number) => { currentPage.value = page; loadList() }
const onTabChange = () => {
  // 使用 nextTick 确保 activeTab 的值已经更新
  nextTick(() => {
    currentPage.value = 1
    loadList()
    setupPolling()
  })
}
const refreshList = () => loadList()
const onSelectionChange = (rows: AnalysisTask[]) => { selectedRows.value = rows }

// 结果与报告
const resultVisible = ref(false)
const currentResult = ref<Record<string, unknown> | null>(null)
const currentRow = ref<AnalysisTask | null>(null)

const openResult = async (row: AnalysisTask) => {
  currentRow.value = row
  try {
    const res = await analysisApi.getTaskResult(row.task_id)
    const body = res?.data ?? {}
    currentResult.value = body
    resultVisible.value = true
  } catch {
    ElMessage.error('获取结果失败')
  }
}

/** 跳转完整报告详情页 */
const openReport = (row: AnalysisTask): void => {
  const id = row?.task_id
  if (!id) { ElMessage.warning('未找到报告ID'); return }
  currentRow.value = row
  router.push({ name: 'ReportDetail', params: { id } })
}

/** 跳转分析任务详情页（实时过程/报告/配置，全状态可进，二次进入入口） */
const openTaskDetail = (row: AnalysisTask): void => {
  const id = row?.task_id
  if (!id) { ElMessage.warning('未找到任务ID'); return }
  currentRow.value = row
  router.push({ name: 'AnalysisTaskDetail', params: { taskId: id } })
}

const retryTask = (_row: AnalysisTask) => { ElMessage.info('重试功能待实现') }

// 显示错误详情
const showErrorDetail = async (row: AnalysisTask) => {
  try {
    const taskId = row.task_id
    if (!taskId) {
      ElMessage.error('任务ID不存在')
      return
    }

    // 获取任务详情
    const res = await analysisApi.getTaskStatus(taskId)
    const task = res?.data ?? row

    const errorMessage = task.error_message || '未知错误'

    // 使用 ElMessageBox 显示错误详情
    await ElMessageBox.alert(
      errorMessage,
      '错误详情',
      {
        confirmButtonText: '确定',
        type: 'error',
        dangerouslyUseHTMLString: true,
        customStyle: {
          width: '600px'
        },
        // 使用 HTML 格式化显示：先转义 HTML 特殊字符防 XSS，再替换换行
        message: errorMessage
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;')
          .replace(/'/g, '&#39;')
          .replace(/\n/g, '<br>')
      }
    )
  } catch (e: unknown) {
    if (e !== 'cancel' && e !== 'close') {
      ElMessage.error((e as Error)?.message || '获取错误详情失败')
    }
  }
}

// 标记任务为失败
const markAsFailed = async (row: AnalysisTask) => {
  try {
    await ElMessageBox.confirm(
      `确定要将任务 "${row.stock_name || row.stock_code}" 标记为失败吗？`,
      '确认操作',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    const taskId = row.task_id
    if (!taskId) {
      ElMessage.error('任务ID不存在')
      return
    }

    loading.value = true
    await analysisApi.markTaskAsFailed(taskId)
    ElMessage.success('任务已标记为失败')
    await loadList()
  } catch (e: unknown) {
    if (e !== 'cancel') {
      ElMessage.error((e as Error)?.message || '标记失败')
    }
  } finally {
    loading.value = false
  }
}

// 删除任务
const deleteTask = async (row: AnalysisTask) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除任务 "${row.stock_name || row.stock_code}" 吗？此操作不可恢复！`,
      '确认删除',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'error'
      }
    )

    const taskId = row.task_id
    if (!taskId) {
      ElMessage.error('任务ID不存在')
      return
    }

    loading.value = true
    await analysisApi.deleteTask(taskId)
    ElMessage.success('任务已删除')
    await loadList()
  } catch (e: unknown) {
    if (e !== 'cancel') {
      ElMessage.error((e as Error)?.message || '删除失败')
    }
  } finally {
    loading.value = false
  }
}

// 导出所选任务
const exportSelected = () => {
  try {
    const data = JSON.stringify(selectedRows.value, null, 2)
    const blob = new Blob([data], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `tasks_selected_${Date.now()}.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    ElMessage.success('导出成功')
  } catch {
    ElMessage.error('导出失败')
  }
}

onMounted(() => {
  // 根据路由 query 初始化标签页
  const tab = String(route.query?.tab ?? '').toLowerCase()
  const validTabs = ['running', 'completed', 'failed', 'all'] as const
  if ((validTabs as readonly string[]).includes(tab)) {
    activeTab.value = tab as typeof activeTab.value
  }
  loadList(); setupPolling()
})

// 监听路由 query 的 tab 变化，动态切换标签页
watch(() => route.query?.tab, (newVal) => {
  const tab = String(newVal ?? '').toLowerCase()
  const validTabs = ['running', 'completed', 'failed', 'all'] as const
  if ((validTabs as readonly string[]).includes(tab)) {
    activeTab.value = tab as typeof activeTab.value
    currentPage.value = 1
    loadList()
    setupPolling()
  }
})
onUnmounted(() => {
  if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
})

const getStatusType = (status:string): 'success' | 'info' | 'warning' | 'danger' => {
  const map: Record<string,'success'|'info'|'warning'|'danger'> = {
    pending: 'info', processing: 'warning', completed: 'success', failed: 'danger', cancelled: 'info'
  }
  return map[status] || 'info'
}

const getStatusText = (status: string): string => {
  const map: Record<string, string> = {
    pending: '等待中', processing: '处理中', completed: '已完成', failed: '失败', cancelled: '已取消'
  }
  return map[status] || status
}
const formatTime = (t:string) => t ? formatDateTime(t) : '-'


</script>

<style scoped lang="scss">
.task-center {
  .page-header { margin-bottom: 24px; }
  .page-title { display:flex; align-items:center; gap:8px; font-size:24px; font-weight:600; margin:0 0 8px 0; }
  .page-description { color: var(--el-text-color-regular); margin:0; }
  .tabs-card { margin-bottom: 16px; }
  .list-header { display:flex; justify-content: space-between; align-items: center; margin-bottom: 12px; gap:8px; }
  .pagination-wrapper { display:flex; justify-content:center; margin-top: 16px; }
}
</style>

