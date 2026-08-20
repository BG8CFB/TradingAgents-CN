<template>
  <div class="single-analysis">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-content">
        <div class="title-section">
          <h1 class="page-title">
            <el-icon class="title-icon"><Document /></el-icon>
            单股分析
          </h1>
          <p class="page-description">
            AI驱动的智能股票分析，多维度评估投资价值与风险
          </p>
        </div>
      </div>
    </div>

    <!-- 进行中任务提示（点击跳转详情页） -->
    <el-alert
      v-if="runningTaskId"
      type="info"
      show-icon
      class="running-task-banner"
      @close="runningTaskId = ''"
    >
      <template #title>
        有进行中的分析任务，
        <el-link type="primary" :underline="false" @click="goToRunningTask">点击查看</el-link>
      </template>
    </el-alert>

    <!-- 主要分析表单 -->
    <div class="analysis-container">
      <el-row :gutter="24">
        <!-- 左侧：基础配置 -->
        <el-col :span="18">
          <el-card class="main-form-card" shadow="hover">
            <template #header>
              <div class="card-header">
                <h3>分析配置</h3>
                <el-tag type="info" size="small">必填信息</el-tag>
              </div>
            </template>

            <el-form :model="analysisForm" label-width="100px" class="analysis-form">
              <!-- 股票信息 -->
              <div class="form-section">
                <h4 class="section-title">📊 股票信息</h4>
                <el-row :gutter="16">
                  <el-col :span="12">
                    <el-form-item label="股票代码" required>
                      <el-input
                        v-model="analysisForm.stockCode"
                        placeholder="如：000001、AAPL、700、1810"
                        clearable
                        size="large"
                        class="stock-input"
                        :class="{ 'is-error': stockCodeError }"
                        @blur="validateStockCodeInput"
                        @input="onStockCodeInput"
                      >
                        <template #prefix>
                          <el-icon><TrendCharts /></el-icon>
                        </template>
                      </el-input>
                      <div v-if="stockCodeError" class="error-message">
                        <el-icon><WarningFilled /></el-icon>
                        {{ stockCodeError }}
                      </div>
                      <div v-else-if="stockCodeHelp" class="help-message">
                        <el-icon><InfoFilled /></el-icon>
                        {{ stockCodeHelp }}
                      </div>
                    </el-form-item>
                  </el-col>
                  <el-col :span="12">
                    <el-form-item label="市场类型">
                      <el-select
                        v-model="analysisForm.market"
                        placeholder="选择市场"
                        size="large"
                        style="width: 100%"
                        @change="onMarketChange"
                      >
                        <el-option label="🇨🇳 A股市场" value="A股">
                          <span>🇨🇳 A股市场</span>
                          <span style="color: #909399; font-size: 12px; margin-left: 8px;">（6位数字）</span>
                        </el-option>
                        <el-option label="🇺🇸 美股市场" value="美股">
                          <span>🇺🇸 美股市场</span>
                          <span style="color: #909399; font-size: 12px; margin-left: 8px;">（1-5个字母）</span>
                        </el-option>
                        <el-option label="🇭🇰 港股市场" value="港股">
                          <span>🇭🇰 港股市场</span>
                          <span style="color: #909399; font-size: 12px; margin-left: 8px;">（1-5位数字）</span>
                        </el-option>
                      </el-select>
                    </el-form-item>
                  </el-col>
                </el-row>

                <el-form-item label="分析日期">
                  <el-date-picker
                    v-model="analysisForm.analysisDate"
                    type="date"
                    placeholder="选择分析基准日期"
                    size="large"
                    style="width: 100%"
                    :disabled-date="disabledDate"
                  />
                </el-form-item>
              </div>

              <!-- 分析师团队 -->
              <div class="form-section">
                <h4 class="section-title">👥 分析师团队</h4>
                <div class="analysts-grid">
                  <div
                    v-for="analyst in analysts"
                    :key="analyst.id"
                    class="analyst-card"
                    :class="{ 
                      active: analysisForm.selectedAnalysts.includes(analyst.id)
                    }"
                    @click="toggleAnalyst(analyst.id)"
                  >
                    <div class="analyst-avatar">
                      <el-icon>
                        <component :is="resolveIcon(analyst.icon)" />
                      </el-icon>
                    </div>
                    <div class="analyst-content">
                      <div class="analyst-name">{{ analyst.name }}</div>
                      <div class="analyst-desc">{{ analyst.description }}</div>
                    </div>
                    <div class="analyst-check">
                      <el-icon v-if="analysisForm.selectedAnalysts.includes(analyst.id)" class="check-icon">
                        <Check />
                      </el-icon>
                    </div>
                  </div>
                </div>
                

              </div>

              <!-- 后续阶段配置 -->
              <div class="form-section">
                <div class="section-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                  <h4 class="section-title" style="margin: 0;">🚀 深度分析阶段</h4>
                  <div class="time-estimate" style="display: flex; align-items: center; gap: 6px; font-size: 14px; background: var(--el-color-success-light-9); padding: 4px 12px; border-radius: 12px; color: var(--el-color-success);">
                    <el-icon><Timer /></el-icon>
                    <span>预计总耗时: <strong>{{ estimatedTotalTime }}</strong> 分钟</span>
                  </div>
                </div>
                
                <div class="phases-grid">
                  <div 
                    v-for="phase in PHASES" 
                    :key="phase.id" 
                    class="phase-card"
                    :class="{ enabled: getPhaseConfig(phase.name)?.enabled }"
                  >
                    <div class="phase-header">
                      <div class="phase-title-row">
                        <div class="phase-title">{{ phase.title }}</div>
                        <el-switch
                          :model-value="getPhaseConfig(phase.name)?.enabled"
                          @update:model-value="(val: boolean | string | number) => { if (getPhaseConfig(phase.name)) getPhaseConfig(phase.name).enabled = val as boolean }"
                          :disabled="phase.id === 4"
                        />
                      </div>
                      <div class="phase-desc">{{ phase.description }}</div>
                    </div>

                    <div class="phase-body" v-if="getPhaseConfig(phase.name)?.enabled">
                      <div class="phase-agents">
                        <span class="label">参与角色:</span>
                        <div class="agent-tags">
                          <el-tag v-for="agent in phase.agents" :key="agent" size="small" type="info" effect="plain">
                            {{ stageAgentNames[agent] || agent }}
                          </el-tag>
                        </div>
                      </div>

                      <!-- 第四阶段固定执行1次，不显示辩论轮次设置 -->
                      <div class="phase-rounds" v-if="phase.hasDebateRounds !== false">
                        <span class="label">辩论轮次:</span>
                        <el-input-number
                          :model-value="getPhaseConfig(phase.name)?.debateRounds"
                          @update:model-value="(val: number | undefined) => { if (getPhaseConfig(phase.name)) getPhaseConfig(phase.name).debateRounds = val || 1 }"
                          :min="phase.minRounds"
                          :max="phase.maxRounds"
                          size="small"
                          controls-position="right"
                        />
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 操作按钮 -->
              <div class="form-section">
                <div class="action-buttons" style="display: flex; justify-content: center; align-items: center; width: 100%; text-align: center;">
                  <el-button
                    type="primary"
                    size="large"
                    @click="submitAnalysis"
                    :loading="submitting"
                    :disabled="!analysisForm.stockCode.trim()"
                    class="submit-btn large-analysis-btn"
                    style="width: 280px; height: 56px; font-size: 18px; font-weight: 700; border-radius: 16px;"
                  >
                    <el-icon><TrendCharts /></el-icon>
                    开始智能分析
                  </el-button>
                </div>
              </div>

            </el-form>
          </el-card>
        </el-col>

        <!-- 右侧：高级配置 -->
        <el-col :span="6">
          <el-card class="config-card" shadow="hover">
            <template #header>
              <div class="card-header">
                <h3>高级配置</h3>
                <el-tag type="warning" size="small">可选设置</el-tag>
              </div>
            </template>

            <div class="config-content">
              <!-- AI模型配置 -->
              <div class="config-section">
                <h4 class="config-title">🤖 AI模型配置</h4>
                <div class="model-config">
                  <div class="model-item">
                    <div class="model-label">
                      <span>分析师模型（一阶段）</span>
                      <el-tooltip content="用于一阶段分析师（市场分析、新闻分析、基本面分析等），推荐选择低幻觉、数字敏感的模型" placement="top">
                        <el-icon class="help-icon"><InfoFilled /></el-icon>
                      </el-tooltip>
                    </div>
                    <el-select v-model="modelSettings.analystModel" size="small" style="width: 100%" filterable>
                      <el-option
                        v-for="model in availableModels"
                        :key="`quick-${model.provider}/${model.model_name}`"
                        :label="model.model_display_name || model.model_name"
                        :value="model.model_name"
                      >
                        <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px;">
                          <span style="flex: 1;">{{ model.model_display_name || model.model_name }}</span>
                          <div style="display: flex; align-items: center; gap: 4px;">
                            <!-- 能力等级徽章 -->
                            <el-tag
                              v-if="model.capability_level"
                              :type="getCapabilityTagType(model.capability_level)"
                              size="small"
                              effect="plain"
                            >
                              {{ getCapabilityText(model.capability_level) }}
                            </el-tag>
                            <!-- 角色标签 -->
                            <el-tag
                              v-if="isAnalystRole(model.suitable_roles)"
                              type="success"
                              size="small"
                              effect="plain"
                            >
                              ⚡分析师
                            </el-tag>
                            <span style="font-size: 12px; color: #909399;">{{ model.provider }}</span>
                          </div>
                        </div>
                      </el-option>
                    </el-select>
                  </div>

                  <div class="model-item">
                    <div class="model-label">
                      <span>辩论推理模型（二至四阶段）</span>
                      <el-tooltip content="用于二至四阶段（辩论、风控、交易决策），推荐选择强逻辑推理能力的模型" placement="top">
                        <el-icon class="help-icon"><InfoFilled /></el-icon>
                      </el-tooltip>
                    </div>
                    <DeepModelSelector v-model="modelSettings.debateModel" :available-models="availableModels" type="debate" size="small" width="100%" />
                  </div>
                </div>
              </div>

              <!-- 分析选项 -->
              <div class="config-section">
                <h4 class="config-title">⚙️ 分析选项</h4>
                <div class="option-list">
                  <div class="option-item">
                    <div class="option-info">
                      <span class="option-name">语言偏好</span>
                    </div>
                    <el-select v-model="analysisForm.language" size="small" style="width: 100px">
                      <el-option label="中文" value="zh-CN" />
                      <el-option label="English" value="en-US" />
                    </el-select>
                  </div>
                </div>
              </div>

              <!-- MCP工具选择 (已移除，统一在设置中管理) -->
              <!-- <div class="config-section">
                <h4 class="config-title">🛠️ MCP工具</h4>
                 ...
              </div> -->

            </div>
          </el-card>
        </el-col>
      </el-row>

    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Document,
  TrendCharts,
  InfoFilled,
  Check,
  WarningFilled,
  Timer,
  DataAnalysis,
  ChatDotRound,
  Histogram,
  Money,
  Wallet,
} from '@element-plus/icons-vue'
import { analysisApi, type SingleAnalysisRequest } from '@/api/analysis'
import { stocksApi } from '@/api/stocks'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { configApi } from '@/api/config'
import { agentConfigApi } from '@/api/agentConfigs'
import { loadAgentDisplayNames } from '@/utils/agentDisplayNames'
import { mcpApi } from '@/api/mcp'
import type { MCPTool } from '@/types/mcp'
import DeepModelSelector from '@/components/DeepModelSelector.vue'
import { normalizeAnalystIds } from '@/constants/analysts'
import { PHASES, estimateTotalTime } from '@/constants/phases'
import { validateStockCode, getStockCodeFormatHelp } from '@/utils/stockValidator'
import { normalizeMarketForAnalysis, getMarketByStockCode } from '@/utils/market'

