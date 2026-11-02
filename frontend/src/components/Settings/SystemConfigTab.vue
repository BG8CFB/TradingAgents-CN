<template>
  <div>
    <el-card class="config-content" shadow="never">
      <template #header>
        <h3>系统设置</h3>
      </template>

      <el-alert type="info" show-icon :closable="false"
        title="敏感/ENV来源项已锁定"
        description="来自环境变量或标记为敏感的设置将以只读方式展示。保存时仅提交可编辑项。"
        style="margin-bottom: 12px;"
      />

      <el-form :model="systemSettings" label-width="150px" v-loading="systemLoading">
        <!-- 基础设置 -->
        <el-divider content-position="left">基础设置</el-divider>

        <el-form-item label="分析师模型">
          <el-select
            v-model="systemSettings.analyst_model"
            :disabled="!isEditable('analyst_model')"
            :placeholder="allEnabledModels.length ? '选择分析师模型（默认第一个启用模型）' : '未添加模型，请先在「模型配置」中添加'"
            filterable
          >
            <el-option
              v-for="model in allEnabledModels"
              :key="`${model.provider}/${model.model_name}`"
              :label="model.model_display_name || model.model_name"
              :value="model.model_name"
            >
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <span>{{ model.model_display_name || model.model_name }}</span>
                <el-tag size="small" type="info">{{ getProviderDisplayName(model.provider) }}</el-tag>
              </div>
            </el-option>
          </el-select>
          <div class="setting-description">用于一阶段分析师（市场分析、新闻分析等），低幻觉、数字敏感；未设置时默认使用第一个启用的模型</div>
        </el-form-item>

        <el-form-item label="辩论推理模型">
          <el-select
            v-model="systemSettings.debate_model"
            :disabled="!isEditable('debate_model')"
            :placeholder="allEnabledModels.length ? '选择辩论推理模型（默认第一个启用模型）' : '未添加模型，请先在「模型配置」中添加'"
            filterable
          >
            <el-option
              v-for="model in allEnabledModels"
              :key="`${model.provider}/${model.model_name}`"
              :label="model.model_display_name || model.model_name"
              :value="model.model_name"
            >
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <span>{{ model.model_display_name || model.model_name }}</span>
                <el-tag size="small" type="info">{{ getProviderDisplayName(model.provider) }}</el-tag>
              </div>
            </el-option>
          </el-select>
          <div class="setting-description">用于二至四阶段（辩论、风控、交易决策），强逻辑推理；未设置时默认使用第一个启用的模型</div>
        </el-form-item>

        <el-form-item label="启用成本跟踪">
          <el-switch v-model="systemSettings.enable_cost_tracking" :disabled="!isEditable('enable_cost_tracking')" />
        </el-form-item>

        <el-form-item label="成本警告阈值">
          <el-input-number v-model="systemSettings.cost_alert_threshold" :min="0" :step="10" :disabled="!isEditable('cost_alert_threshold')" />
          <span class="setting-description">元</span>
        </el-form-item>

        <el-form-item label="货币偏好">
          <el-select v-model="systemSettings.currency_preference" :disabled="!isEditable('currency_preference')">
            <el-option label="人民币 (CNY)" value="CNY" />
            <el-option label="美元 (USD)" value="USD" />
            <el-option label="欧元 (EUR)" value="EUR" />
          </el-select>
        </el-form-item>

        <el-form-item label="系统时区">
          <el-select v-model="systemSettings.app_timezone" :disabled="!isEditable('app_timezone')" filterable>
            <el-option label="Asia/Shanghai (UTC+8)" value="Asia/Shanghai" />
            <el-option label="UTC (UTC+0)" value="UTC" />
          </el-select>
          <div class="setting-description">用于后端存储与展示的统一时区；修改后新写入的时间将按此时区保存与返回。</div>
        </el-form-item>


        <!-- 性能设置 -->
        <el-divider content-position="left">性能设置</el-divider>

        <el-form-item label="分析超时时间">
          <el-input-number v-model="systemSettings.default_analysis_timeout" :min="60" :max="1800" :disabled="!isEditable('default_analysis_timeout')" />
          <span class="setting-description">秒</span>
        </el-form-item>

        <el-form-item label="启用缓存">
          <el-switch v-model="systemSettings.enable_cache" :disabled="!isEditable('enable_cache')" />
        </el-form-item>

        <el-form-item label="缓存TTL">
          <el-input-number v-model="systemSettings.cache_ttl" :min="300" :max="86400" :disabled="!isEditable('cache_ttl')" />
          <span class="setting-description">秒</span>
        </el-form-item>


        <!-- 队列与 Worker -->
        <el-divider content-position="left">队列与 Worker</el-divider>

        <el-form-item label="Worker 心跳间隔">
          <el-input-number v-model="systemSettings.worker_heartbeat_interval_seconds" :min="1" :step="1" :disabled="!isEditable('worker_heartbeat_interval_seconds')" />
          <span class="setting-description">秒</span>
          <el-tooltip effect="dark" content="Worker 心跳上报周期；过小会增加负载，过大可能影响健康检查" placement="top">
            <i class="el-icon-info" style="margin-left:8px; color:var(--el-text-color-placeholder);" />
          </el-tooltip>
        </el-form-item>

        <el-form-item label="队列轮询间隔">
          <el-input-number v-model="systemSettings.queue_poll_interval_seconds" :min="0.1" :step="0.1" :disabled="!isEditable('queue_poll_interval_seconds')" />
          <span class="setting-description">秒</span>
          <el-tooltip effect="dark" content="队列拉取任务的频率；过小增加Redis压力，过大影响任务延迟" placement="top">
            <i class="el-icon-info" style="margin-left:8px; color:var(--el-text-color-placeholder);" />
          </el-tooltip>
        </el-form-item>

        <el-form-item label="队列清理间隔">
          <el-input-number v-model="systemSettings.queue_cleanup_interval_seconds" :min="1" :step="1" :disabled="!isEditable('queue_cleanup_interval_seconds')" />
          <span class="setting-description">秒</span>
          <el-tooltip effect="dark" content="清理超时/失败任务的频率；建议≥60秒" placement="top">
            <i class="el-icon-info" style="margin-left:8px; color:var(--el-text-color-placeholder);" />
          </el-tooltip>
        </el-form-item>

        <!-- TradingAgents（可选） -->
        <el-divider content-position="left">TradingAgents（可选）</el-divider>
        <el-form-item label="使用 App 缓存优先">
          <el-switch v-model="systemSettings.ta_use_app_cache" :disabled="!isEditable('ta_use_app_cache')" />
          <div class="setting-description">优先使用 App 缓存（stock_basic_info / market_quotes），未命中自动回退直连数据源</div>
        </el-form-item>


        <el-form-item label="港股最小请求间隔">
          <el-input-number v-model="systemSettings.ta_hk_min_request_interval_seconds" :min="0.1" :step="0.1" :disabled="!isEditable('ta_hk_min_request_interval_seconds')" />
          <span class="setting-description">秒</span>
          <el-tooltip effect="dark" content="港股数据请求的最小间隔，用于节流" placement="top">
            <i class="el-icon-info" style="margin-left:8px; color:var(--el-text-color-placeholder);" />
          </el-tooltip>
        </el-form-item>

        <el-form-item label="港股请求超时">
          <el-input-number v-model="systemSettings.ta_hk_timeout_seconds" :min="1" :step="1" :disabled="!isEditable('ta_hk_timeout_seconds')" />
          <span class="setting-description">秒</span>
        </el-form-item>

        <el-form-item label="港股最大重试">
          <el-input-number v-model="systemSettings.ta_hk_max_retries" :min="0" :step="1" :disabled="!isEditable('ta_hk_max_retries')" />
        </el-form-item>

        <el-form-item label="港股限速等待">
          <el-input-number v-model="systemSettings.ta_hk_rate_limit_wait_seconds" :min="1" :step="1" :disabled="!isEditable('ta_hk_rate_limit_wait_seconds')" />
          <span class="setting-description">秒</span>
        </el-form-item>

        <el-form-item label="港股缓存TTL">
          <el-input-number v-model="systemSettings.ta_hk_cache_ttl_seconds" :min="10" :step="10" :disabled="!isEditable('ta_hk_cache_ttl_seconds')" />
          <span class="setting-description">秒</span>
        </el-form-item>

        <el-form-item label="A股最小调用间隔">
          <el-input-number v-model="systemSettings.ta_china_min_api_interval_seconds" :min="0.1" :step="0.1" :disabled="!isEditable('ta_china_min_api_interval_seconds')" />
          <span class="setting-description">秒</span>
        </el-form-item>

        <el-form-item label="美股最小调用间隔">
          <el-input-number v-model="systemSettings.ta_us_min_api_interval_seconds" :min="0.1" :step="0.1" :disabled="!isEditable('ta_us_min_api_interval_seconds')" />
          <span class="setting-description">秒</span>
        </el-form-item>

        <el-form-item label="GoogleNews最小延时">
          <el-input-number v-model="systemSettings.ta_google_news_sleep_min_seconds" :min="0.1" :step="0.1" :disabled="!isEditable('ta_google_news_sleep_min_seconds')" />
          <span class="setting-description">秒</span>
        </el-form-item>

        <el-form-item label="GoogleNews最大延时">
          <el-input-number v-model="systemSettings.ta_google_news_sleep_max_seconds" :min="0.1" :step="0.1" :disabled="!isEditable('ta_google_news_sleep_max_seconds')" />
          <span class="setting-description">秒</span>
        </el-form-item>

        <!-- 日志和监控 -->
        <el-divider content-position="left">日志和监控</el-divider>

        <el-form-item label="日志级别">
          <el-select v-model="systemSettings.log_level" :disabled="!isEditable('log_level')">
            <el-option label="DEBUG" value="DEBUG" />
            <el-option label="INFO" value="INFO" />
            <el-option label="WARNING" value="WARNING" />
            <el-option label="ERROR" value="ERROR" />
          </el-select>
        </el-form-item>

        <el-form-item label="启用监控">
          <el-switch v-model="systemSettings.enable_monitoring" :disabled="!isEditable('enable_monitoring')" />
        </el-form-item>

        <!-- 数据管理 -->
        <el-divider content-position="left">数据管理</el-divider>

        <el-form-item label="自动保存使用记录">
          <el-switch v-model="systemSettings.auto_save_usage" :disabled="!isEditable('auto_save_usage')" />
        </el-form-item>

        <el-form-item label="最大使用记录数">
          <el-input-number v-model="systemSettings.max_usage_records" :min="1000" :max="100000" :step="1000" :disabled="!isEditable('max_usage_records')" />
        </el-form-item>

        <el-form-item label="自动创建目录">
          <el-switch v-model="systemSettings.auto_create_dirs" :disabled="!isEditable('auto_create_dirs')" />
        </el-form-item>

        <!-- 选股与 AI 研判 -->
        <el-divider content-position="left">选股与 AI 研判</el-divider>

        <el-form-item label="每日自动研判">
          <el-switch
            v-model="systemSettings.screening_daily_insight_enabled"
            :disabled="!isEditable('screening_daily_insight_enabled')"
          />
          <span class="setting-description">
            开启后每日推荐生成时自动对默认策略 Top-20 做 AI 研判（消耗 token），默认关闭
          </span>
        </el-form-item>

        <el-form-item label="手动研判日配额">
          <el-input-number
            v-model="systemSettings.screening_manual_insight_daily_limit"
            :min="0"
            :max="100"
            :step="1"
            :disabled="!isEditable('screening_manual_insight_daily_limit')"
          />
          <span class="setting-description">次/用户/日（失败不扣减）</span>
        </el-form-item>

        <el-form-item label="研判模型">
          <el-select
            v-model="systemSettings.screening_insight_model"
            :disabled="!isEditable('screening_insight_model')"
            clearable
            filterable
            :placeholder="allEnabledModels.length ? '留空则用分析师默认模型' : '未添加模型，请先在「模型配置」中添加'"
          >
            <el-option
              v-for="model in allEnabledModels"
              :key="`${model.provider}/${model.model_name}`"
              :label="model.model_display_name || model.model_name"
              :value="model.model_name"
            >
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <span>{{ model.model_display_name || model.model_name }}</span>
                <el-tag size="small" type="info">{{ getProviderDisplayName(model.provider) }}</el-tag>
              </div>
            </el-option>
          </el-select>
        </el-form-item>

        <el-form-item label="研判系统提示词">
          <el-input
            v-model="systemSettings.screening_insight_prompt"
            type="textarea"
            :rows="6"
            :disabled="!isEditable('screening_insight_prompt')"
            placeholder="留空使用内置默认提示词（量化研究员角色：每只股票 2-3 句研判——核心逻辑 / 主要风险 / 适用风格，仅基于因子数据，禁止买卖建议，输出 JSON）"
          />
          <span class="setting-description">
            控制 AI 研判的角色与输出格式；修改后对新调用生效
          </span>
        </el-form-item>

        <!-- AI 问答助手 -->
        <el-divider content-position="left">AI 问答助手</el-divider>

        <el-form-item label="启用问答助手">
          <el-switch
            v-model="systemSettings.chat_enabled"
            :disabled="!isEditable('chat_enabled')"
          />
          <span class="setting-description">
            开启后可在「AI 选股助手」页对话式选股（每轮消耗 token），默认关闭
          </span>
        </el-form-item>

        <el-form-item label="每日问答配额">
          <el-input-number
            v-model="systemSettings.chat_daily_limit"
            :min="0"
            :max="200"
            :step="1"
            :disabled="!isEditable('chat_daily_limit')"
          />
          <span class="setting-description">轮/用户/日（仅成功的轮次计数，失败与停止不额外扣减）</span>
        </el-form-item>

        <el-form-item label="问答模型">
          <el-select
            v-model="systemSettings.chat_model"
            :disabled="!isEditable('chat_model')"
            clearable
            filterable
            :placeholder="allEnabledModels.length ? '留空则用分析师默认模型' : '未添加模型，请先在「模型配置」中添加'"
          >
            <el-option
              v-for="model in allEnabledModels"
              :key="`${model.provider}/${model.model_name}`"
              :label="model.model_display_name || model.model_name"
              :value="model.model_name"
            >
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <span>{{ model.model_display_name || model.model_name }}</span>
                <el-tag size="small" type="info">{{ getProviderDisplayName(model.provider) }}</el-tag>
              </div>
            </el-option>
          </el-select>
        </el-form-item>

        <el-form-item label="启用 MCP 工具">
          <el-switch
            v-model="systemSettings.chat_enable_mcp"
            :disabled="!isEditable('chat_enable_mcp')"
          />
          <span class="setting-description">开启后对话中可调用已配置的 MCP 服务器工具</span>
        </el-form-item>

        <el-form-item label="问答系统提示词">
          <el-input
            v-model="systemSettings.chat_system_prompt"
            type="textarea"
            :rows="6"
            :disabled="!isEditable('chat_system_prompt')"
            placeholder="留空使用内置默认提示词（A股选股助手：三层选股体系——今日推荐/策略选股/个股因子，先查数据再回答，每轮最多 6 次工具调用，禁止买卖指令，中文回答）"
          />
          <span class="setting-description">
            控制问答助手的角色、数据使用规则与安全边界；修改后对新轮次生效
          </span>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" @click="saveSystemSettings" :loading="systemSaving">
            保存设置
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import {
  configApi,
  type LLMProvider,
  type LLMConfig,
  type SettingMeta
} from '@/api/config'

