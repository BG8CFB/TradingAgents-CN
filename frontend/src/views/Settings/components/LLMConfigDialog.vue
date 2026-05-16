<template>
  <el-dialog
    :model-value="visible"
    :title="isEdit ? '编辑大模型配置' : '添加大模型配置'"
    width="640px"
    @update:model-value="handleVisibleChange"
    @close="handleClose"
  >
    <el-form
      ref="formRef"
      :model="formData"
      :rules="rules"
      label-width="110px"
    >
      <!-- 基础配置 -->
      <el-form-item label="供应商" prop="provider">
        <div style="display: flex; gap: 8px; align-items: flex-start; width: 100%;">
          <el-select
            v-model="formData.provider"
            placeholder="选择供应商"
            @change="handleProviderChange"
            :loading="providersLoading"
            style="flex: 1; min-width: 0;"
          >
            <el-option
              v-for="provider in availableProviders"
              :key="provider.name"
              :label="provider.display_name"
              :value="provider.name"
            />
          </el-select>
          <el-button
            :icon="Refresh"
            :loading="providersLoading"
            @click="() => loadProviders(true)"
            title="刷新供应商列表"
          />
        </div>
      </el-form-item>

      <el-form-item label="模型ID" prop="model_name">
        <div style="display: flex; gap: 8px; align-items: flex-start; width: 100%;">
          <el-select
            v-model="selectedModelKey"
            placeholder="选择模型或输入自定义模型ID"
            filterable
            clearable
            allow-create
            default-first-option
            @change="handleModelSelect"
            style="flex: 1; min-width: 0;"
          >
            <el-option
              v-for="model in modelOptions"
              :key="model.value"
              :label="model.label"
              :value="model.value"
            >
              <div style="display: flex; flex-direction: column;">
                <span>{{ model.label }}</span>
                <span style="font-size: 12px; color: #909399;">代码: {{ model.value }}</span>
              </div>
            </el-option>
          </el-select>
          <el-button
            :icon="Refresh"
            :loading="fetchingModels"
            :disabled="!formData.provider"
            @click="fetchModels"
            title="从厂家API获取最新模型列表"
          >
            获取模型
          </el-button>
        </div>
        <div class="form-tip">
          可从列表选择或直接输入模型ID（如 glm-4-flash、qwen-turbo）
        </div>
      </el-form-item>

      <el-form-item label="显示名称" prop="model_display_name">
        <el-input
          v-model="formData.model_display_name"
          placeholder="模型显示名称，如：Qwen3 Flash - 快速经济"
        />
      </el-form-item>

      <el-form-item label="用途" prop="suitable_roles">
        <el-checkbox-group v-model="formData.suitable_roles">
          <el-checkbox value="analyst">
            <span>快速分析</span>
            <span class="role-hint">数据收集、工具调用</span>
          </el-checkbox>
          <el-checkbox value="debate">
            <span>深度分析</span>
            <span class="role-hint">推理、决策</span>
          </el-checkbox>
        </el-checkbox-group>
        <div class="form-tip">不选则默认为"两者都适合"</div>
      </el-form-item>

      <el-form-item label="模型参数">
        <div style="display: flex; gap: 16px; width: 100%;">
          <div style="flex: 1;">
            <div class="param-label">最大Token</div>
            <el-input-number
              v-model="formData.max_tokens"
              :min="100"
              :max="maxTokensLimit"
              :step="100"
              style="width: 100%;"
            />
          </div>
          <div style="flex: 1;">
            <div class="param-label">温度</div>
            <el-input-number
              v-model="formData.temperature"
              :min="0"
              :max="2"
              :step="0.1"
              :precision="1"
              style="width: 100%;"
            />
          </div>
          <div style="flex: 1;">
            <div class="param-label">超时(秒)</div>
            <el-input-number
              v-model="formData.timeout"
              :min="10"
              :max="300"
              :step="10"
              style="width: 100%;"
            />
          </div>
        </div>
      </el-form-item>

      <!-- 高级设置（折叠） -->
      <el-collapse v-model="advancedOpen" class="advanced-collapse">
        <el-collapse-item title="高级设置" name="advanced">
          <el-form-item label="API地址" prop="api_base">
            <el-input
              v-model="formData.api_base"
              placeholder="可选，留空使用厂家默认地址"
            />
          </el-form-item>

          <el-form-item label="重试次数" prop="retry_times">
            <el-input-number
              v-model="formData.retry_times"
              :min="0"
              :max="10"
            />
          </el-form-item>

          <el-divider content-position="left">定价配置</el-divider>

          <el-form-item label="输入价格">
            <el-input-number
              v-model="formData.input_price_per_1k"
              :min="0"
              :step="0.0001"
              :controls="false"
              placeholder="每1000个token的价格"
            />
            <span class="ml-2 text-gray-500">{{ formData.currency || 'CNY' }}/1K tokens</span>
          </el-form-item>

          <el-form-item label="输出价格">
            <el-input-number
              v-model="formData.output_price_per_1k"
              :min="0"
              :step="0.0001"
              :controls="false"
              placeholder="每1000个token的价格"
            />
            <span class="ml-2 text-gray-500">{{ formData.currency || 'CNY' }}/1K tokens</span>
          </el-form-item>

          <el-form-item label="货币单位">
            <el-select v-model="formData.currency" placeholder="选择货币单位">
              <el-option label="人民币 (CNY)" value="CNY" />
              <el-option label="美元 (USD)" value="USD" />
              <el-option label="欧元 (EUR)" value="EUR" />
            </el-select>
          </el-form-item>

          <el-divider content-position="left">其他设置</el-divider>

          <el-form-item label="启用状态">
            <el-switch v-model="formData.enabled" />
          </el-form-item>

          <el-form-item label="优先级">
            <el-input-number
              v-model="formData.priority"
              :min="0"
              :max="100"
            />
            <span class="ml-2 text-gray-500">数值越大优先级越高</span>
          </el-form-item>

          <el-form-item label="描述">
            <el-input
              v-model="formData.description"
              type="textarea"
              :rows="2"
              placeholder="可选"
            />
          </el-form-item>
        </el-collapse-item>
      </el-collapse>
    </el-form>

    <template #footer>
      <div class="dialog-footer">
        <el-button @click="handleClose">取消</el-button>
        <el-button type="primary" @click="handleSubmit" :loading="loading">
          {{ isEdit ? '更新' : '添加' }}
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { configApi, type LLMProvider, type LLMConfig, validateLLMConfig } from '@/api/config'
import { getModelCapability } from '@/api/modelCapabilities'

