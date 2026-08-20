<template>
  <div class="task-report-panel">
    <!-- 加载中 -->
    <div v-if="loading" v-loading="true" class="panel-loading" element-loading-text="报告加载中…">
      <el-skeleton :rows="6" animated />
    </div>

    <!-- 加载失败 -->
    <div v-else-if="loadError" class="panel-error">
      <el-alert type="error" :title="loadError" :closable="false" show-icon>
        <el-button size="small" @click="load">重试</el-button>
      </el-alert>
    </div>

    <!-- 空态：无报告（cancelled 中断 / 结果缺失） -->
    <div v-else-if="isEmpty" class="panel-empty">
      <el-empty :description="emptyDescription">
        <el-button v-if="status === 'cancelled'" type="primary" plain @click="emit('restart')">
          重新发起分析
        </el-button>
      </el-empty>
    </div>

    <!-- 报告内容 -->
    <template v-else>
      <!-- 风险提示 -->
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        class="risk-disclaimer"
      >
        <template #title>
          <span style="font-weight: bold;">报告由 AI 基于历史数据自动生成，仅供学习研究，不构成任何投资建议。市场有风险，投资需谨慎。</span>
        </template>
      </el-alert>

      <!-- 最终决策卡（structured_summary 优先，decision 兜底） -->
      <div v-if="result?.structured_summary || result?.decision" class="decision-section">
        <h4 class="section-title">🎯 分析参考</h4>
        <div class="decision-card">
          <div class="decision-main">
            <div class="decision-action">
              <span class="label">分析倾向:</span>
              <el-tag :type="actionTagType" size="large">{{ finalSignal || '暂无' }}</el-tag>
              <el-tag type="info" size="small" style="margin-left: 8px;">仅供参考</el-tag>
            </div>

            <div class="decision-metrics">
              <div class="metric-item">
                <span class="label">参考价格:</span>
                <span class="value">{{ structured?.key_indicators?.target_price || decision?.target_price || '暂无' }}</span>
              </div>
              <div class="metric-item">
                <span class="label">模型置信度:</span>
                <span class="value">{{ confidenceText }}</span>
              </div>
              <div class="metric-item">
                <span class="label">风险评分:</span>
                <span class="value">{{ structured?.risk_assessment?.level || formatPercentage(decision?.risk_score) }}</span>
              </div>
            </div>
          </div>

          <div class="decision-reasoning">
            <h5>分析依据:</h5>
            <p v-if="structured?.risk_assessment?.description">
              {{ structured.risk_assessment.description }}
            </p>
            <p v-else>{{ decision?.reasoning || decision?.reason || '暂无分析依据' }}</p>

            <!-- 关键指标 -->
            <div v-if="structured?.key_indicators" class="key-indicators">
              <h5 class="key-indicators-title">🔑 关键点位参考:</h5>
              <div class="key-indicators-grid">
                <div class="key-indicator-item">
                  <span class="key-indicator-label">入场:</span>
                  <strong class="key-indicator-value">{{ structured.key_indicators.entry_price ?? '暂无' }}</strong>
                </div>
                <div class="key-indicator-item">
                  <span class="key-indicator-label">止损:</span>
                  <strong class="key-indicator-value">{{ structured.key_indicators.stop_loss ?? '暂无' }}</strong>
                </div>
                <div class="key-indicator-item">
                  <span class="key-indicator-label">支撑:</span>
                  <strong class="key-indicator-value">{{ structured.key_indicators.support_level ?? '暂无' }}</strong>
                </div>
                <div class="key-indicator-item">
                  <span class="key-indicator-label">阻力:</span>
                  <strong class="key-indicator-value">{{ structured.key_indicators.resistance_level ?? '暂无' }}</strong>
                </div>
              </div>
            </div>

            <el-alert type="info" :closable="false" style="margin-top: 12px;">
              <template #default>
                <span style="font-size: 13px;">💡 以上内容由 AI 基于历史数据自动生成，仅供学习研究，不构成任何投资建议。投资有风险，入市需谨慎。</span>
              </template>
            </el-alert>
          </div>
        </div>
      </div>

      <!-- 分析概览 -->
      <div v-if="structured?.analysis_summary || result?.summary" class="overview-section">
        <h4 class="section-title">📊 分析概览</h4>
        <div class="overview-card">
          <div v-if="structured?.analysis_summary || result?.summary" class="overview-summary">
            <h5>分析摘要:</h5>
            <p style="white-space: pre-wrap;">{{ structured?.analysis_summary || result?.summary }}</p>
          </div>
          <div v-if="structured?.investment_recommendation || result?.recommendation" class="overview-recommendation">
            <h5>投资建议:</h5>
            <p style="white-space: pre-wrap;">{{ structured?.investment_recommendation || result?.recommendation }}</p>
          </div>
        </div>
      </div>

      <!-- 详细分析报告（标题 report_titles 驱动，缺失时 agentDisplayNames 兜底） -->
      <div v-if="reportEntries.length" class="reports-section">
        <h4 class="section-title">📋 详细分析报告</h4>
        <el-tabs v-model="activeReportTab" type="card" class="report-tabs">
          <el-tab-pane
            v-for="(entry, idx) in reportEntries"
            :key="entry.key"
            :name="String(idx)"
            :label="entry.title"
            class="report-tab-pane"
          >
            <div class="report-header">
              <div class="report-title">
                <span class="report-icon">{{ entry.icon }}</span>
                <span class="report-name">{{ entry.title }}</span>
              </div>
              <div class="report-description">{{ entry.description }}</div>
            </div>
            <div class="report-content-wrapper">
              <div
                v-if="entry.html"
                class="report-content markdown-body"
                v-html="entry.html"
              ></div>
              <div v-else class="no-content">
                <el-empty description="暂无内容" />
              </div>
            </div>
          </el-tab-pane>
        </el-tabs>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { analysisApi } from '@/api/analysis'