// 响应式数据
const systemSettings = ref<Record<string, any>>({})
const systemSettingsMeta = ref<Record<string, SettingMeta>>({})
const systemLoading = ref(false)
const systemSaving = ref(false)

// 厂家与大模型配置（模型选择下拉框与默认模型回退依赖）
const providers = ref<LLMProvider[]>([])
const llmConfigs = ref<LLMConfig[]>([])

// 计算属性：所有启用的对话模型（跨厂家，用于系统设置中的模型选择；向量模型不参与）
const allEnabledModels = computed(() => {
  const activeProviderNames = new Set(providers.value.filter(p => p.is_active).map(p => p.name))
  return llmConfigs.value.filter(config =>
    config.enabled && config.model_type !== 'embedding' && activeProviderNames.has(config.provider))
})

// 加载厂家列表
const loadProviders = async () => {
  try {
    const providerListResp = await configApi.getLLMProviders()
    providers.value = Array.isArray(providerListResp) ? providerListResp : providerListResp.data
  } catch (error) {
    console.error('❌ 加载厂家列表失败:', error)
    ElMessage.error('加载厂家列表失败')
  }
}

// 加载大模型配置（本 tab 仅用于模型下拉选择，不构建分组）
const loadLLMConfigs = async () => {
  try {
    const configsResp = await configApi.getLLMConfigs()
    llmConfigs.value = Array.isArray(configsResp) ? configsResp : configsResp.data
  } catch (error) {
    console.error('❌ 加载大模型配置失败:', error)
    ElMessage.error('加载大模型配置失败')
  }
}