interface Props {
  visible: boolean
  config?: LLMConfig | null
}

const props = withDefaults(defineProps<Props>(), {
  config: null
})

const emit = defineEmits<{
  'update:visible': [value: boolean]
  'success': []
}>()

const formRef = ref<FormInstance>()
const loading = ref(false)
const providersLoading = ref(false)
const fetchingModels = ref(false)
const availableProviders = ref<LLMProvider[]>([])
const advancedOpen = ref<string[]>([])
const autoFilledFields = ref<string[]>([])

const isEdit = computed(() => !!props.config)

const defaultFormData = {
  provider: '',
  model_name: '',
  model_display_name: '',
  api_base: '',
  max_tokens: 4000,
  temperature: 0.7,
  timeout: 180,
  retry_times: 3,
  enabled: true,
  enable_memory: false,
  enable_debug: false,
  priority: 0,
  model_category: '',
  description: '',
  input_price_per_1k: 0,
  output_price_per_1k: 0,
  currency: 'CNY',
  suitable_roles: [] as string[],
}

const formData = ref({ ...defaultFormData })
const selectedModelKey = ref<string>('')

const rules: FormRules = {
  provider: [{ required: true, message: '请选择供应商', trigger: 'change' }],
  model_name: [{ required: true, message: '请输入或选择模型', trigger: 'blur' }],
}

// 模型选项相关
interface ModelInfo {
  name: string
  display_name: string
  input_price_per_1k?: number | null
  output_price_per_1k?: number | null
  context_length?: number | null
  currency?: string
}

const modelOptions = ref<Array<{ label: string; value: string }>>([])
const modelCatalog = ref<Record<string, Array<ModelInfo>>>({})
const DEFAULT_MAX_TOKENS_LIMIT = 200000

const maxTokensLimit = computed(() => {
  const models = modelCatalog.value[formData.value.provider]
  if (!models) return DEFAULT_MAX_TOKENS_LIMIT
  const info = models.find(m => m.name === formData.value.model_name)
  if (info?.context_length && info.context_length > 0) return info.context_length
  return DEFAULT_MAX_TOKENS_LIMIT
})

const loadModelCatalog = async () => {
  try {
    const catalog = await configApi.getModelCatalog()
    const catalogMap: Record<string, ModelInfo[]> = {}
    ;(catalog as any).forEach((item: any) => {
      catalogMap[item.provider] = item.models
    })
    modelCatalog.value = catalogMap
  } catch {
    modelCatalog.value = {}
  }
}

