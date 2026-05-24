<template>
  <div class="report-detail">
    <!-- 加载状态 -->
    <div v-if="loading" class="loading-container">
      <el-skeleton :rows="10" animated />
    </div>

    <!-- 报告内容 -->
    <div v-else-if="report" class="report-content">
      <!-- 报告头部 -->
      <el-card class="report-header" shadow="never">
        <div class="header-content">
          <div class="title-section">
            <h1 class="report-title">
              <el-icon><Document /></el-icon>
              {{ report.stock_name || report.stock_symbol }} 分析报告
            </h1>
            <div class="report-meta">
              <el-tag type="primary">{{ report.stock_symbol }}</el-tag>
              <el-tag v-if="report.stock_name && report.stock_name !== report.stock_symbol" type="info">{{ report.stock_name }}</el-tag>
              <el-tag type="success">{{ getStatusText(report.status) }}</el-tag>
              <span class="meta-item">
                <el-icon><Calendar /></el-icon>
                {{ formatTime(report.created_at) }}
              </span>
              <span class="meta-item">
                <el-icon><User /></el-icon>
                {{ formatAnalysts(report.analysts) }}
              </span>
              <span v-if="report.model_info && report.model_info !== 'Unknown'" class="meta-item">
                <el-icon><Cpu /></el-icon>
                <el-tooltip :content="getModelDescription(report.model_info)" placement="top">
                  <el-tag type="info" style="cursor: help;">{{ report.model_info }}</el-tag>
                </el-tooltip>
              </span>
            </div>
          </div>
          
          <div class="action-section">
            <el-dropdown trigger="click" @command="downloadReport">
              <el-button type="primary">
                <el-icon><Download /></el-icon>
                下载报告
                <el-icon class="el-icon--right"><arrow-down /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="markdown">
                    <el-icon><document /></el-icon> Markdown
                  </el-dropdown-item>
                  <el-dropdown-item command="docx">
                    <el-icon><document /></el-icon> Word 文档
                  </el-dropdown-item>
                  <el-dropdown-item command="pdf">
                    <el-icon><document /></el-icon> PDF
                  </el-dropdown-item>
                  <el-dropdown-item command="json" divided>
                    <el-icon><document /></el-icon> JSON (原始数据)
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-button @click="goBack">
              <el-icon><Back /></el-icon>
              返回
            </el-button>
          </div>
        </div>
      </el-card>

      <!-- 风险提示 -->
      <div class="risk-disclaimer">
        <el-alert
          type="warning"
          :closable="false"
          show-icon
        >
          <template #title>
            <div class="disclaimer-content">
              <el-icon class="disclaimer-icon"><WarningFilled /></el-icon>
              <div class="disclaimer-text">
                <p style="margin: 0 0 8px 0;"><strong>⚠️ 重要风险提示与免责声明</strong></p>
                <ul style="margin: 0; padding-left: 20px; line-height: 1.8;">
                  <li><strong>工具性质：</strong>本系统为股票分析辅助工具，使用AI技术对公开市场数据进行分析，不具备证券投资咨询资质。</li>
                  <li><strong>非投资建议：</strong>所有分析结果、评分、建议仅为技术分析参考，不构成任何买卖建议或投资决策依据。</li>
                  <li><strong>数据局限性：</strong>分析基于历史数据和公开信息，可能存在延迟、不完整或不准确的情况，无法预测未来市场走势。</li>
                  <li><strong>投资风险：</strong>股票投资存在市场风险、流动性风险、政策风险等多种风险，可能导致本金损失。</li>
                  <li><strong>独立决策：</strong>投资者应基于自身风险承受能力、投资目标和财务状况独立做出投资决策。</li>
                  <li><strong>专业咨询：</strong>重大投资决策建议咨询具有合法资质的专业投资顾问或金融机构。</li>
                  <li><strong>责任声明：</strong>使用本工具产生的任何投资决策及其后果由投资者自行承担，本系统不承担任何责任。</li>
                </ul>
              </div>
            </div>
          </template>
        </el-alert>
      </div>

      <!-- 关键指标 -->
      <el-card class="metrics-card" shadow="never">
        <template #header>
          <div class="card-header">
            <el-icon><TrendCharts /></el-icon>
            <span>关键指标</span>
          </div>
        </template>
        <div class="metrics-content">
          <el-row :gutter="24">
            <!-- 分析参考 -->
            <el-col :span="8">
              <div class="metric-item">
                <div class="metric-label">
                  <el-icon><TrendCharts /></el-icon>
                  分析参考
                  <el-tooltip content="基于AI模型的分析倾向，仅供参考，不构成投资建议" placement="top">
                    <el-icon style="margin-left: 4px; cursor: help; font-size: 14px;"><QuestionFilled /></el-icon>
                  </el-tooltip>
                </div>
                <div class="metric-value recommendation-value markdown-content" v-html="renderSafeMarkdown(report.recommendation || '暂无')"></div>
                <el-tag type="info" size="small" style="margin-top: 8px;">仅供参考</el-tag>
              </div>
            </el-col>

            <!-- 风险评估 -->
            <el-col :span="8">
              <div class="metric-item risk-item">
                <div class="metric-label">
                  <el-icon><Warning /></el-icon>
                  风险评估
                  <el-tooltip content="基于历史数据的风险评估，实际风险可能更高" placement="top">
                    <el-icon style="margin-left: 4px; cursor: help; font-size: 14px;"><QuestionFilled /></el-icon>
                  </el-tooltip>
                </div>
                <div class="risk-display">
                  <div class="risk-stars">
                    <el-icon
                      v-for="star in 5"
                      :key="star"
                      class="star-icon"
                      :class="{ active: star <= getRiskStars(report.risk_level || '中等') }"
                    >
                      <StarFilled />
                    </el-icon>
                  </div>
                  <div class="risk-label" :style="{ color: getRiskColor(report.risk_level || '中等') }">
                    {{ report.risk_level || '中等' }}风险
                  </div>
                </div>
              </div>
            </el-col>

            <!-- 模型置信度 -->
            <el-col :span="8">
              <div class="metric-item confidence-item">
                <div class="metric-label">
                  <el-icon><DataAnalysis /></el-icon>
                  模型置信度
                  <el-tooltip content="基于AI模型计算的置信度，不代表实际投资成功率" placement="top">
                    <el-icon style="margin-left: 4px; cursor: help; font-size: 14px;"><QuestionFilled /></el-icon>
                  </el-tooltip>
                </div>
                <div class="confidence-display">
                  <el-progress
                    type="circle"
                    :percentage="normalizeConfidenceScore(report.confidence_score || 0)"
                    :width="120"
                    :stroke-width="10"
                    :color="getConfidenceColor(normalizeConfidenceScore(report.confidence_score || 0))"
                  >
                    <template #default="{ percentage }">
                      <span class="confidence-text">
                        <span class="confidence-number">{{ percentage }}</span>
                        <span class="confidence-unit">分</span>
                      </span>
                    </template>
                  </el-progress>
                  <div class="confidence-label">{{ getConfidenceLabel(normalizeConfidenceScore(report.confidence_score || 0)) }}</div>
                </div>
              </div>
            </el-col>
          </el-row>

          <!-- 关键要点 -->
          <div v-if="report.key_points && report.key_points.length > 0" class="key-points">
            <h4>
              <el-icon><List /></el-icon>
              关键要点
            </h4>
            <ul>
              <li v-for="(point, index) in report.key_points" :key="index">
                <el-icon class="point-icon"><Check /></el-icon>
                {{ point }}
              </li>
            </ul>
          </div>

          <!-- 🔥 关键点位参考（来自结构化总结） -->
          <div v-if="report.structured_summary && report.structured_summary.key_indicators" class="key-indicators-section">
            <h4>
              <el-icon><TrendCharts /></el-icon>
              关键点位参考
              <el-tooltip content="基于AI模型分析的参考点位，仅供参考，不构成投资建议" placement="top">
                <el-icon style="margin-left: 4px; cursor: help; font-size: 14px;"><QuestionFilled /></el-icon>
              </el-tooltip>
            </h4>
            <div class="key-indicators-grid">
              <div class="indicator-item">
                <span class="indicator-label">入场价格:</span>
                <span class="indicator-value">{{ report.structured_summary.key_indicators.entry_price || 'N/A' }}</span>
              </div>
              <div class="indicator-item">
                <span class="indicator-label">目标价格:</span>
                <span class="indicator-value">{{ report.structured_summary.key_indicators.target_price || 'N/A' }}</span>
              </div>
              <div class="indicator-item">
                <span class="indicator-label">止损价格:</span>
                <span class="indicator-value">{{ report.structured_summary.key_indicators.stop_loss || 'N/A' }}</span>
              </div>
              <div class="indicator-item">
                <span class="indicator-label">支撑位:</span>
                <span class="indicator-value">{{ report.structured_summary.key_indicators.support_level || 'N/A' }}</span>
              </div>
              <div class="indicator-item">
                <span class="indicator-label">阻力位:</span>
                <span class="indicator-value">{{ report.structured_summary.key_indicators.resistance_level || 'N/A' }}</span>
              </div>
            </div>
            <el-tag type="info" size="small" style="margin-top: 8px;">仅供参考，不构成投资建议</el-tag>
          </div>

          <!-- 🔥 风险评估详情（来自结构化总结） -->
          <div v-if="report.structured_summary && report.structured_summary.risk_assessment" class="risk-assessment-section">
            <h4>
              <el-icon><Warning /></el-icon>
              风险评估详情
            </h4>
            <div class="risk-assessment-content">
              <div class="risk-score-display">
                <span class="risk-score-label">风险评分:</span>
                <el-progress
                  :percentage="(report.structured_summary.risk_assessment.score || 0) * 10"
                  :stroke-width="12"
                  :color="getRiskProgressColor(report.structured_summary.risk_assessment.score || 0)"
                  style="width: 200px; display: inline-block; margin-left: 12px;"
                />
                <span class="risk-score-value">{{ report.structured_summary.risk_assessment.score || 0 }}/10</span>
              </div>
              <div v-if="report.structured_summary.risk_assessment.description" class="risk-description">
                <p>{{ report.structured_summary.risk_assessment.description }}</p>
              </div>
            </div>
          </div>
        </div>
      </el-card>

      <!-- 报告摘要 -->
      <el-card v-if="report.summary" class="summary-card" shadow="never">
        <template #header>
          <div class="card-header">
            <el-icon><InfoFilled /></el-icon>
            <span>执行摘要</span>
          </div>
        </template>
        <div class="summary-content markdown-content" v-html="renderSafeMarkdown(report.summary)"></div>
      </el-card>

      <!-- 报告模块 -->
      <el-card class="modules-card" shadow="never">
        <template #header>
          <div class="card-header">
            <el-icon><Files /></el-icon>
            <span>分析报告</span>
          </div>
        </template>
        
        <el-tabs v-model="activeModule" type="border-card">
          <el-tab-pane
            v-for="moduleName in sortedReportKeys"
            :key="moduleName"
            :label="getModuleDisplayName(moduleName)"
            :name="moduleName"
          >
            <div class="module-content">
              <div v-if="typeof report.reports?.[moduleName] === 'string'" class="markdown-content">
                <div v-html="renderSafeMarkdown(report.reports[moduleName]!)"></div>
              </div>
              <div v-else class="json-content">
                <pre>{{ JSON.stringify(report.reports?.[moduleName], null, 2) }}</pre>
              </div>
            </div>
          </el-tab-pane>
        </el-tabs>
      </el-card>
    </div>

    <!-- 错误状态 -->
    <div v-else class="error-container">
      <el-result
        icon="error"
        title="报告加载失败"
        sub-title="请检查报告ID是否正确或稍后重试"
      >
        <template #extra>
          <el-button type="primary" @click="goBack">返回列表</el-button>
        </template>
      </el-result>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { configApi, type LLMConfig } from '@/api/config'