// 获取厂家显示名称
const getProviderDisplayName = (providerId: string) => {
  const provider = providers.value.find(p => p.name === providerId)
  return provider?.display_name || providerId
}

const loadSystemSettings = async () => {
  systemLoading.value = true
  try {
    const [response, meta] = await Promise.all([
      configApi.getSystemSettings(),
      configApi.getSystemSettingsMeta()
    ])

    // 🔧 修复：后端返回的是 {config: {...}, version, cached_at}，需要提取 config
    const settings = response.config || response

    // 确保有默认值
    systemSettings.value = {
      // 🔧 添加 default_provider 字段
      default_provider: '',
      analyst_model: '',
      debate_model: '',
      default_analysis_timeout: 300,
      enable_cache: true,
      cache_ttl: 3600,
      log_level: 'INFO',
      enable_monitoring: true,
      // 队列与 Worker 默认
      worker_heartbeat_interval_seconds: 30,
      queue_poll_interval_seconds: 1.0,
      queue_cleanup_interval_seconds: 60.0,
      // TradingAgents（可选）默认
      ta_use_app_cache: false,
      ta_hk_min_request_interval_seconds: 2.0,
      ta_hk_timeout_seconds: 60,
      ta_hk_max_retries: 3,
      ta_hk_rate_limit_wait_seconds: 60,
      ta_hk_cache_ttl_seconds: 86400,
      ta_china_min_api_interval_seconds: 0.5,
      ta_us_min_api_interval_seconds: 1.0,
      ta_google_news_sleep_min_seconds: 2.0,
      ta_google_news_sleep_max_seconds: 6.0,
      app_timezone: 'Asia/Shanghai',
      // 选股与 AI 研判（prompt 留空 = 使用后端内置默认提示词）
      screening_daily_insight_enabled: false,
      screening_manual_insight_daily_limit: 10,
      screening_insight_model: '',
      screening_insight_prompt: '',
      // AI 问答助手（prompt 留空 = 使用后端内置默认提示词）
      chat_enabled: false,
      chat_daily_limit: 20,
      chat_model: '',
      chat_enable_mcp: false,
      chat_system_prompt: '',

      ...settings
    }

    // 规整元数据为map
    const metaList = meta?.items || []
    systemSettingsMeta.value = Object.fromEntries(metaList.map((m: SettingMeta) => [m.key, m]))

    // 未显式设置默认模型时，自动选中第一个启用的模型（不写死具体模型 ID）
    const firstModel = allEnabledModels.value[0]?.model_name || ''
    if (!systemSettings.value.analyst_model && firstModel) {
      systemSettings.value.analyst_model = firstModel
    }
    if (!systemSettings.value.debate_model && firstModel) {
      systemSettings.value.debate_model = firstModel
    }
  } catch (error) {
    console.error('❌ 加载系统设置失败:', error)
    ElMessage.error('加载系统设置失败')
  } finally {
    systemLoading.value = false
  }
}