const getModelOptions = (provider: string) => {
  const models = modelCatalog.value[provider]
  if (models && models.length > 0) {
    return models.map(m => ({
      label: m.display_name,
      value: m.name
    }))
  }
  return []
}

const getModelInfo = (provider: string, modelName: string): ModelInfo | null => {
  const models = modelCatalog.value[provider]
  if (!models) return null
  return models.find(m => m.name === modelName) || null
}

// 自动填充能力数据（从后端 DEFAULT_MODEL_CAPABILITIES）
const autoFillCapabilities = async (modelName: string) => {
  try {
    const resp = await getModelCapability(modelName) as any
    const data = resp?.data || resp
    if (data) {
      if (data.description && !formData.value.description) {
        formData.value.description = data.description
      }
    }
  } catch {
    autoFilledFields.value = []
  }
}

// 从厂家 API 获取最新模型列表
const fetchModels = async () => {
  if (!formData.value.provider) return
  const provider = availableProviders.value.find(p => p.name === formData.value.provider)
  if (!provider?.id) {
    ElMessage.warning('未找到该厂家的配置信息')
    return
  }

  fetchingModels.value = true
  try {
    const result = await configApi.fetchProviderModels(provider.id) as any
    if (result.success && result.models?.length > 0) {
      // 更新本地 modelCatalog 和下拉选项
      const models = result.models.map((m: any) => ({
        name: m.id || m.name,
        display_name: m.name || m.id,
        input_price_per_1k: m.input_price_per_1k ?? null,
        output_price_per_1k: m.output_price_per_1k ?? null,
        context_length: m.context_length ?? null,
        currency: m.currency || undefined,
      }))
      modelCatalog.value[formData.value.provider] = models
      modelOptions.value = models.map((m: any) => ({
        label: m.display_name,
        value: m.name,
      }))
      ElMessage.success(`获取到 ${models.length} 个模型`)
    } else {
      ElMessage.warning(result.message || '未获取到模型，请检查厂家 API 地址和密钥')
    }
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '获取模型列表失败')
  } finally {
    fetchingModels.value = false
  }
}

// 处理供应商变更
const handleProviderChange = async (provider: string) => {
  modelOptions.value = getModelOptions(provider)

  if (modelOptions.value.length === 0) {
    await loadModelCatalog()
    modelOptions.value = getModelOptions(provider)

    if (modelOptions.value.length > 0) {
      ElMessage.success(`已加载 ${modelOptions.value.length} 个可用模型`)
    }
  }

  formData.value.model_name = ''
  formData.value.input_price_per_1k = 0
  formData.value.output_price_per_1k = 0
  formData.value.currency = 'CNY'
  autoFilledFields.value = []
}

// 处理模型选择
const handleModelSelect = async (modelCode: string) => {
  if (!modelCode) {
    selectedModelKey.value = ''
    formData.value.model_name = ''
    return
  }

  // 无论列表选择还是自定义输入，都同步到 formData
  formData.value.model_name = modelCode

  const selectedModel = modelOptions.value.find(m => m.value === modelCode)
  if (selectedModel) {
    // 列表中存在的模型：自动填充显示名称、价格等
    formData.value.model_display_name = selectedModel.label

    const modelInfo = getModelInfo(formData.value.provider, modelCode)
    if (modelInfo) {
      if (modelInfo.input_price_per_1k !== undefined && modelInfo.input_price_per_1k !== null) {
        formData.value.input_price_per_1k = modelInfo.input_price_per_1k
      }
      if (modelInfo.output_price_per_1k !== undefined && modelInfo.output_price_per_1k !== null) {
        formData.value.output_price_per_1k = modelInfo.output_price_per_1k
      }
      if (modelInfo.currency) {
        formData.value.currency = modelInfo.currency
      }
    }

    await autoFillCapabilities(modelCode)
  } else {
    formData.value.model_display_name = modelCode
  }
}

// 监听配置变化
watch(
  () => props.config,
  (config) => {
    if (config) {
      formData.value = {
        ...defaultFormData,
        ...config,
        input_price_per_1k: config.input_price_per_1k ?? defaultFormData.input_price_per_1k,
        output_price_per_1k: config.output_price_per_1k ?? defaultFormData.output_price_per_1k,
        currency: config.currency || defaultFormData.currency,
        model_display_name: config.model_display_name || '',
        suitable_roles: config.suitable_roles || [],
      }
      modelOptions.value = getModelOptions(config.provider)
      if (config.model_name) {
        selectedModelKey.value = config.model_name
      }
      autoFilledFields.value = []
    } else {
      formData.value = { ...defaultFormData, suitable_roles: [] }
      modelOptions.value = []
      selectedModelKey.value = ''
      autoFilledFields.value = []
    }
  },
  { immediate: true }
)

