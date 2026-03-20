<template>
  <div class="batch-analysis">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-content">
        <div class="title-section">
          <h1 class="page-title">
            <el-icon class="title-icon"><Files /></el-icon>
            批量分析
          </h1>
          <p class="page-description">
            AI驱动的批量股票分析，高效处理多只股票
          </p>
        </div>
      </div>

      <!-- 风险提示 -->
      <div class="risk-disclaimer">
        <el-alert
          type="warning"
          :closable="false"
          show-icon
        >
          <template #title>
            <span style="font-size: 14px;">
              <strong>⚠️ 重要提示：</strong>本工具为股票分析辅助工具，所有分析结果仅供参考，不构成投资建议。投资有风险，决策需谨慎。
            </span>
          </template>
        </el-alert>
      </div>
    </div>

    <!-- 股票列表输入区域 -->
    <div class="analysis-container">
      <el-row :gutter="24">
        <el-col :span="24">
          <el-card class="stock-list-card" shadow="hover">
            <template #header>
              <div class="card-header">
                <h3>📋 股票列表</h3>
                <el-tag :type="stockCodes.length > 0 ? 'success' : 'info'" size="small">
                  {{ stockCodes.length }} 只股票
                </el-tag>
              </div>
            </template>

            <div class="stock-input-section">
              <div class="input-area">
                <el-input
                  v-model="stockInput"
                  type="textarea"
                  :rows="8"
                  placeholder="请输入股票代码，每行一个&#10;支持格式：&#10;000001&#10;000002.SZ&#10;600036.SH&#10;AAPL&#10;TSLA"
                  @input="parseStockCodes"
                  class="stock-textarea"
                />
                <div class="input-actions">
                  <el-button type="primary" @click="parseStockCodes" size="small">
                    解析股票代码
                  </el-button>
                  <el-button @click="clearStocks" size="small">清空</el-button>
                </div>
              </div>

              <!-- 股票预览 -->
              <div v-if="stockCodes.length > 0" class="stock-preview">
                <h4>股票预览</h4>
                <div class="stock-tags">
                  <el-tag
                    v-for="(code, index) in stockCodes.slice(0, 20)"
                    :key="code"
                    closable
                    @close="removeStock(index)"
                    class="stock-tag"
                  >
                    {{ code }}
                  </el-tag>
                  <el-tag v-if="stockCodes.length > 20" type="info">
                    +{{ stockCodes.length - 20 }} 更多...
                  </el-tag>
                </div>
              </div>

              <!-- 无效代码提示 -->
              <div v-if="invalidCodes.length > 0" class="invalid-codes">
                <el-alert
                  title="以下股票代码格式可能有误，请检查："
                  type="warning"
                  :closable="false"
                >
                  <div class="invalid-list">
                    <el-tag v-for="code in invalidCodes" :key="code" type="danger" size="small">
                      {{ code }}
                    </el-tag>
                  </div>
                </el-alert>
              </div>
            </div>
          </el-card>
        </el-col>
      </el-row>

      <!-- 分析配置区域 -->
      <el-row :gutter="24" style="margin-top: 24px;">
        <!-- 左侧：分析配置 -->
        <el-col :span="18">
          <el-card class="config-card" shadow="hover">
            <template #header>
              <div class="card-header">
                <h3>⚙️ 分析配置</h3>
                <el-tag type="primary" size="small">批量设置</el-tag>
              </div>
            </template>

            <el-form :model="batchForm" label-width="100px" class="batch-form">
              <!-- 基础信息 -->
              <div class="form-section">
                <h4 class="section-title">📋 基础信息</h4>
                <el-form-item label="批次标题" required>
                  <el-input
                    v-model="batchForm.title"
                    placeholder="如：银行板块分析"
                    size="large"
                  />
                </el-form-item>

                <el-form-item label="批次描述">
                  <el-input
                    v-model="batchForm.description"
                    type="textarea"
                    :rows="2"
                    placeholder="描述本次批量分析的目的和背景（可选）"
                  />
                </el-form-item>
              </div>

              <!-- 分析师选择 -->
              <div class="form-section">
                <h4 class="section-title">👥 分析师团队</h4>
                <div class="analysts-selection">
                  <el-checkbox-group v-model="batchForm.analysts" class="analysts-group">
                    <div
                      v-for="analyst in analysts"
                      :key="analyst.id"
                      class="analyst-option"
                    >
                      <el-checkbox :label="analyst.id" class="analyst-checkbox">
                        <div class="analyst-info">
                          <span class="analyst-name">
                            <el-icon style="margin-right: 4px; vertical-align: middle;">
                                <component :is="resolveIcon(analyst.icon)" />
                            </el-icon>
                            {{ analyst.name }}
                          </span>
                          <span class="analyst-desc">{{ analyst.description }}</span>
                        </div>
                      </el-checkbox>
                    </div>
                  </el-checkbox-group>
                </div>
              </div>

              <!-- 后续阶段配置 -->
              <div class="form-section">
                <div class="section-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                  <h4 class="section-title" style="margin: 0;">🚀 深度分析阶段</h4>
                  <div class="time-estimate" style="display: flex; align-items: center; gap: 6px; font-size: 14px; color: #666; background: #f0f9eb; padding: 4px 12px; border-radius: 12px; color: #67c23a;">
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
                            {{ agent }}
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
                    @click="submitBatchAnalysis"
                    :loading="submitting"
                    :disabled="stockCodes.length === 0"
                    class="submit-btn large-batch-btn"
                    style="width: 320px; height: 56px; font-size: 18px; font-weight: 700; border-radius: 16px;"
                  >
                    <el-icon><TrendCharts /></el-icon>
                    开始批量分析 ({{ stockCodes.length }}只)
                  </el-button>
                </div>
              </div>
            </el-form>
          </el-card>
        </el-col>

        <!-- 右侧：高级配置 -->
        <el-col :span="6">
          <el-card class="advanced-config-card" shadow="hover">
            <template #header>
              <div class="card-header">
                <h3>🔧 高级配置</h3>
              </div>
            </template>

            <div class="config-content">
              <!-- AI模型配置组件 -->
              <ModelConfig
                v-model:quick-analysis-model="modelSettings.quickAnalysisModel"
                v-model:deep-analysis-model="modelSettings.deepAnalysisModel"
                :available-models="availableModels"
                analysis-depth="标准"
              />

              <!-- 分析选项 -->
              <div class="config-section">
                <h4 class="config-title">⚙️ 分析选项</h4>
                <div class="analysis-options">
                  <div class="option-item">
                    <el-select v-model="batchForm.language" size="small" style="width: 100%">
                      <el-option label="中文" value="zh-CN" />
                      <el-option label="English" value="en-US" />
                    </el-select>
                    <div class="option-content">
                      <div class="option-name">语言偏好</div>
                    </div>
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

    <!-- 股票预览 -->
    <el-card v-if="stockCodes.length > 0" class="stock-preview-card" shadow="never">
      <template #header>
        <div class="card-header">
          <h3>股票预览 ({{ stockCodes.length }}只)</h3>
          <el-button type="text" @click="validateStocks">
            <el-icon><Check /></el-icon>
            验证股票代码
          </el-button>
        </div>
      </template>

      <div class="stock-grid">
        <div
          v-for="(code, index) in stockCodes"
          :key="index"
          class="stock-item"
          :class="{ invalid: invalidCodes.includes(code) }"
        >
          <span class="stock-code">{{ code }}</span>
          <el-button
            type="text"
            size="small"
            @click="removeStock(index)"
            class="remove-btn"
          >
            <el-icon><Close /></el-icon>
          </el-button>
        </div>
      </div>

      <div v-if="invalidCodes.length > 0" class="invalid-notice">
        <el-alert
          title="发现无效股票代码"
          type="warning"
          :description="`以下股票代码可能无效：${invalidCodes.join(', ')}`"
          show-icon
          :closable="false"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, watch, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { 
  Files, TrendCharts, Check, Close, Timer, Loading,
  Document, Histogram, ChatDotRound, DataAnalysis, Wallet, Money, InfoFilled, WarningFilled
} from '@element-plus/icons-vue'
import { normalizeAnalystIds } from '@/constants/analysts'
import { PHASES, estimateTotalTime } from '@/constants/phases'
import { configApi } from '@/api/config'
import { mcpApi } from '@/api/mcp'
import { agentConfigApi } from '@/api/agentConfigs'
import type { MCPTool } from '@/types/mcp'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import ModelConfig from '@/components/ModelConfig.vue'
import { getMarketByStockCode } from '@/utils/market'
import { validateStockCode } from '@/utils/stockValidator'