import { agentConfigApi } from '@/api/agentConfigs'
import { normalizeAnalystId } from '@/constants/analysts'
import {
  Document,
  Calendar,
  User,
  Download,
  Back,
  InfoFilled,
  TrendCharts,
  Files,
  WarningFilled,
  DataAnalysis,
  Warning,
  StarFilled,
  List,
  Check,
  Cpu,
  QuestionFilled,
  ArrowDown
} from '@element-plus/icons-vue'
import { reportsApi } from '@/api/reports'
import { renderMarkdown } from '@/utils/markdown'


// 路由
const route = useRoute()
const router = useRouter()

// 报告数据类型
interface ReportData {
  success?: boolean
  data?: any
  stock_name?: string
  stock_symbol?: string
  status?: string
  created_at?: string
  analysts?: string | string[]
  model_info?: string
  recommendation?: string
  summary?: string
  structured_summary?: any
  reports?: Record<string, any>
  risk_level?: string
  confidence_score?: number | string
  key_points?: string[]
  key_indicators?: any
  risk_assessment?: any
  [key: string]: any
}

// 响应式数据
const loading = ref(true)
const report = ref<ReportData | null>(null)
const activeModule = ref('')
const llmConfigs = ref<LLMConfig[]>([]) // 存储所有模型配置
const analystNameMap = ref<Record<string, string>>({})