// 市场类型定义
type MarketType = 'A股' | '美股' | '港股'

// 分析师接口
interface Analyst {
  id: string
  name: string
  description: string
  icon: string
  slug: string
}

// 表单类型定义
interface AnalysisForm {
  stockCode: string
  symbol: string
  market: MarketType
  analysisDate: Date
  selectedAnalysts: string[]
  mcpTools: string[]
  language: 'zh-CN' | 'en-US'
  phases: {
    phase2: { enabled: boolean, debateRounds: number }
    phase3: { enabled: boolean, debateRounds: number }
    phase4: { enabled: boolean, debateRounds: number }
  }
}

// 使用store
const route = useRoute()
const router = useRouter()

const submitting = ref(false)

// 进行中任务提示（onMounted 轻量检查缓存发现 running 任务时展示，点击跳转详情页）
const runningTaskId = ref('')
const goToRunningTask = () => {
  if (runningTaskId.value) {
    router.push({ name: 'AnalysisTaskDetail', params: { taskId: runningTaskId.value } })
  }
}

// 动态分析师列表
const analysts = ref<Analyst[]>([])
const loadingAnalysts = ref(false)

// 分析师图标映射
const getAnalystIcon = (slug: string) => {
  const map: Record<string, string> = {
    'financial-news-analyst': 'Document',
    'china-market-analyst': 'TrendCharts',
    'market-analyst': 'Histogram',
    'social-media-analyst': 'ChatDotRound',
    'fundamentals-analyst': 'DataAnalysis',
    'short-term-capital-analyst': 'Wallet',
    'bull-researcher': 'TrendCharts',
    'bear-researcher': 'TrendCharts'
  }
  // 简单的启发式映射
  if (slug.includes('news')) return 'Document'
  if (slug.includes('market')) return 'TrendCharts'
  if (slug.includes('social')) return 'ChatDotRound'
  if (slug.includes('fund')) return 'DataAnalysis'
  if (slug.includes('capital')) return 'Wallet'
  
  return map[slug] || 'User'
}