// 路由实例（必须在顶层调用）
const router = useRouter()
const route = useRoute()

// 分析师接口
interface Analyst {
  id: string
  name: string
  description: string
  icon: string
  slug: string
}

const submitting = ref(false)
const stockInput = ref('')
const stockCodes = ref<string[]>([])  // 保留用于表单绑定
const symbols = ref<string[]>([])     // 标准化后的代码列表
const invalidCodes = ref<string[]>([])

// 动态分析师列表
const analysts = ref<Analyst[]>([])
const loadingAnalysts = ref(false)

// 解决图标组件
const resolveIcon = (name: string) => {
  const icons: Record<string, any> = {
    Files, TrendCharts, Check, Close, Timer, Loading,
    Document, Histogram, ChatDotRound, DataAnalysis, Wallet, Money, InfoFilled, WarningFilled
  }
  return icons[name] || InfoFilled
}

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

// 获取分析师列表
const fetchAnalysts = async () => {
  loadingAnalysts.value = true
  try {
    const res = await agentConfigApi.getPhase(1)
    if (res.success && res.data && res.data.customModes) {
      analysts.value = res.data.customModes.map(mode => ({
        id: mode.slug, // 使用 slug 作为唯一标识
        name: mode.name,
        description: mode.description || mode.name,
        icon: getAnalystIcon(mode.slug),
        slug: mode.slug
      }))
      
      // 不设置硬编码默认值，保持用户选择
      if (batchForm.analysts.length === 0) {
        batchForm.analysts = []
      }
    } else {
      analysts.value = []
      batchForm.analysts = []
    }
  } catch (error) {
    console.error('Failed to fetch analysts:', error)
    analysts.value = []
    batchForm.analysts = []
  } finally {
    loadingAnalysts.value = false
  }
}