// 模块排序权重：按阶段 1→2→3→4 排列
const MODULE_ORDER: Record<string, number> = {
  // 阶段 1：分析师报告（*_report 后缀，权重 100 档，由动态分析师配置决定子序号）
  // 阶段 2：研究团队
  bull_researcher: 200,
  bear_researcher: 201,
  research_team_decision: 202,
  // 阶段 3：风险管理
  risky_analyst: 300,
  safe_analyst: 301,
  neutral_analyst: 302,
  risk_management_decision: 303,
  risk_manager_decision: 303,
  // 阶段 4：交易员与最终决策
  trader_investment_plan: 400,
  investment_plan: 400,
  final_trade_decision: 401,
}

const getModuleWeight = (key: string): number => {
  if (MODULE_ORDER[key] !== undefined) return MODULE_ORDER[key]
  // 阶段1分析师报告 (*_report 后缀)
  if (key.endsWith('_report')) return 150
  return 999
}

const sortedReportKeys = computed(() => {
  if (!report.value?.reports) return []
  return Object.keys(report.value.reports).sort((a, b) => getModuleWeight(a) - getModuleWeight(b))
})

// 获取模型配置列表
const fetchLLMConfigs = async () => {
  try {
    const response = await configApi.getSystemConfig()
    if (response.success && response.data?.llm_configs) {
      llmConfigs.value = response.data.llm_configs
    }
  } catch (error) {
    console.error('获取模型配置失败:', error)
  }
}