watch(
  () => props.visible,
  async (visible) => {
    if (visible) {
      await Promise.all([loadProviders(), loadModelCatalog()])

      if (props.config) {
        formData.value = {
          ...defaultFormData,
          ...props.config,
          input_price_per_1k: props.config.input_price_per_1k ?? defaultFormData.input_price_per_1k,
          output_price_per_1k: props.config.output_price_per_1k ?? defaultFormData.output_price_per_1k,
          currency: props.config.currency || defaultFormData.currency,
          model_display_name: props.config.model_display_name || '',
          suitable_roles: props.config.suitable_roles || [],
        }
        modelOptions.value = getModelOptions(props.config.provider)
        if (props.config.model_name) {
          selectedModelKey.value = props.config.model_name
        }
      } else {
        formData.value = { ...defaultFormData, suitable_roles: [] }
        if (formData.value.provider) {
          modelOptions.value = getModelOptions(formData.value.provider)
        } else {
          modelOptions.value = []
        }
        selectedModelKey.value = ''
      }
      autoFilledFields.value = []
    }
  }
)

const handleVisibleChange = (value: boolean) => {
  emit('update:visible', value)
}

const handleClose = () => {
  emit('update:visible', false)
  formRef.value?.resetFields()
  advancedOpen.value = []
  autoFilledFields.value = []
}

const handleSubmit = async () => {
  if (!formRef.value) return

  try {
    await formRef.value.validate()

    const errors = validateLLMConfig(formData.value)
    if (errors.length > 0) {
      ElMessage.error(`配置验证失败: ${errors.join(', ')}`)
      return
    }

    loading.value = true

    // 处理 suitable_roles：如果两个都选了或都没选，设为 both
    if (formData.value.suitable_roles.includes('analyst') && formData.value.suitable_roles.includes('debate')) {
      formData.value.suitable_roles = ['both']
    } else if (formData.value.suitable_roles.length === 0) {
      formData.value.suitable_roles = ['both']
    }

    const submitData = { ...formData.value } as any

    if ('api_key' in submitData) {
      delete submitData.api_key
    }

    await configApi.updateLLMConfig(submitData)

    ElMessage.success(isEdit.value ? '模型配置更新成功' : '模型配置添加成功')
    emit('success')
    handleClose()
  } catch (error) {
    ElMessage.error(isEdit.value ? '模型配置更新失败' : '模型配置添加失败')
  } finally {
    loading.value = false
  }
}

const loadProviders = async (showSuccessMessage = false) => {
  providersLoading.value = true
  try {
    const providers = await configApi.getLLMProviders()
    availableProviders.value = (providers as any).filter((p: any) => p.is_active)

    if (showSuccessMessage) {
      ElMessage.success(`已刷新供应商列表，共 ${availableProviders.value.length} 个`)
    }

    if (!isEdit.value && !formData.value.provider && availableProviders.value.length > 0) {
      formData.value.provider = availableProviders.value[0].name
      await handleProviderChange(formData.value.provider)
    }
  } catch {
    ElMessage.error('加载厂家列表失败')
  } finally {
    providersLoading.value = false
  }
}

onMounted(() => {
  loadProviders()
  loadModelCatalog()
})
</script>

<style lang="scss" scoped>
.dialog-footer {
  text-align: right;
}

.ml-2 {
  margin-left: 8px;
}

.text-gray-500 {
  color: #6b7280;
  font-size: 12px;
}

.form-tip {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  margin-top: 4px;
}

.role-hint {
  font-size: 12px;
  color: #909399;
  margin-left: 4px;
}

.param-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 4px;
}

.auto-fill-notice {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--el-color-success-light-9);
  border-radius: 4px;
  margin-bottom: 16px;

  .auto-fill-text {
    font-size: 12px;
    color: var(--el-text-color-secondary);
  }
}

.advanced-collapse {
  margin-top: 16px;
  border: none;

  :deep(.el-collapse-item__header) {
    background: var(--el-fill-color-lighter);
    padding: 0 12px;
    border-radius: 4px;
    border: none;
    font-weight: 500;
    color: var(--el-text-color-secondary);
  }

  :deep(.el-collapse-item__wrap) {
    border: none;
  }

  :deep(.el-collapse-item__content) {
    padding-top: 16px;
  }
}

:deep(.el-select-dropdown__item) {
  height: auto;
  line-height: 1.5;
  padding: 8px 20px;

  span {
    display: inline-block;
  }
}
</style>