import { reportsApi } from '@/api/reports'
import { renderMarkdown } from '@/utils/markdown'
import { loadAgentDisplayNames } from '@/utils/agentDisplayNames'

/** 后端 GET /tasks/{id}/result 返回 data 的消费字段（app/routers/analysis.py final_result_data） */
interface TaskResultData {
  analysis_id?: string
  stock_symbol?: string
  stock_code?: string
  analysis_date?: string
  summary?: string
  recommendation?: string
  decision?: {
    action?: string
    confidence?: number
    target_price?: string | number
    risk_score?: number
    reasoning?: string
    reason?: string
  } | Record<string, never>
  structured_summary?: {
    final_signal?: string
    model_confidence?: number
    analysis_summary?: string
    investment_recommendation?: string
    risk_assessment?: { level?: string; description?: string }
    key_indicators?: {
      target_price?: string | number
      entry_price?: string | number
      stop_loss?: string | number
      support_level?: string | number
      resistance_level?: string | number
    }
  } | Record<string, never>
  reports?: Record<string, string>
  report_titles?: Record<string, string>
  state?: Record<string, unknown>
  [key: string]: unknown
}

interface ReportEntry {
  key: string
  title: string
  icon: string
  description: string
  html: string
}

const props = withDefaults(defineProps<{
  taskId: string
  visible: boolean
  status?: string
}>(), {
  status: '',
})

const emit = defineEmits<{ restart: [] }>()

const loading = ref(false)
const loadError = ref('')
const loaded = ref(false)
const result = ref<TaskResultData | null>(null)
const activeReportTab = ref('0')

// 首次可见时拉取（详情页切到报告 tab / 完成自动切换时触发）
watch(
  () => props.visible,
  (v) => {
    if (v && !loaded.value && !loading.value) void load()
  },
  { immediate: true },
)
onMounted(() => {
  if (props.visible && !loaded.value && !loading.value) void load()
})

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const res = await analysisApi.getTaskResult(props.taskId)
    result.value = (res.data ?? {}) as TaskResultData
    loaded.value = true
  } catch (e: unknown) {
    loadError.value = `报告加载失败：${e instanceof Error ? e.message : String(e)}`
  } finally {
    loading.value = false
  }
}