// 获取分析师名称映射（从后端动态配置构建）
const loadAnalystNameMap = async () => {
  try {
    const res = await agentConfigApi.getPhase(1)
    if (res.success && res.data?.customModes) {
      const map: Record<string, string> = {}
      res.data.customModes.forEach(mode => {
        const name = mode.name || mode.slug
        if (mode.slug) {
          // 1. 原始 slug 映射
          map[mode.slug] = name
          
          // 2. 规范化 ID 映射
          const normalized = normalizeAnalystId(mode.slug)
          if (normalized) {
            map[normalized] = name
          }

          // 3. 报告模块 key 映射 (e.g. market-analyst -> market_report)
          // 逻辑: 移除 -analyst 后缀, 横杠转下划线, 添加 _report 后缀
          const baseKey = mode.slug.replace(/-analyst$/, '').replace(/-/g, '_')
          const reportKey = `${baseKey}_report`
          
          // 直接使用中文名称，不添加图标
          map[reportKey] = name
          
          // 4. 额外兼容常见 key 变体 (防止 key 不一致导致回退到英文)
          map[baseKey] = name // e.g. market
          map[`${baseKey}_analyst`] = name // e.g. market_analyst
        }
      })
      analystNameMap.value = map
    } else {
      analystNameMap.value = {}
    }
  } catch (error) {
    console.error('获取分析师配置失败:', error)
    analystNameMap.value = {}
  }
}

// 获取报告详情
const fetchReportDetail = async () => {
  loading.value = true
  try {
    const reportId = route.params.id as string

    const result = await reportsApi.detail(reportId)

    if (result.success) {
      report.value = result.data

      // 设置默认激活的模块（使用排序后的第一个）
      const reports = result.data.reports || {}
      const moduleNames = Object.keys(reports).sort((a, b) => getModuleWeight(a) - getModuleWeight(b))
      if (moduleNames.length > 0) {
        activeModule.value = moduleNames[0]
      }
    } else {
      throw new Error(result.message || '获取报告详情失败')
    }
  } catch (error) {
    console.error('获取报告详情失败:', error)
    ElMessage.error('获取报告详情失败')
  } finally {
    loading.value = false
  }
}