// 阶段 2-4 报告显示名映射（后端配置统一构建，前端不写死智能体名称）
const stageAgentNames = ref<Record<string, string>>({})

// 获取分析师列表
const fetchAnalysts = async () => {
  loadingAnalysts.value = true
  try {
    // 并行拉取阶段1列表与全阶段显示名映射
    const [res, names] = await Promise.all([
      agentConfigApi.getPhase(1),
      loadAgentDisplayNames(),
    ])
    stageAgentNames.value = names
    if (res.success && res.data && res.data.customModes) {
      analysts.value = res.data.customModes.map(mode => ({
        id: mode.slug, // 使用 slug 作为唯一标识
        name: mode.name,
        description: mode.description || mode.name,
        icon: getAnalystIcon(mode.slug),
        slug: mode.slug
      }))
      // 不再设置硬编码默认值，保持用户选择
      if (analysisForm.selectedAnalysts.length === 0) {
        analysisForm.selectedAnalysts = []
      }
    } else {
      analysts.value = []
      analysisForm.selectedAnalysts = []
    }
  } catch (error) {
    console.error('Failed to fetch analysts:', error)
    analysts.value = []
    analysisForm.selectedAnalysts = []
  } finally {
    loadingAnalysts.value = false
  }
}

// 模型设置（初始为空，由后端设置或第一个启用模型填充）
const modelSettings = ref({
  analystModel: '',
  debateModel: ''
})