const isEditable = (key: string): boolean => {
  const meta = systemSettingsMeta.value[key]
  if (!meta) return true
  return !!meta.editable
}

const saveSystemSettings = async () => {
  systemSaving.value = true
  try {
    // 基本校验：这些数值需 > 0
    const positiveKeys: Array<{key: string; min: number}> = [
      { key: 'worker_heartbeat_interval_seconds', min: 1 },
      { key: 'queue_poll_interval_seconds', min: 0.000001 },
      { key: 'queue_cleanup_interval_seconds', min: 1 },
      // TradingAgents（可选）
      { key: 'ta_hk_min_request_interval_seconds', min: 0.000001 },
      { key: 'ta_hk_timeout_seconds', min: 1 },
      { key: 'ta_hk_max_retries', min: 0 },
      { key: 'ta_hk_rate_limit_wait_seconds', min: 1 },
      { key: 'ta_hk_cache_ttl_seconds', min: 1 },
      { key: 'ta_china_min_api_interval_seconds', min: 0.000001 },
      { key: 'ta_us_min_api_interval_seconds', min: 0.000001 },
      { key: 'ta_google_news_sleep_min_seconds', min: 0.000001 },
      { key: 'ta_google_news_sleep_max_seconds', min: 0.000001 },
    ]
    for (const { key, min } of positiveKeys) {
      const v = (systemSettings.value as any)[key]
      if (v !== undefined && v !== null && Number(v) <= min - Number.EPSILON && isEditable(key)) {
        ElMessage.error(`${key} 必须大于 ${min}`)
        systemSaving.value = false
        return
      }
    }
    // 额外：Google News 最大延时应大于最小延时
    const gMin = Number((systemSettings.value as any)['ta_google_news_sleep_min_seconds'])
    const gMax = Number((systemSettings.value as any)['ta_google_news_sleep_max_seconds'])
    if (!Number.isNaN(gMin) && !Number.isNaN(gMax) && isEditable('ta_google_news_sleep_max_seconds')) {
      if (gMax <= gMin) {
        ElMessage.error('ta_google_news_sleep_max_seconds 必须大于 ta_google_news_sleep_min_seconds')
        systemSaving.value = false
        return
      }
    }

    // 仅提交可编辑项
    const entries = Object.entries(systemSettings.value).filter(([k]) => isEditable(k))
    const payload = Object.fromEntries(entries)
    await configApi.updateSystemSettings(payload)
    ElMessage.success('系统设置保存成功')
  } catch (error) {
    ElMessage.error('系统设置保存失败')
  } finally {
    systemSaving.value = false
  }
}

// tab 激活时加载：系统设置需要厂家和大模型配置，用于模型选择下拉框
const load = async () => {
  await loadProviders()
  await loadLLMConfigs()
  await loadSystemSettings()
}

// 供父组件按 tab 懒加载
defineExpose({ reload: load })
</script>

<style lang="scss" scoped>
.config-content {
  min-height: 500px;

  .setting-description {
    margin-left: 8px;
    font-size: 12px;
    color: var(--el-text-color-placeholder);
  }
}
</style>