// 下载报告
const downloadReport = async (format: string = 'markdown') => {
  if (!report.value) return
  try {
    // 显示加载提示
    const loadingMsg = ElMessage({
      message: `正在生成${getFormatName(format)}格式报告...`,
      type: 'info',
      duration: 0
    })

    const blob = await reportsApi.download(report.value.id, format)

    loadingMsg.close()

    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url

    // 根据格式设置文件扩展名
    const ext = getFileExtension(format)
    a.download = `${report.value.stock_symbol || 'report'}_分析报告_${report.value.analysis_date || new Date().toISOString().slice(0,10)}.${ext}`

    document.body.appendChild(a)
    a.click()
    window.URL.revokeObjectURL(url)
    document.body.removeChild(a)

    ElMessage.success(`${getFormatName(format)}报告下载成功`)
  } catch (error: any) {
    console.error('下载报告失败:', error)

    // 显示详细错误信息
    if (error.message && error.message.includes('pandoc')) {
      ElMessage.error({
        message: 'PDF/Word 导出需要安装 pandoc 工具',
        duration: 5000
      })
    } else {
      ElMessage.error(`下载报告失败: ${error.message || '未知错误'}`)
    }
  }
}

// 辅助函数：获取格式名称
const getFormatName = (format: string): string => {
  const names: Record<string, string> = {
    'markdown': 'Markdown',
    'docx': 'Word',
    'pdf': 'PDF',
    'json': 'JSON'
  }
  return names[format] || format
}

// 辅助函数：获取文件扩展名
const getFileExtension = (format: string): string => {
  const extensions: Record<string, string> = {
    'markdown': 'md',
    'docx': 'docx',
    'pdf': 'pdf',
    'json': 'json'
  }
  return extensions[format] || 'txt'
}

// 返回列表
const goBack = () => {
  router.push('/reports')
}

// 工具函数
const getStatusText = (status: string | undefined) => {
  if (!status) return ''
  const statusMap: Record<string, string> = {
    completed: '已完成',
    processing: '生成中',
    failed: '失败'
  }
  return statusMap[status] || status
}

const formatTime = (time: string | undefined) => {
  if (!time) return ''
  return new Date(time).toLocaleString('zh-CN')
}

// 将分析师英文名称转换为中文（使用统一的映射）
const formatAnalysts = (analysts: string | string[] | undefined) => {
  if (!analysts) return ''
  const arr = Array.isArray(analysts) ? analysts : [analysts]
  if (arr.length === 0) return ''
  return arr
    .map(analyst => {
      const normalized = normalizeAnalystId(analyst)
      return analystNameMap.value[analyst] ||
        (normalized ? analystNameMap.value[normalized] : undefined) ||
        analyst
    })
    .join('、')
}

// 获取模型的详细描述（从后端配置中获取）
const getModelDescription = (modelInfo: string) => {
  if (!modelInfo || modelInfo === 'Unknown') {
    return '未知模型'
  }

  // 1. 优先从后端配置中查找精确匹配
  const config = llmConfigs.value.find(c => c.model_name === modelInfo)
  if (config?.description) {
    return config.description
  }

  // 2. 尝试模糊匹配（处理版本号等变化）
  const fuzzyConfig = llmConfigs.value.find(c =>
    modelInfo.toLowerCase().includes(c.model_name.toLowerCase()) ||
    c.model_name.toLowerCase().includes(modelInfo.toLowerCase())
  )
  if (fuzzyConfig?.description) {
    return fuzzyConfig.description
  }

  // 3. 根据模型名称前缀提供通用描述
  const modelLower = modelInfo.toLowerCase()
  if (modelLower.includes('gpt')) {
    return `OpenAI ${modelInfo} - 强大的语言模型`
  } else if (modelLower.includes('claude')) {
    return `Anthropic ${modelInfo} - 高性能推理模型`
  } else if (modelLower.includes('qwen')) {
    return `阿里通义千问 ${modelInfo} - 中文优化模型`
  } else if (modelLower.includes('glm')) {
    return `智谱 ${modelInfo} - 综合性能优秀`
  } else if (modelLower.includes('deepseek')) {
    return `DeepSeek ${modelInfo} - 高性价比模型`
  } else if (modelLower.includes('ernie')) {
    return `百度文心 ${modelInfo} - 中文能力强`
  } else if (modelLower.includes('spark')) {
    return `讯飞星火 ${modelInfo} - 专业模型`
  } else if (modelLower.includes('moonshot')) {
    return `Moonshot ${modelInfo} - 长上下文模型`
  } else if (modelLower.includes('yi')) {
    return `零一万物 ${modelInfo} - 高性能模型`
  }

  // 4. 默认返回
  return `${modelInfo} - AI 大语言模型`
}