// 模型设置
const modelSettings = ref({
  quickAnalysisModel: 'qwen-turbo',
  deepAnalysisModel: 'qwen-max'
})

// 可用的模型列表（从配置中获取）
const availableModels = ref<any[]>([])

// MCP工具列表
const mcpTools = ref<MCPTool[]>([])
const loadingMcpTools = ref(false)

const batchForm = reactive({
  title: '',
  description: '',
  analysts: [] as string[],  // 将在 onMounted 中加载
  mcpTools: [] as string[],
  language: 'zh-CN',
  phases: {
    phase2: { enabled: false, debateRounds: 2 },
    phase3: { enabled: false, debateRounds: 1 },
    phase4: { enabled: true, debateRounds: 1 }
  }
})

// 辅助函数：安全获取阶段配置（避免模板中的类型索引问题）
const getPhaseConfig = (phaseName: string) => {
  return (batchForm.phases as Record<string, { enabled: boolean; debateRounds: number }>)[phaseName]
}

// 归一化阶段配置，确保后续阶段依赖前置阶段
const buildPhasePayload = (phases: any) => {
  const phase2Enabled = phases.phase2.enabled
  const phase3Enabled = phase2Enabled && phases.phase3.enabled
  // phase4 (Trader) is linked to phase2 (Debate) in UI now
  const phase4Enabled = phase2Enabled

  return {
    phase2_enabled: phase2Enabled,
    phase2_debate_rounds: phase2Enabled ? phases.phase2.debateRounds : 0,
    phase3_enabled: phase3Enabled,
    phase3_debate_rounds: phase3Enabled ? phases.phase3.debateRounds : 0,
    phase4_enabled: phase4Enabled,
    phase4_debate_rounds: 1
  }
}