// 可用的模型列表（从配置中获取）
const availableModels = ref<{ model_name: string; model_display_name?: string; capability_level?: number; suitable_roles?: string[]; provider?: string }[]>([])

// MCP工具列表
const mcpTools = ref<MCPTool[]>([])
const loadingMcpTools = ref(false)

// 分析表单
const analysisForm = reactive<AnalysisForm>({
  stockCode: '',  // 保留用于表单绑定
  symbol: '',     // 标准化后的代码
  market: 'A股',
  analysisDate: new Date(),
  selectedAnalysts: [], // 将在 onMounted 中加载默认值
  mcpTools: [],
  language: 'zh-CN',
  phases: {
    phase2: { enabled: false, debateRounds: 2 },
    phase3: { enabled: false, debateRounds: 1 },
    phase4: { enabled: true, debateRounds: 1 }
  }
})

// 辅助函数：安全获取阶段配置（避免模板中的类型索引问题）
const getPhaseConfig = (phaseName: string) => {
  return (analysisForm.phases as Record<string, { enabled: boolean; debateRounds: number }>)[phaseName]
}

// 归一化阶段配置：交易员始终执行，阶段2/3 可独立开关
const buildPhasePayload = (phases: any) => {
  const phase2Enabled = phases.phase2.enabled
  const phase3Enabled = phases.phase3.enabled
  // 交易员始终执行，phase4 始终为 true
  const phase4Enabled = true

  return {
    phase2_enabled: phase2Enabled,
    phase2_debate_rounds: phase2Enabled ? phases.phase2.debateRounds : 0,
    phase3_enabled: phase3Enabled,
    phase3_debate_rounds: phase3Enabled ? phases.phase3.debateRounds : 0,
    phase4_enabled: phase4Enabled,
    phase4_debate_rounds: 1 // Default to 1 round for Trader
  }
}

// 股票代码验证相关
const stockCodeError = ref<string>('')
const stockCodeHelp = ref<string>('')

// 估算总耗时
const estimatedTotalTime = computed(() => {
  return estimateTotalTime(analysisForm.phases)
})

// 禁用日期
const disabledDate = (time: Date) => {
  return time.getTime() > Date.now()
}

// 股票代码输入时的处理
const onStockCodeInput = () => {
  // 清除错误信息
  stockCodeError.value = ''
  // 显示格式提示
  stockCodeHelp.value = getStockCodeFormatHelp(analysisForm.market)
}

// 市场类型变更时的处理
const onMarketChange = () => {
  // 重新验证股票代码
  if (analysisForm.stockCode.trim()) {
    validateStockCodeInput()
  } else {
    // 显示新市场的格式提示
    stockCodeHelp.value = getStockCodeFormatHelp(analysisForm.market)
  }
}

// 获取股票信息
const fetchStockInfo = async () => {
  const code = analysisForm.stockCode.trim()
  if (!code) return

  try {
    const res = await stocksApi.getQuote(code)
    if (!res.success || !res.data) {
      if (import.meta.env.DEV) console.warn('股票信息获取失败:', res.message)
    }
  } catch (error) {
    console.error('获取股票信息失败:', (error as any)?.message || error)
  }
}

// 验证股票代码输入
const validateStockCodeInput = () => {
  const code = analysisForm.stockCode.trim()

  if (!code) {
    stockCodeError.value = ''
    stockCodeHelp.value = ''
    return
  }

  // 验证股票代码格式
  const validation = validateStockCode(code, analysisForm.market)

  if (!validation.valid) {
    stockCodeError.value = validation.message || '股票代码格式不正确'
    stockCodeHelp.value = ''
  } else {
    stockCodeError.value = ''
    stockCodeHelp.value = `✓ ${validation.market}代码格式正确`

    // 自动更新市场类型（如果识别出的市场与当前选择不同）
    if (validation.market && validation.market !== analysisForm.market) {
      analysisForm.market = validation.market
      ElMessage.success(`已自动识别为${validation.market}`)
    }

    // 标准化代码
    if (validation.normalizedCode) {
      analysisForm.stockCode = validation.normalizedCode
    }
  }

  // 获取股票信息
  fetchStockInfo()
}

// 解决图标组件
const resolveIcon = (name: string) => {
  const icons: Record<string, any> = {
    Document, TrendCharts, Histogram, ChatDotRound, DataAnalysis, Wallet, Money, Check, InfoFilled, WarningFilled
  }
  return icons[name] || InfoFilled
}