const getModuleDisplayName = (moduleName: string) => {
  // 1. 优先使用动态加载的映射 (第一阶段分析师)
  if (analystNameMap.value && analystNameMap.value[moduleName]) {
    return analystNameMap.value[moduleName]
  }

  // 非第1阶段的固定报告映射（研究团队、交易团队、风险管理团队等）
  const fixedNameMap: Record<string, string> = {
    // 研究团队 (3个)
    bull_researcher: '多头研究员',
    bear_researcher: '空头研究员',
    research_team_decision: '研究经理决策',

    // 交易团队 (1个)
    trader_investment_plan: '交易员计划',

    // 风险管理团队 (4个)
    risky_analyst: '激进分析师',
    safe_analyst: '保守分析师',
    neutral_analyst: '中性分析师',
    risk_management_decision: '投资组合经理',
    risk_manager_decision: '投资组合经理',

    // 最终决策 (1个)
    final_trade_decision: '最终交易决策',

    // 兼容旧字段
    investment_plan: '投资建议',
    investment_debate_state: '研究团队决策（旧）',
    risk_debate_state: '风险管理团队（旧）',
    detailed_analysis: '详细分析'
  }
  
  if (fixedNameMap[moduleName]) {
    return fixedNameMap[moduleName]
  }
  
  // 对于第1阶段分析师报告，自动生成友好中文名称
  if (moduleName.endsWith('_report')) {
    const base = moduleName.replace('_report', '')
    // 尝试从 analystNameMap 中按 base key 匹配
    if (analystNameMap.value && analystNameMap.value[base]) {
      return analystNameMap.value[base]
    }
    // 最后 fallback：下划线分隔 → 中文友好的名称
    return base.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()) + ' 分析师'
  }
  
  // 未匹配到时，做一个友好的回退：下划线转空格
  return moduleName.replace(/_/g, ' ')
}

const renderSafeMarkdown = (content: string): string => {
  if (!content) return ''
  try {
    return renderMarkdown(content)
  } catch (e) {
    return `<pre style="white-space: pre-wrap; font-family: inherit;">${content}</pre>`
  }
}

// 置信度评分相关函数
// 将后端返回的 0-1 小数转换为 0-100 的百分制
const normalizeConfidenceScore = (score: number | string): number => {
  const num = typeof score === 'string' ? parseFloat(score) : score
  if (isNaN(num)) return 0
  // 如果已经是 0-100 的范围，直接返回
  if (num > 1) {
    return Math.round(num)
  }
  // 如果是 0-1 的小数，转换为百分制
  return Math.round(num * 100)
}

const getConfidenceColor = (score: number) => {
  if (score >= 80) return '#7CB342' // 较高 - 绿色
  if (score >= 60) return '#C5A55A' // 中上 - 金色
  if (score >= 40) return '#D4AF37' // 中等 - 琥珀色
  return '#E57373' // 较低 - 红色
}

const getConfidenceLabel = (score: number) => {
  if (score >= 80) return '较高'
  if (score >= 60) return '中上'
  if (score >= 40) return '中等'
  return '较低'
}

// 风险等级相关函数
const getRiskStars = (riskLevel: string) => {
  const riskMap: Record<string, number> = {
    '低': 1,
    '中低': 2,
    '中等': 3,
    '中高': 4,
    '高': 5
  }
  return riskMap[riskLevel] || 3
}

const getRiskColor = (riskLevel: string) => {
  const colorMap: Record<string, string> = {
    '低': '#7CB342',      // 绿色
    '中低': '#95D475',    // 浅绿色
    '中等': '#D4AF37',    // 琥珀色
    '中高': '#E57373',    // 红色
    '高': '#E57373'       // 深红色
  }
  return colorMap[riskLevel] || '#D4AF37'
}

// 🔥 风险评分进度条颜色
const getRiskProgressColor = (score: number) => {
  if (score <= 3) return '#7CB342'  // 低风险 - 绿色
  if (score <= 5) return '#D4AF37'  // 中等风险 - 琥珀色
  if (score <= 7) return '#E57373'  // 较高风险 - 红色
  return '#C45656'                   // 高风险 - 深红色
}