// 估算总耗时
const estimatedTotalTime = computed(() => {
  // 批量分析总耗时 = 单只股票耗时 * 股票数量
  const perStockTime = estimateTotalTime(batchForm.phases)
  const stockCount = stockCodes.value.length || 1
  return perStockTime * stockCount
})

// 阶段开关级联：后续阶段需要前置阶段
watch(() => batchForm.phases.phase2.enabled, (enabled) => {
  if (!enabled) {
    batchForm.phases.phase3.enabled = false
  }
})

watch(() => batchForm.phases.phase3.enabled, (enabled) => {
  if (enabled && !batchForm.phases.phase2.enabled) {
    batchForm.phases.phase2.enabled = true
  }
})

// 使用通用校验器规范化代码，自动识别市场
const normalizeCodeSmart = (raw: string): { symbol?: string; error?: string } => {
  const code = String(raw || '').trim()
  if (!code) return { error: '空代码' }

  // 自动识别市场
  const v = validateStockCode(code)
  if (v.valid && v.normalizedCode) return { symbol: v.normalizedCode }

  return { error: v.message || '代码格式无效' }
}

const parseStockCodes = () => {
  const codes = stockInput.value
    .split('\n')
    .map(code => code.trim())
    .filter(code => code.length > 0)
    .filter((code, index, arr) => arr.indexOf(code) === index) // 去重

  const normalized: string[] = []
  const invalid: string[] = []
  for (const c of codes) {
    const { symbol } = normalizeCodeSmart(c)
    if (symbol) normalized.push(symbol)
    else invalid.push(c)
  }

  stockCodes.value = normalized
  symbols.value = [...normalized]
  invalidCodes.value = invalid
}

const clearStocks = () => {
  stockInput.value = ''
  stockCodes.value = []
  symbols.value = []
  invalidCodes.value = []
}

// 初始化模型设置
const initializeModelSettings = async () => {
  try {
    // 获取默认模型
    const defaultModels = await configApi.getDefaultModels()
    modelSettings.value.quickAnalysisModel = defaultModels.quick_analysis_model
    modelSettings.value.deepAnalysisModel = defaultModels.deep_analysis_model

    // 获取所有可用的模型列表
    const llmConfigs = await configApi.getLLMConfigs()
    availableModels.value = (llmConfigs as any).filter((config: any) => config.enabled)

    console.log('✅ 加载模型配置成功:', {
      quick: modelSettings.value.quickAnalysisModel,
      deep: modelSettings.value.deepAnalysisModel,
      available: availableModels.value.length
    })
  } catch (error) {
    console.error('加载默认模型配置失败:', error)
    // 使用硬编码的默认值
    modelSettings.value.quickAnalysisModel = 'qwen-turbo'
    modelSettings.value.deepAnalysisModel = 'qwen-max'
  }
}