const structured = computed(() => {
  const s = result.value?.structured_summary
  return s && Object.keys(s).length ? s : null
})
const decision = computed(() => {
  const d = result.value?.decision
  return d && Object.keys(d).length ? d : null
})
const finalSignal = computed(() => structured.value?.final_signal || decision.value?.action || '')
const actionTagType = computed((): 'primary' | 'success' | 'warning' | 'info' | 'danger' => {
  const actionTypes: Record<string, 'primary' | 'success' | 'warning' | 'info' | 'danger'> = {
    买入: 'success',
    持有: 'warning',
    卖出: 'danger',
    观望: 'info',
  }
  return actionTypes[finalSignal.value] || 'info'
})
const confidenceText = computed(() =>
  structured.value
    ? formatPercentage(structured.value.model_confidence === undefined ? undefined : structured.value.model_confidence / 100)
    : formatPercentage(decision.value?.confidence),
)

function formatPercentage(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '暂无'
  return `${(value * 100).toFixed(1)}%`
}

// ── 报告条目（标题 report_titles 驱动；缺失时 loadAgentDisplayNames 兜底；都无则用 key） ──
// 图标/描述是纯装饰映射，不承载智能体中文显示名（名称一律来自后端）
const REPORT_ICON: Record<string, string> = {
  bull_researcher: '🐂',
  bear_researcher: '🐻',
  research_team_decision: '🔬',
  trader_investment_plan: '💼',
  risky_analyst: '⚡',
  safe_analyst: '🛡️',
  neutral_analyst: '⚖️',
  risk_management_decision: '👔',
  final_trade_decision: '🎯',
  investment_plan: '📋',
}
// fallback 名称映射（report_titles 缺失时；含 *_report 键别名）
const agentNames = ref<Record<string, string>>({})
watch(
  loaded,
  (v) => {
    if (!v) return
    // report_titles 未覆盖全部 key 时也要兜底（部分覆盖场景按 key 缺失加载）
    const reportsData = (result.value?.reports ?? result.value?.state ?? {}) as Record<string, unknown>
    const uncovered = Object.keys(reportsData).some(k => !result.value?.report_titles?.[k])
    if (!uncovered) return
    loadAgentDisplayNames()
      .then((m) => {
        agentNames.value = m
      })
      .catch(() => {
        agentNames.value = {}
      })
  },
  { immediate: true },
)

const reportEntries = computed<ReportEntry[]>(() => {
  const r = result.value
  if (!r) return []
  const reportsData: Record<string, unknown> =
    (r.reports && typeof r.reports === 'object' && Object.keys(r.reports).length
      ? r.reports
      : (r.state ?? {})) as Record<string, unknown>
  const titles = r.report_titles ?? {}

  const keys = Object.keys(reportsData).filter((k) => {
    const v = reportsData[k]
    // state 兜底时过滤非报告字段与空值
    return v !== null && v !== undefined && String(v).trim() !== ''
  })

  return keys.map((key) => {
    const title = titles[key] || agentNames.value[key] || key
    return {
      key,
      title,
      icon: REPORT_ICON[key] || '📊',
      description: '详细分析报告',
      html: formatReportContent(reportsData[key]),
    }
  })
})

function formatReportContent(content: unknown): string {
  if (!content) return ''
  let text: string
  if (typeof content === 'string') {
    text = content
  } else if (typeof content === 'object' && content !== null && 'judge_decision' in (content as Record<string, unknown>)) {
    text = String((content as Record<string, unknown>).judge_decision ?? '')
  } else if (typeof content === 'object') {
    text = JSON.stringify(content, null, 2)
  } else {
    text = String(content)
  }
  try {
    return renderMarkdown(text)
  } catch {
    const escaped = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    return `<pre style="white-space: pre-wrap; font-family: inherit;">${escaped}</pre>`
  }
}

const isEmpty = computed(() =>
  loaded.value && !loadError.value && !reportEntries.value.length && !structured.value && !decision.value,
)
const emptyDescription = computed(() =>
  props.status === 'cancelled' ? '任务已取消，未生成分析报告' : '暂无分析报告',
)

// ── 下载（迁移自 SingleAnalysis downloadReport；reportId = taskId，供 TaskDetail 顶栏 dropdown 调用） ──
const FORMAT_NAMES: Record<string, string> = {
  markdown: 'Markdown',
  docx: 'Word',
  pdf: 'PDF',
  json: 'JSON',
}
const FORMAT_EXTS: Record<string, string> = {
  markdown: 'md',
  docx: 'docx',
  pdf: 'pdf',
  json: 'json',
}