// 页面初始化
onMounted(async () => {
  await fetchAnalysts()
  initializeModelSettings()

  // 加载模型配置
  try {
    const defaultModels = await configApi.getDefaultModels()
    modelSettings.value.analystModel = defaultModels.analyst_model
    modelSettings.value.debateModel = defaultModels.debate_model

    const llmConfigs = await configApi.getLLMConfigs()
    availableModels.value = (llmConfigs as any).filter((config: any) => config.enabled)
  } catch (error) {
    console.error('加载模型配置失败:', error)
  }

  // 加载MCP工具
  loadingMcpTools.value = true
  try {
    const res = await mcpApi.listTools()
    if (res.success && res.data) {
      mcpTools.value = res.data
    }
  } catch (error) {
    console.error('加载MCP工具失败:', error)
  } finally {
    loadingMcpTools.value = false
  }

  // 🆕 从用户偏好加载默认设置
  const authStore = useAuthStore()
  const appStore = useAppStore()

  // 优先从 authStore.user.preferences 读取，其次从 appStore.preferences 读取
  const userPrefs = authStore.user?.preferences
  if (userPrefs) {
    // 加载默认市场
    if (userPrefs.default_market) {
      analysisForm.market = userPrefs.default_market as MarketType
    }

    // 加载默认分析师（兼容旧的名称数据，统一规范化）
    if (userPrefs.default_analysts && userPrefs.default_analysts.length > 0) {
      analysisForm.selectedAnalysts = normalizeAnalystIds([...userPrefs.default_analysts])
    }
  } else {
    // 降级到 appStore.preferences
    if (appStore.preferences.defaultMarket) {
      analysisForm.market = appStore.preferences.defaultMarket as MarketType
    }
  }

  // 从用户偏好加载分析师选择 (如果有保存的偏好，且分析师列表已加载)
  if (authStore.user?.preferences?.default_analysts) {
    // 这里需要注意：用户偏好可能存的是旧的ID或名称，需要兼容
    // 简单起见，暂不覆盖 fetchAnalysts 中的默认逻辑，除非有明确映射
  }

  // 接收一次路由参数（从筛选页带入）- 路由参数优先级最高
  const q = route.query as any
  const hasNewStock = !!q?.stock
  if (hasNewStock) {
    analysisForm.stockCode = String(q.stock)
    // 🔥 关键修复：如果有新的股票代码，清除旧任务缓存
    clearTaskCache()
    console.log('🔄 检测到新股票代码，已清除旧任务缓存:', q.stock)

    // 🆕 自动识别市场类型（如果URL中没有明确指定market参数）
    if (!q?.market) {
      const detectedMarket = getMarketByStockCode(analysisForm.stockCode)
      analysisForm.market = detectedMarket as MarketType
    }
  }
  if (q?.market) analysisForm.market = normalizeMarketForAnalysis(q.market) as MarketType

  // 轻量检查：缓存中有进行中任务时仅显示提示条（不再原地恢复）
  if (!hasNewStock) {
    await checkRunningTaskFromCache()
  }
})

// 切换分析师
const toggleAnalyst = (analystId: string) => {
  const index = analysisForm.selectedAnalysts.indexOf(analystId)
  if (index > -1) {
    analysisForm.selectedAnalysts.splice(index, 1)
  } else {
    analysisForm.selectedAnalysts.push(analystId)
  }
}

// 提交分析
const submitAnalysis = async () => {
  const stockCode = analysisForm.stockCode.trim()
  if (!stockCode) {
    ElMessage.warning('请输入股票代码')
    return
  }

  // 验证股票代码格式
  const validation = validateStockCode(stockCode, analysisForm.market)
  if (!validation.valid) {
    ElMessage.error(validation.message || '股票代码格式不正确')
    stockCodeError.value = validation.message || '股票代码格式不正确'
    return
  }

  // 使用标准化后的代码
  analysisForm.symbol = validation.normalizedCode || stockCode.toUpperCase()

  if (analysisForm.selectedAnalysts.length === 0) {
    ElMessage.warning('请至少选择一个分析师')
    return
  }

  submitting.value = true

  try {
    // 确保 analysisDate 是 Date 对象
    const analysisDate = analysisForm.analysisDate instanceof Date
      ? analysisForm.analysisDate
      : new Date(analysisForm.analysisDate)

    const request: SingleAnalysisRequest = {
      symbol: analysisForm.symbol,
      stock_code: analysisForm.symbol,  // 兼容字段
      parameters: {
        market_type: analysisForm.market,
        analysis_date: analysisDate.toISOString().split('T')[0],
        selected_analysts: normalizeAnalystIds(analysisForm.selectedAnalysts), // 确保使用英文ID
        language: analysisForm.language,
        analyst_model: modelSettings.value.analystModel,
        debate_model: modelSettings.value.debateModel,
        // 阶段配置（按顺序依赖）
        ...buildPhasePayload(analysisForm.phases),
        // MCP工具
        mcp_tools: analysisForm.mcpTools
      }
    }

    const response = await analysisApi.startSingleAnalysis(request)

    ElMessage.success('分析任务已提交，正在处理中...')

    // 响应拦截器已返回 response.data，所以直接访问 response.data.task_id
    const taskId = response.data.task_id

    if (!taskId) {
      console.error('[Analysis] startAnalysis: 任务ID为空')
      ElMessage.error('任务ID获取失败，请重试')
      return
    }

    // 保存任务状态到缓存
    saveTaskToCache(taskId, {
      parameters: { ...analysisForm },
      submitTime: new Date().toISOString()
    })

    // 提交成功即跳转详情页（进度/结果/下载均在详情页展示）
    router.push({ name: 'AnalysisTaskDetail', params: { taskId } })

  } catch (error: any) {
    ElMessage.error(error.message || '提交分析失败')
  } finally {
    submitting.value = false
  }
}