// 生命周期
onMounted(() => {
  loadAnalystNameMap() // 先加载分析师映射，确保显示友好名称
  fetchLLMConfigs() // 先加载模型配置
  fetchReportDetail() // 再加载报告详情
})
</script>

<style lang="scss" scoped>
.report-detail {
  .loading-container {
    padding: 24px;
  }

  .report-content {
    .report-header {
      margin-bottom: 24px;

      .header-content {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;

        .title-section {
          .report-title {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 24px;
            font-weight: 600;
            color: var(--el-text-color-primary);
            margin: 0 0 12px 0;
          }

          .report-meta {
            display: flex;
            align-items: center;
            gap: 16px;
            flex-wrap: wrap;

            .meta-item {
              display: flex;
              align-items: center;
              gap: 4px;
              color: var(--el-text-color-regular);
              font-size: 14px;
            }
          }
        }

        .action-section {
          display: flex;
          gap: 8px;
        }
      }
    }

    /* 风险提示样式 */
    .risk-disclaimer {
      margin-bottom: 24px;
      animation: fadeInDown 0.5s ease-out;
    }

    .risk-disclaimer :deep(.el-alert) {
      background: linear-gradient(135deg, #fff3cd 0%, #ffe69c 100%);
      border: 2px solid #ffc107;
      border-radius: 12px;
      padding: 16px 20px;
      box-shadow: 0 4px 12px rgba(255, 193, 7, 0.2);
    }

    .risk-disclaimer :deep(.el-alert__icon) {
      font-size: 24px;
      color: #ff6b00;
    }

    .disclaimer-content {
      display: flex;
      align-items: center;
      gap: 12px;
      font-size: 15px;
      line-height: 1.6;
    }

    .disclaimer-icon {
      font-size: 24px;
      color: #ff6b00;
      flex-shrink: 0;
      animation: pulse 2s ease-in-out infinite;
    }

    .disclaimer-text {
      color: #856404;
      flex: 1;
    }

    .disclaimer-text strong {
      color: #d63031;
      font-size: 16px;
      font-weight: 700;
    }

    @keyframes pulse {
      0%, 100% {
        transform: scale(1);
        opacity: 1;
      }
      50% {
        transform: scale(1.1);
        opacity: 0.8;
      }
    }

    @keyframes fadeInDown {
      from {
        opacity: 0;
        transform: translateY(-20px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }

    .summary-card,
    .metrics-card,
    .modules-card {
      margin-bottom: 24px;

      .card-header {
        display: flex;
        align-items: center;
        gap: 8px;
        font-weight: 600;
      }
    }

    .summary-content {
      line-height: 1.6;
      color: var(--el-text-color-primary);
    }

    .metrics-content {
      .metric-item {
        text-align: center;
        padding: 24px;
        border: 1px solid var(--el-border-color-light);
        border-radius: 12px;
        background: var(--el-fill-color-blank);
        transition: all 0.3s ease;

        &:hover {
          box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
          transform: translateY(-2px);
        }

        .metric-label {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          font-size: 15px;
          font-weight: 500;
          color: var(--el-text-color-regular);
          margin-bottom: 16px;

          .el-icon {
            font-size: 18px;
          }
        }

        .metric-value {
          font-size: 18px;
          font-weight: 600;
          color: var(--el-color-primary);
        }

        .recommendation-value {
          font-size: 16px;
          line-height: 1.6;
          color: var(--el-text-color-primary);
        }
      }

      // 置信度评分样式
      .confidence-item {
        .confidence-display {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 12px;

          .el-progress {
            margin-bottom: 8px;
          }

          .confidence-text {
            display: flex;
            flex-direction: column;
            align-items: center;
            line-height: 1;

            .confidence-number {
              font-size: 32px;
              font-weight: 700;
            }

            .confidence-unit {
              font-size: 14px;
              margin-top: 4px;
              opacity: 0.8;
            }
          }

          .confidence-label {
            font-size: 16px;
            font-weight: 600;
            color: var(--el-text-color-primary);
          }
        }
      }

      // 风险等级样式
      .risk-item {
        .risk-display {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 12px;

          .risk-stars {
            display: flex;
            gap: 8px;
            font-size: 28px;

            .star-icon {
              color: #DCDFE6;
              transition: all 0.3s ease;

              &.active {
                color: #F7BA2A;
                animation: starPulse 0.6s ease-in-out;
              }
            }
          }

          .risk-label {
            font-size: 18px;
            font-weight: 700;
            margin-top: 4px;
          }

          .risk-description {
            font-size: 13px;
            color: var(--el-text-color-secondary);
            text-align: center;
            line-height: 1.4;
            max-width: 200px;
          }
        }
      }

      .key-points {
        margin-top: 32px;
        padding-top: 24px;
        border-top: 1px solid var(--el-border-color-lighter);

        h4 {
          display: flex;
          align-items: center;
          gap: 8px;
          margin: 0 0 16px 0;
          font-size: 16px;
          font-weight: 600;
          color: var(--el-text-color-primary);

          .el-icon {
            font-size: 18px;
            color: var(--el-color-primary);
          }
        }

        ul {
          margin: 0;
          padding: 0;
          list-style: none;

          li {
            display: flex;
            align-items: flex-start;
            gap: 8px;
            margin-bottom: 12px;
            padding: 12px;
            background: var(--el-fill-color-light);
            border-radius: 8px;
            line-height: 1.6;
            transition: all 0.2s ease;

            &:hover {
              background: var(--el-fill-color);
            }

            .point-icon {
              flex-shrink: 0;
              margin-top: 2px;
              font-size: 16px;
              color: var(--el-color-success);
            }
          }
        }
      }

      // 🔥 关键点位参考样式
      .key-indicators-section {
        margin-top: 32px;
        padding-top: 24px;
        border-top: 1px solid var(--el-border-color-lighter);

        h4 {
          display: flex;
          align-items: center;
          gap: 8px;
          margin: 0 0 16px 0;
          font-size: 16px;
          font-weight: 600;
          color: var(--el-text-color-primary);

          .el-icon {
            font-size: 18px;
            color: var(--el-color-primary);
          }
        }

        .key-indicators-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
          gap: 16px;
          margin-bottom: 12px;

          .indicator-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 16px;
            background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
            border-radius: 8px;
            border: 1px solid var(--el-border-color-lighter);
            transition: all 0.2s ease;

            &:hover {
              box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
              transform: translateY(-1px);
            }

            .indicator-label {
              font-size: 13px;
              color: var(--el-text-color-secondary);
            }

            .indicator-value {
              font-size: 15px;
              font-weight: 600;
              color: var(--el-color-primary);
            }
          }
        }
      }

      // 🔥 风险评估详情样式
      .risk-assessment-section {
        margin-top: 24px;
        padding-top: 24px;
        border-top: 1px solid var(--el-border-color-lighter);

        h4 {
          display: flex;
          align-items: center;
          gap: 8px;
          margin: 0 0 16px 0;
          font-size: 16px;
          font-weight: 600;
          color: var(--el-text-color-primary);

          .el-icon {
            font-size: 18px;
            color: var(--el-color-warning);
          }
        }

        .risk-assessment-content {
          padding: 16px;
          background: linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%);
          border-radius: 8px;
          border: 1px solid #fcd34d;

          .risk-score-display {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 12px;

            .risk-score-label {
              font-size: 14px;
              color: var(--el-text-color-secondary);
            }

            .risk-score-value {
              font-size: 16px;
              font-weight: 600;
              color: var(--el-text-color-primary);
              margin-left: 12px;
            }
          }

          .risk-description {
            p {
              margin: 0;
              font-size: 14px;
              line-height: 1.6;
              color: var(--el-text-color-regular);
            }
          }
        }
      }
    }

    // 星星脉冲动画
    @keyframes starPulse {
      0%, 100% {
        transform: scale(1);
      }
      50% {
        transform: scale(1.2);
      }
    }

    .module-content {
      .markdown-content {
        line-height: 1.6;
        
        :deep(h1), :deep(h2), :deep(h3) {
          margin: 16px 0 8px 0;
          color: var(--el-text-color-primary);
        }

        :deep(h1) { font-size: 24px; }
        :deep(h2) { font-size: 20px; }
        :deep(h3) { font-size: 16px; }
      }

      .json-content {
        pre {
          background: var(--el-fill-color-light);
          padding: 16px;
          border-radius: 8px;
          overflow-x: auto;
          font-size: 14px;
          line-height: 1.4;
        }
      }
    }
  }

  .error-container {
    padding: 48px 24px;
  }
}
</style>