// 页面初始化
onMounted(async () => {
  await fetchAnalysts()
  await initializeModelSettings()

  // 加载MCP工具
  loadingMcpTools.value = true
  try {
    const res = await mcpApi.listTools()
    if (res.success && res.data) {
      mcpTools.value = res.data
    }
  } catch (error) {
    console.error('❌ 加载MCP工具失败:', error)
  } finally {
    loadingMcpTools.value = false
  }

  // 🆕 从用户偏好加载默认设置
  const authStore = useAuthStore()
  const userPrefs = authStore.user?.preferences

  if (userPrefs) {
    // 加载默认分析师（兼容旧的中文名称数据，统一转换为英文ID）
    if (userPrefs.default_analysts && userPrefs.default_analysts.length > 0) {
      batchForm.analysts = normalizeAnalystIds([...userPrefs.default_analysts])
    }

    console.log('✅ 批量分析已加载用户偏好设置:', {
      analysts: batchForm.analysts
    })
  }

  // 读取路由查询参数以便从筛选页预填充（路由参数优先级最高）
  const q = route.query as any
  if (q?.stocks) {
    const parts = String(q.stocks).split(',').map((s) => s.trim()).filter(Boolean)
    stockCodes.value = parts
    stockInput.value = parts.join('\n')
    // 触发解析以更新 symbols
    parseStockCodes()
  }
})

const removeStock = (index: number) => {
  const removedCode = stockCodes.value[index]
  stockCodes.value.splice(index, 1)
  
  // 更新输入框
  stockInput.value = stockCodes.value.join('\n')
  
  // 从无效列表中移除
  const invalidIndex = invalidCodes.value.indexOf(removedCode)
  if (invalidIndex > -1) {
    invalidCodes.value.splice(invalidIndex, 1)
  }
}

const validateStocks = async () => {
  // 按当前市场重新规范化并验证
  const invalid: string[] = []
  const valid: string[] = []
  for (const c of stockCodes.value) {
    const { symbol } = normalizeCodeSmart(c)
    if (symbol) valid.push(symbol)
    else invalid.push(c)
  }
  stockCodes.value = valid
  symbols.value = [...valid]
  invalidCodes.value = invalid

  if (invalid.length === 0) {
    ElMessage.success('所有股票代码验证通过')
  } else {
    ElMessage.warning(`发现 ${invalid.length} 个无效股票代码`)
  }
}

const submitBatchAnalysis = async () => {
  if (!batchForm.title) {
    ElMessage.warning('请输入批次标题')
    return
  }

  if (stockCodes.value.length === 0) {
    ElMessage.warning('请输入股票代码')
    return
  }

  if (stockCodes.value.length > 10) {
    ElMessage.warning('单次批量分析最多支持10只股票，请减少股票数量')
    return
  }

  try {
    await ElMessageBox.confirm(
      `确定要提交批量分析任务吗？\n批次：${batchForm.title}\n股票数量：${stockCodes.value.length}只`,
      '确认提交',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'info'
      }
    )

    submitting.value = true

    // 准备批量分析请求参数（真实API调用）
    const phasePayload = buildPhasePayload(batchForm.phases)
    const batchRequest = {
      title: batchForm.title,
      description: batchForm.description,
      symbols: symbols.value,
      stock_codes: symbols.value,  // 兼容字段
      parameters: {
        // 若全部代码可识别为同一市场则携带；否则省略让后端自行判断
        market_type: (() => {
          const markets = new Set(symbols.value.map(s => getMarketByStockCode(s)))
          return markets.size === 1 ? Array.from(markets)[0] : undefined
        })(),
        selected_analysts: normalizeAnalystIds(batchForm.analysts), // 确保使用英文ID
        language: batchForm.language,
        quick_analysis_model: modelSettings.value.quickAnalysisModel,
        deep_analysis_model: modelSettings.value.deepAnalysisModel,

        // 阶段配置（按顺序依赖）
        ...phasePayload,
        // MCP工具
        mcp_tools: batchForm.mcpTools
      }
    }

    // 调用真实的批量分析API
    const { analysisApi } = await import('@/api/analysis')
    const response = await analysisApi.startBatchAnalysis(batchRequest)

    if (!response?.success) {
      throw new Error(response?.message || '批量分析提交失败')
    }

    const { batch_id, total_tasks } = response.data

    // 显示成功提示并引导用户去任务中心
    ElMessageBox.confirm(
      `✅ 批量分析任务已成功提交！\n\n📊 股票数量：${total_tasks}只\n📋 批次ID：${batch_id}\n\n任务正在后台执行中，最多同时执行3个任务，其他任务会自动排队等待。\n\n是否前往任务中心查看进度？`,
      '提交成功',
      {
        confirmButtonText: '前往任务中心',
        cancelButtonText: '留在当前页面',
        type: 'success',
        distinguishCancelAndClose: true,
        closeOnClickModal: false
      }
    ).then(() => {
      // 用户点击"前往任务中心"
      router.push({ path: '/tasks', query: { batch_id } })
    }).catch((action) => {
      // 用户点击"留在当前页面"或关闭对话框
      if (action === 'cancel') {
        ElMessage.info('任务正在后台执行，您可以随时前往任务中心查看进度')
      }
    })

  } catch (error: any) {
    // 处理错误
    if (error !== 'cancel') {
      ElMessage.error(error.message || '批量分析提交失败')
    }
  } finally {
    submitting.value = false
  }
}