/** 从错误中提取后端 message（blob 错误响应需读文本解析 JSON detail） */
async function extractErrorMessage(err: unknown): Promise<string> {
  const anyErr = err as { message?: string; response?: { data?: unknown } }
  const data = anyErr?.response?.data
  if (data instanceof Blob) {
    try {
      const text = await data.text()
      try {
        const parsed = JSON.parse(text) as { detail?: string; message?: string }
        return parsed.detail || parsed.message || text
      } catch {
        return text
      }
    } catch {
      // fallthrough
    }
  }
  return anyErr?.message || '未知错误'
}

const downloading = ref(false)
async function download(format: string = 'markdown') {
  // 以 loaded 为准：接口成功但空对象也不应产出空报告文件
  if (!loaded.value || !result.value) {
    ElMessage.error('报告尚未生成，无法下载')
    return
  }
  if (downloading.value) return
  downloading.value = true
  const loadingMsg = ElMessage({
    message: `正在生成${FORMAT_NAMES[format] || format}格式报告...`,
    type: 'info',
    duration: 0,
  })
  try {
    const blob = (await reportsApi.download(props.taskId, format)) as Blob
    loadingMsg.close()

    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    const code =
      (result.value?.stock_symbol as string) ||
      (result.value?.stock_code as string) ||
      String(result.value?.symbol ?? '') ||
      'stock'
    const dateStr = result.value?.analysis_date || new Date().toISOString().slice(0, 10)
    const ext = FORMAT_EXTS[format] || 'txt'
    a.download = `${String(code)}_分析报告_${String(dateStr).slice(0, 10)}.${ext}`

    document.body.appendChild(a)
    a.click()
    window.URL.revokeObjectURL(url)
    document.body.removeChild(a)

    ElMessage.success(`${FORMAT_NAMES[format] || format}报告下载成功`)
  } catch (err: unknown) {
    loadingMsg.close()
    console.error('下载报告出错:', err)
    const message = await extractErrorMessage(err)
    if (message.includes('pandoc')) {
      ElMessage.error({ message: 'PDF/Word 导出需要安装 pandoc 工具', duration: 5000 })
    } else {
      ElMessage.error(`下载报告失败: ${message}`)
    }
  } finally {
    downloading.value = false
  }
}

defineExpose({ download, reload: load })
</script>

<style scoped>
.task-report-panel {
  padding: 4px 0 12px;
}

.panel-loading {
  min-height: 200px;
  padding: 16px 0;
}

.panel-error {
  padding: 16px 0;
}

.panel-empty {
  padding: 24px 0;
}

.risk-disclaimer {
  margin-bottom: 16px;
}

.section-title {
  margin: 16px 0 8px;
}

/* ── 决策卡（样式迁移自 SingleAnalysis） ── */
.decision-card {
  background: var(--el-fill-color-lighter);
  border-radius: 8px;
  padding: 16px;
}

.decision-action {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 12px;
}

.decision-action .label,
.decision-metrics .label,
.key-indicator-label {
  color: var(--el-text-color-secondary);
}

.decision-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 32px;
  margin-bottom: 12px;
}

.metric-item .value {
  font-weight: 600;
}

.decision-reasoning p {
  margin: 4px 0;
  white-space: pre-wrap;
  word-break: break-word;
}

.key-indicators {
  margin-top: 12px;
}

.key-indicators-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 8px;
  margin-top: 8px;
}

.key-indicator-item {
  background: var(--el-fill-color);
  border-radius: 6px;
  padding: 6px 10px;
  display: flex;
  gap: 6px;
  align-items: center;
}

/* ── 概览 / 报告 ── */
.overview-card {
  background: var(--el-fill-color-lighter);
  border-radius: 8px;
  padding: 12px 16px;
}

.overview-card p {
  margin: 4px 0 12px;
  word-break: break-word;
}

.reports-section {
  margin-top: 8px;
}

.report-header {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 4px;
}

.report-title {
  font-weight: 600;
}

.report-icon {
  margin-right: 6px;
}

.report-description {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.report-content-wrapper {
  padding: 8px 4px 16px;
}

.report-content {
  line-height: 1.7;
  word-break: break-word;
}

.report-content :deep(pre) {
  overflow-x: auto;
  max-width: 100%;
}

.report-content :deep(table) {
  max-width: 100%;
}

.no-content {
  padding: 24px 0;
}
</style>