// 初始化模型设置
const initializeModelSettings = async () => {
  try {
    // 获取默认模型
    const defaultModels = await configApi.getDefaultModels()
    modelSettings.value.analystModel = defaultModels.analyst_model
    modelSettings.value.debateModel = defaultModels.debate_model

    // 获取所有可用的模型列表
    const llmConfigs = await configApi.getLLMConfigs()
    availableModels.value = (llmConfigs as any).filter((config: any) => config.enabled)

    // 未设置默认模型时，回退到第一个启用的模型（不写死具体模型 ID）
    const firstModel = availableModels.value[0]?.model_name || ''
    if (!modelSettings.value.analystModel) modelSettings.value.analystModel = firstModel
    if (!modelSettings.value.debateModel) modelSettings.value.debateModel = firstModel

    if (import.meta.env.DEV) {
      console.log('加载模型配置成功:', {
        quick: modelSettings.value.analystModel,
        deep: modelSettings.value.debateModel,
        available: availableModels.value.length
      })
    }
  } catch (error) {
    console.error('加载默认模型配置失败:', (error as any)?.message || error)
    modelSettings.value.analystModel = ''
    modelSettings.value.debateModel = ''
  }
}

// 任务状态缓存管理（按用户隔离：未登录不读写缓存）
const TASK_CACHE_DURATION = 30 * 60 * 1000 // 30分钟

const taskCacheKey = () => {
  const userId = useAuthStore().user?.id
  return userId ? `trading_analysis_task:${userId}` : null
}

// 保存任务状态到缓存
const saveTaskToCache = (taskId: string, taskData: any) => {
  const key = taskCacheKey()
  if (!key) return
  const cacheData = {
    taskId,
    taskData,
    timestamp: Date.now()
  }
  localStorage.setItem(key, JSON.stringify(cacheData))
}

// 从缓存获取任务状态
const getTaskFromCache = () => {
  const key = taskCacheKey()
  if (!key) return null
  try {
    const cached = localStorage.getItem(key)
    if (!cached) return null

    const cacheData = JSON.parse(cached)
    const now = Date.now()

    // 检查是否过期（30分钟）
    if (now - cacheData.timestamp > TASK_CACHE_DURATION) {
      localStorage.removeItem(key)
      return null
    }

    return cacheData
  } catch (error) {
    console.error('❌ 读取缓存失败:', error)
    localStorage.removeItem(key)
    return null
  }
}

// 清除任务缓存
const clearTaskCache = () => {
  const key = taskCacheKey()
  if (key) localStorage.removeItem(key)
}

// 轻量检查缓存中的任务：仍在运行则显示提示条（跳转详情页），终态则清理缓存
const checkRunningTaskFromCache = async () => {
  const cached = getTaskFromCache()
  if (!cached) return

  try {
    const response = await analysisApi.getTaskStatus(cached.taskId)
    const status = response.data // 响应拦截器已返回 response.data
    if (['running', 'pending', 'processing'].includes(status?.status)) {
      runningTaskId.value = cached.taskId
    } else {
      // 终态任务在详情页/任务中心查看，此处不再恢复
      clearTaskCache()
    }
  } catch (error) {
    // 查询失败（任务可能已不存在），清理缓存
    clearTaskCache()
  }
}

// 🆕 模型能力相关辅助函数

/**
 * 获取能力等级文本
 */
const getCapabilityText = (level: number): string => {
  const texts: Record<number, string> = {
    1: '⚡基础',
    2: '📊标准',
    3: '🎯高级',
    4: '🔥专业',
    5: '👑旗舰'
  }
  return texts[level] || '📊标准'
}

/**
 * 获取能力等级标签类型
 */
const getCapabilityTagType = (level: number): 'success' | 'info' | 'warning' | 'danger' => {
  if (level >= 4) return 'danger'
  if (level >= 3) return 'warning'
  if (level >= 2) return 'success'
  return 'info'
}

/**
 * 判断是否适合快速分析
 */
const isAnalystRole = (roles: string[] | undefined): boolean => {
  if (!roles || !Array.isArray(roles)) return false
  return roles.includes('analyst') || roles.includes('both')
}

// 监听分析深度变化
import { watch } from 'vue'

// 阶段开关已独立：Phase 2（辩论）和 Phase 3（风险辩论）可分别开关，交易员始终执行

// 监听模型选择变化
watch([() => modelSettings.value.analystModel, () => modelSettings.value.debateModel], () => {
  // checkModelSuitability() // Removed
})
</script>