// @ts-expect-error - reserved for future use
const _resetForm = () => {
  // 从用户偏好加载默认值
  const authStore = useAuthStore()
  const userPrefs = authStore.user?.preferences

  // 重置分析师：如果分析师列表已加载，使用默认逻辑
  let defaultAnalysts = [] as string[]
  if (userPrefs?.default_analysts) {
      defaultAnalysts = [...userPrefs.default_analysts]
  } else if (analysts.value.length > 0) {
      defaultAnalysts = analysts.value
          .filter(a => a.slug.includes('market') || a.slug.includes('fundamental'))
          .map(a => a.id)
  } else {
      defaultAnalysts = [] // 会由 fetchAnalysts 填充
  }

  Object.assign(batchForm, {
    title: '',
    description: '',
    analysts: defaultAnalysts,
    phases: {
      phase2: { enabled: false, debateRounds: 2 },
      phase3: { enabled: false, debateRounds: 1 },
      phase4: { enabled: true, debateRounds: 1 }
    }
  })
  clearStocks()
}

</script>

<style lang="scss" scoped>
.batch-analysis {
  min-height: 100vh;
  background: var(--el-bg-color-page);
  padding: 24px;

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
        color: #1a202c;
        margin: 0 0 8px 0;

        .title-icon {
          margin-right: 12px;
          color: #3b82f6;
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
    .stock-list-card, .config-card {
      border-radius: 16px;
      border: none;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);

      :deep(.el-card__header) {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
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

    // 右侧高级配置卡片样式
    .advanced-config-card {
      border-radius: 16px;
      border: none;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);

      :deep(.el-card__header) {
        background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
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

      .config-content {
        .config-section {
          margin-bottom: 24px;

          &:last-child {
            margin-bottom: 0;
          }

          .analysis-options {
            .option-item {
              display: flex;
              align-items: flex-start;
              gap: 12px;
              padding: 12px 0;
              border-bottom: 1px solid #f3f4f6;

              &:last-child {
                border-bottom: none;
                padding-bottom: 0;
              }

              .option-content {
                flex: 1;

                .option-name {
                  font-size: 14px;
                  font-weight: 500;
                  color: #374151;
                  margin-bottom: 2px;
                }

                .option-desc {
                  font-size: 12px;
                  color: #6b7280;
                }
              }
            }
          }
        }
      }
    }

    .stock-input-section {
      .input-area {
        margin-bottom: 24px;

        .stock-textarea {
          :deep(.el-textarea__inner) {
            border-radius: 12px;
            border: 2px solid #e2e8f0;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            font-size: 14px;
            line-height: 1.6;

            &:focus {
              border-color: #3b82f6;
              box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
            }
          }
        }

        .input-actions {
          margin-top: 12px;
          display: flex;
          gap: 12px;
        }
      }

      .stock-preview {
        h4 {
          font-size: 16px;
          font-weight: 600;
          color: #1a202c;
          margin: 0 0 12px 0;
        }

        .stock-tags {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;

          .stock-tag {
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            font-weight: 600;
          }
        }
      }

      .invalid-codes {
        margin-top: 16px;

        .invalid-list {
          margin-top: 8px;
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }
      }
    }

    .batch-form {
      .form-section {
        margin-bottom: 32px;

        .section-title {
          font-size: 16px;
          font-weight: 600;
          color: #1a202c;
          margin: 0 0 16px 0;
          padding-bottom: 8px;
          border-bottom: 2px solid #e2e8f0;
        }
      }

      .analysts-selection {
        .analysts-group {
          display: flex;
          flex-direction: column;
          gap: 12px;

          .analyst-option {
            .analyst-checkbox {
              width: 100%;

              :deep(.el-checkbox__label) {
                width: 100%;
              }

              :deep(.el-checkbox__input.is-checked .el-checkbox__inner) {
                background-color: #3b82f6;
                border-color: #3b82f6;
              }

              :deep(.el-checkbox__input.is-checked + .el-checkbox__label) {
                color: #3b82f6;
              }

              .analyst-info {
                display: flex;
                flex-direction: column;
                gap: 4px;

                .analyst-name {
                  font-weight: 500;
                  color: #374151;
                }

                .analyst-desc {
                  font-size: 12px;
                  color: #6b7280;
                }
              }
            }
          }
        }
      }
    }

    .action-section {
      margin-top: 24px !important;
      display: flex !important;
      justify-content: center !important;
      align-items: center !important;
      width: 100% !important;
      text-align: center !important;

      .submit-btn.el-button {
        width: 320px !important;
        height: 56px !important;
        font-size: 18px !important;
        font-weight: 700 !important;
        background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%) !important;
        border: none !important;
        border-radius: 16px !important;
        transition: all 0.3s ease !important;
        box-shadow: 0 4px 15px rgba(59, 130, 246, 0.2) !important;
        min-width: 320px !important;
        max-width: 320px !important;

        &:hover {
          transform: translateY(-3px) !important;
          box-shadow: 0 12px 30px rgba(59, 130, 246, 0.4) !important;
          background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%) !important;
        }

        &:disabled {
          opacity: 0.6 !important;
          transform: none !important;
          box-shadow: 0 4px 15px rgba(59, 130, 246, 0.1) !important;
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
        border-color: #3b82f6;
        box-shadow: 0 4px 12px rgba(59, 130, 246, 0.1);

        .phase-header .phase-title {
          color: #3b82f6;
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
            color: #1a202c;
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
}
</style>

<style>
/* 全局样式确保按钮样式生效 */
.action-section {
  display: flex !important;
  justify-content: center !important;
  align-items: center !important;
  width: 100% !important;
  text-align: center !important;
}

.large-batch-btn.el-button {
  width: 320px !important;
  height: 56px !important;
  font-size: 18px !important;
  font-weight: 700 !important;
  background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%) !important;
  border: none !important;
  border-radius: 16px !important;
  transition: all 0.3s ease !important;
  box-shadow: 0 4px 15px rgba(59, 130, 246, 0.2) !important;
  min-width: 320px !important;
  max-width: 320px !important;
}

.large-batch-btn.el-button:hover {
  transform: translateY(-3px) !important;
  box-shadow: 0 12px 30px rgba(59, 130, 246, 0.4) !important;
  background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%) !important;
}

.large-batch-btn.el-button:disabled {
  opacity: 0.6 !important;
  transform: none !important;
  box-shadow: 0 4px 15px rgba(59, 130, 246, 0.1) !important;
}

.large-batch-btn.el-button .el-icon {
  margin-right: 8px !important;
  font-size: 20px !important;
}

.large-batch-btn.el-button span {
  font-size: 18px !important;
  font-weight: 700 !important;
}
</style>