<style lang="scss" scoped>
.single-analysis {
  min-height: 100vh;
  background: var(--el-bg-color-page);
  padding: 24px;

  .running-task-banner {
    margin-bottom: 16px;
  }

  .page-header {
    margin-bottom: 32px;

    .header-content {
      background: var(--el-bg-color);
      padding: 32px;
      border-radius: 16px;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
    }

    .title-section {
      .page-title {
        display: flex;
        align-items: center;
        font-size: 32px;
        font-weight: 700;
        color: var(--el-text-color-primary);
        margin: 0 0 8px 0;

        .title-icon {
          margin-right: 12px;
          color: var(--el-color-primary);
        }
      }

      .page-description {
        font-size: 16px;
        color: #64748b;
        margin: 0;
      }
    }
  }

  .analysis-container {
    .main-form-card, .config-card {
      border-radius: 16px;
      border: none;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);

      :deep(.el-card__header) {
        background: linear-gradient(135deg, #C5A55A 0%, #9E7E3E 100%);
        color: white;
        border-radius: 16px 16px 0 0;
        padding: 20px 24px;

        .card-header {
          display: flex;
          justify-content: space-between;
          align-items: center;

          h3 {
            margin: 0;
            font-size: 18px;
            font-weight: 600;
          }
        }
      }

      :deep(.el-card__body) {
        padding: 24px;
      }
    }

    .analysis-form {
      .form-section {
        margin-bottom: 32px;
        width: 100%;
        display: flex;
        flex-direction: column;

        .section-title {
          font-size: 16px;
          font-weight: 600;
          color: var(--el-text-color-primary);
          margin: 0 0 16px 0;
          padding-bottom: 8px;
          border-bottom: 2px solid #e2e8f0;
        }
      }

      .stock-input {
        :deep(.el-input__inner) {
          font-weight: 600;
          text-transform: uppercase;
        }

        &.is-error {
          :deep(.el-input__inner) {
            border-color: #E57373;
          }
        }
      }

      .error-message {
        display: flex;
        align-items: center;
        gap: 4px;
        margin-top: 8px;
        font-size: 12px;
        color: #E57373;

        .el-icon {
          font-size: 14px;
        }
      }

      .help-message {
        display: flex;
        align-items: center;
        gap: 4px;
        margin-top: 8px;
        font-size: 12px;
        color: #7CB342;

        .el-icon {
          font-size: 14px;
        }
      }

      .prompt-helper {
        margin-top: 8px;
        color: #94a3b8;
        font-size: 12px;
      }

      .analysts-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
        gap: 16px;

        .analyst-card {
          display: flex;
          align-items: center;
          padding: 16px;
          border: 2px solid #e2e8f0;
          border-radius: 12px;
          cursor: pointer;
          transition: all 0.3s ease;

          &:hover {
            border-color: var(--el-color-primary);
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(197, 165, 90, 0.15);
          }

          &.active {
            border-color: var(--el-color-primary);
            background: linear-gradient(135deg, var(--el-color-primary-light-9) 0%, #f5edd6 100%);
            color: #7a6530;
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(197, 165, 90, 0.15);
          }

          &.disabled {
            opacity: 0.5;
            cursor: not-allowed;

            &:hover {
              transform: none;
              box-shadow: none;
              border-color: #e2e8f0;
            }
          }

          .analyst-avatar {
            width: 48px;
            height: 48px;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.2);
            display: flex;
            align-items: center;
            justify-content: center;
            margin-right: 16px;
            font-size: 20px;
          }

          .analyst-content {
            flex: 1;

            .analyst-name {
              font-weight: 600;
              margin-bottom: 4px;
            }

            .analyst-desc {
              font-size: 12px;
              opacity: 0.8;
            }
          }

          .analyst-check {
            .check-icon {
              font-size: 20px;
              color: var(--el-color-primary);
            }
          }

          &.active .analyst-check .check-icon {
            color: #7a6530;
          }
        }
      }
    }

    .config-card {
      .config-content {
        .config-section {
          margin-bottom: 24px;

          .config-title {
            font-size: 14px;
            font-weight: 600;
            color: var(--el-text-color-primary);
            margin: 0 0 12px 0;
            display: flex;
            align-items: center;
            gap: 8px;
          }

          .model-config {
            .model-item {
              margin-bottom: 16px;

              .model-label {
                display: flex;
                align-items: center;
                justify-content: space-between;
                margin-bottom: 8px;
                font-size: 13px;
                color: #374151;

                .help-icon {
                  color: #9ca3af;
                  cursor: help;
                }
              }
            }
          }

          .option-list {
            .option-item {
              display: flex;
              align-items: center;
              justify-content: space-between;
              padding: 12px 0;
              border-bottom: 1px solid #f3f4f6;

              &:last-child {
                border-bottom: none;
              }

              .option-info {
                .option-name {
                  font-size: 14px;
                  font-weight: 500;
                  color: #374151;
                  display: block;
                  margin-bottom: 2px;
                }

                .option-desc {
                  font-size: 12px;
                  color: #6b7280;
                }
              }
            }
          }

          .custom-input {
            :deep(.el-textarea__inner) {
              border-radius: 8px;
              border: 1px solid #d1d5db;

              &:focus {
                border-color: #C5A55A;
                box-shadow: 0 0 0 3px rgba(197, 165, 90, 0.1);
              }
            }
          }

          .input-help {
            font-size: 12px;
            color: #6b7280;
            margin-top: 8px;
          }

          .action-buttons {
            display: flex !important;
            justify-content: center !important;
            align-items: center !important;
            margin-top: 24px !important;
            width: 100% !important;
            text-align: center !important;

            .submit-btn.el-button {
              width: 280px !important;
              height: 56px !important;
              font-size: 18px !important;
              font-weight: 700 !important;
              background: linear-gradient(135deg, #C5A55A 0%, #9E7E3E 100%) !important;
              border: none !important;
              border-radius: 16px !important;
              transition: all 0.3s ease !important;
              box-shadow: 0 4px 15px rgba(197, 165, 90, 0.2) !important;
              min-width: 280px !important;
              max-width: 280px !important;

              &:hover {
                transform: translateY(-3px) !important;
                box-shadow: 0 12px 30px rgba(197, 165, 90, 0.4) !important;
                background: linear-gradient(135deg, #C5A55A 0%, #9E7E3E 100%) !important;
              }

              &:disabled {
                opacity: 0.6 !important;
                transform: none !important;
                box-shadow: 0 4px 15px rgba(197, 165, 90, 0.1) !important;
              }

              .el-icon {
                margin-right: 8px !important;
                font-size: 20px !important;
              }

              span {
                font-size: 18px !important;
                font-weight: 700 !important;
              }
            }
          }
        }
      }
    }

    .action-section {
      margin-top: 24px;
      display: flex;
      gap: 16px;

      .submit-btn {
        flex: 1;
        height: 48px;
        font-size: 16px;
        font-weight: 600;
        background: linear-gradient(135deg, #C5A55A 0%, #9E7E3E 100%);
        border: none;
        border-radius: 12px;
        transition: all 0.3s ease;

        &:hover {
          transform: translateY(-2px);
          box-shadow: 0 8px 25px rgba(197, 165, 90, 0.3);
        }

        &:disabled {
          opacity: 0.6;
          transform: none;
          box-shadow: none;
        }
      }

      .reset-btn {
        height: 48px;
        font-size: 16px;
        border-radius: 12px;
        border: 2px solid #e5e7eb;
        color: #6b7280;
        transition: all 0.3s ease;

        &:hover {
          border-color: #d1d5db;
          color: #374151;
          transform: translateY(-1px);
        }
      }
    }
  }
}

/* 阶段配置样式 */
.phases-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 16px;

  .phase-card {
    border: 2px solid #e2e8f0;
    border-radius: 12px;
    padding: 16px;
    transition: all 0.3s ease;
    background: #f8fafc;

    &:hover {
      border-color: #cbd5e1;
      transform: translateY(-2px);
    }

    &.enabled {
      background: #fff;
      border-color: #C5A55A;
      box-shadow: 0 4px 12px rgba(197, 165, 90, 0.1);

      .phase-header .phase-title {
        color: #C5A55A;
      }
    }

    .phase-header {
      margin-bottom: 12px;

      .phase-title-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 8px;

        .phase-title {
          font-weight: 600;
          font-size: 15px;
          color: var(--el-text-color-primary);
        }
      }

      .phase-desc {
        font-size: 12px;
        color: #64748b;
        line-height: 1.5;
        min-height: 36px;
      }
    }

    .phase-body {
      padding-top: 12px;
      border-top: 1px solid #e2e8f0;
      animation: fadeIn 0.3s ease;

      .phase-agents {
        margin-bottom: 12px;

        .label {
          font-size: 12px;
          color: #64748b;
          margin-bottom: 6px;
          display: block;
        }

        .agent-tags {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }
      }

      .phase-rounds {
        display: flex;
        justify-content: space-between;
        align-items: center;

        .label {
          font-size: 12px;
          color: #64748b;
        }
      }
    }
  }
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(-5px); }
  to { opacity: 1; transform: translateY(0); }
}

</style>

<style>
/* 全局样式确保按钮样式生效 */
.action-buttons {
  display: flex !important;
  justify-content: center !important;
  align-items: center !important;
  width: 100% !important;
  text-align: center !important;
}

.large-analysis-btn.el-button {
  width: 280px !important;
  height: 56px !important;
  font-size: 18px !important;
  font-weight: 700 !important;
  background: linear-gradient(135deg, #C5A55A 0%, #9E7E3E 100%) !important;
  border: none !important;
  border-radius: 16px !important;
  transition: all 0.3s ease !important;
  box-shadow: 0 4px 15px rgba(197, 165, 90, 0.2) !important;
  min-width: 280px !important;
  max-width: 280px !important;
}

.large-analysis-btn.el-button:hover {
  transform: translateY(-3px) !important;
  box-shadow: 0 12px 30px rgba(197, 165, 90, 0.4) !important;
  background: linear-gradient(135deg, #C5A55A 0%, #9E7E3E 100%) !important;
}

.large-analysis-btn.el-button:disabled {
  opacity: 0.6 !important;
  transform: none !important;
  box-shadow: 0 4px 15px rgba(197, 165, 90, 0.1) !important;
}

.large-analysis-btn.el-button .el-icon {
  margin-right: 8px !important;
  font-size: 20px !important;
}

.large-analysis-btn.el-button span {
  font-size: 18px !important;
  font-weight: 700 !important;
}

</style>
