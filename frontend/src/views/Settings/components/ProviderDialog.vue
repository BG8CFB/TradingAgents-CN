<template>
  <el-dialog
    :model-value="visible"
    :title="isEdit ? '编辑厂家信息' : '添加厂家'"
    width="520px"
    @update:model-value="handleVisibleChange"
    @close="handleClose"
  >
    <el-form
      ref="formRef"
      :model="formData"
      :rules="rules"
      label-width="100px"
    >
      <!-- 预设厂家选择 -->
      <el-form-item v-if="!isEdit" label="快速选择">
        <el-select
          v-model="selectedPreset"
          placeholder="选择预设厂家或手动填写"
          clearable
          @change="handlePresetChange"
          style="width: 100%"
        >
          <el-option
            v-for="preset in presetProviders"
            :key="preset.name"
            :label="preset.display_name"
            :value="preset.name"
          />
        </el-select>
      </el-form-item>

      <!-- 注册引导 -->
      <el-alert
        v-if="selectedPreset && currentPresetInfo?.register_url"
        :title="`${currentPresetInfo.display_name} 注册引导`"
        type="info"
        :closable="false"
        class="mb-4"
      >
        <template #default>
          <div class="register-guide">
            <p>{{ currentPresetInfo.register_guide || '如果您还没有账号，请先注册：' }}</p>
            <el-button type="primary" size="small" link @click="openRegisterUrl">
              <el-icon><Link /></el-icon>
              前往注册 {{ currentPresetInfo.display_name }}
            </el-button>
          </div>
        </template>
      </el-alert>

      <el-form-item label="厂家ID" prop="name">
        <el-input
          v-model="formData.name"
          placeholder="如: openai, anthropic"
          :disabled="isEdit"
        />
        <div class="form-tip">唯一标识符，创建后不可修改</div>
      </el-form-item>

      <el-form-item label="显示名称" prop="display_name">
        <el-input
          v-model="formData.display_name"
          placeholder="如: OpenAI, Anthropic"
        />
      </el-form-item>

      <el-form-item label="厂家类型" prop="provider_type">
        <el-radio-group v-model="formData.provider_type">
          <el-radio value="llm">大模型（对话/推理）</el-radio>
          <el-radio value="embedding">向量模型</el-radio>
        </el-radio-group>
        <div class="form-tip">大模型用于分析和推理，向量模型用于文本嵌入和检索</div>
      </el-form-item>

      <el-form-item label="默认API地址" prop="default_base_url">
        <el-input
          v-model="formData.default_base_url"
          placeholder="https://api.openai.com/v1"
        />
      </el-form-item>

      <el-form-item label="API Key" prop="api_key">
        <el-input
          v-model="formData.api_key"
          type="password"
          placeholder="输入 API Key（留空则使用环境变量）"
          show-password
          clearable
        />
        <div class="form-tip">
          留空则使用环境变量中的 Key
          <el-tag
            v-if="props.provider?.extra_config?.has_api_key"
            :type="props.provider?.extra_config?.source === 'environment' ? 'warning' : 'success'"
            size="small"
            class="ml-2"
          >
            {{ props.provider?.extra_config?.source === 'environment' ? 'ENV 已配置' : 'DB 已配置' }}
          </el-tag>
        </div>
      </el-form-item>

      <el-form-item v-if="needsApiSecret" label="API Secret" prop="api_secret">
        <el-input
          v-model="formData.api_secret"
          type="password"
          placeholder="输入 API Secret"
          show-password
          clearable
        />
        <div class="form-tip">某些厂家（如百度千帆）需要额外的 Secret Key</div>
      </el-form-item>

      <el-form-item label="启用状态">
        <el-switch
          v-model="formData.is_active"
          active-text="启用"
          inactive-text="禁用"
        />
      </el-form-item>

      <!-- 高级设置（折叠） -->
      <el-collapse class="advanced-collapse">
        <el-collapse-item title="高级设置（官网、文档地址等）" name="advanced">
          <el-form-item label="官网">
            <el-input v-model="formData.website" placeholder="https://openai.com" />
          </el-form-item>
          <el-form-item label="API文档">
            <el-input v-model="formData.api_doc_url" placeholder="https://platform.openai.com/docs" />
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
        <el-button type="primary" @click="handleSubmit" :loading="submitting">
          {{ isEdit ? '更新' : '添加' }}
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Link } from '@element-plus/icons-vue'
import type { FormInstance, FormRules } from 'element-plus'
import { configApi, type LLMProvider } from '@/api/config'

interface ProviderFormData extends Partial<LLMProvider> {
  api_key?: string
  api_secret?: string
  provider_type?: string
}

interface Props {
  visible: boolean
  provider?: Partial<LLMProvider>
}

const props = withDefaults(defineProps<Props>(), {
  provider: () => ({})
})

const emit = defineEmits<{
  'update:visible': [value: boolean]
  'success': []
}>()

const formRef = ref<FormInstance>()
const submitting = ref(false)
const selectedPreset = ref('')

const isEdit = computed(() => !!props.provider?.id)

const needsApiSecret = computed(() => {
  const providersNeedSecret = ['baidu', 'dashscope', 'qianfan']
  return providersNeedSecret.includes(formData.value.name || '')
})

const currentPresetInfo = computed(() => {
  if (!selectedPreset.value) return null
  return presetProviders.find(p => p.name === selectedPreset.value)
})

const openRegisterUrl = () => {
  if (currentPresetInfo.value?.register_url) {
    window.open(currentPresetInfo.value.register_url, '_blank')
  }
}

const presetProviders = [
  {
    name: 'dashscope',
    display_name: '阿里云百炼',
    description: '阿里云百炼大模型服务平台，提供通义千问等模型',
    website: 'https://bailian.console.aliyun.com',
    api_doc_url: 'https://help.aliyun.com/zh/dashscope/',
    default_base_url: 'https://dashscope.aliyuncs.com/api/v1',
    supported_features: ['chat', 'completion', 'embedding', 'function_calling', 'streaming'],
    provider_type: 'llm',
    register_url: 'https://account.aliyun.com/register/qr_register.htm',
    register_guide: '如果您还没有阿里云账号，请先注册并开通百炼服务：'
  },
  {
    name: '302ai',
    display_name: '302.AI',
    description: '302.AI是企业级AI聚合平台',
    website: 'https://302.ai',
    api_doc_url: 'https://doc.302.ai',
    default_base_url: 'https://api.302.ai/v1',
    supported_features: ['chat', 'completion', 'embedding', 'image', 'vision', 'function_calling', 'streaming'],
    provider_type: 'llm',
    register_url: 'https://share.302.ai/DUjftK',
    register_guide: '如果您还没有 302.AI 账号，请先注册并获取 API Key：'
  },
  {
    name: 'deepseek',
    display_name: 'DeepSeek',
    description: 'DeepSeek提供高性能的AI推理服务',
    website: 'https://www.deepseek.com',
    api_doc_url: 'https://platform.deepseek.com/api-docs',
    default_base_url: 'https://api.deepseek.com',
    supported_features: ['chat', 'completion', 'function_calling', 'streaming'],
    provider_type: 'llm',
    register_url: 'https://platform.deepseek.com/sign_up',
    register_guide: '如果您还没有 DeepSeek 账号，请先注册并获取 API Key：'
  },
  {
    name: 'openai',
    display_name: 'OpenAI',
    description: 'OpenAI，提供GPT系列模型',
    website: 'https://openai.com',
    api_doc_url: 'https://platform.openai.com/docs',
    default_base_url: 'https://api.openai.com/v1',
    supported_features: ['chat', 'completion', 'embedding', 'image', 'vision', 'function_calling', 'streaming'],
    provider_type: 'llm',
    register_url: 'https://platform.openai.com/signup',
    register_guide: '如果您还没有 OpenAI 账号，请先注册并获取 API Key：'
  },
  {
    name: 'anthropic',
    display_name: 'Anthropic',
    description: 'Anthropic，提供Claude系列模型',
    website: 'https://anthropic.com',
    api_doc_url: 'https://docs.anthropic.com',
    default_base_url: 'https://api.anthropic.com',
    supported_features: ['chat', 'completion', 'function_calling', 'streaming'],
    provider_type: 'llm',
    register_url: 'https://console.anthropic.com/signup',
    register_guide: '如果您还没有 Anthropic 账号，请先注册并获取 API Key：'
  },
  {
    name: 'google',
    display_name: 'Google AI',
    description: 'Google AI，提供Gemini系列模型',
    website: 'https://ai.google.dev',
    api_doc_url: 'https://ai.google.dev/docs',
    default_base_url: 'https://generativelanguage.googleapis.com/v1',
    supported_features: ['chat', 'completion', 'embedding', 'vision', 'function_calling', 'streaming'],
    provider_type: 'llm',
    register_url: 'https://makersuite.google.com/app/apikey',
    register_guide: '如果您还没有 Google AI 账号，请先登录并获取 API Key：'
  },
  {
    name: 'zhipu',
    display_name: '智谱AI',
    description: '智谱AI，提供GLM系列中文大模型',
    website: 'https://zhipuai.cn',
    api_doc_url: 'https://open.bigmodel.cn/doc',
    default_base_url: 'https://open.bigmodel.cn/api/paas/v4',
    supported_features: ['chat', 'completion', 'embedding', 'function_calling', 'streaming'],
    provider_type: 'llm',
    register_url: 'https://open.bigmodel.cn/login',
    register_guide: '如果您还没有智谱AI账号，请先注册并获取 API Key：'
  },
  {
    name: 'baidu',
    display_name: '百度智能云',
    description: '百度，提供文心一言等AI服务',
    website: 'https://cloud.baidu.com',
    api_doc_url: 'https://cloud.baidu.com/doc/WENXINWORKSHOP/index.html',
    default_base_url: 'https://aip.baidubce.com',
    supported_features: ['chat', 'completion', 'embedding', 'streaming'],
    provider_type: 'llm',
    register_url: 'https://login.bce.baidu.com/new-reg',
    register_guide: '如果您还没有百度智能云账号，请先注册并开通文心一言服务：'
  }
]

const formData = ref<ProviderFormData>({
  name: '',
  display_name: '',
  description: '',
  website: '',
  api_doc_url: '',
  default_base_url: '',
  api_key: '',
  api_secret: '',
  supported_features: [],
  provider_type: 'llm',
  is_active: true
})

const rules: FormRules = {
  name: [
    { required: true, message: '请输入厂家ID', trigger: 'blur' },
    { pattern: /^[a-z0-9_-]+$/, message: '只能包含小写字母、数字、下划线和连字符', trigger: 'blur' }
  ],
  display_name: [
    { required: true, message: '请输入显示名称', trigger: 'blur' }
  ],
  provider_type: [
    { required: true, message: '请选择厂家类型', trigger: 'change' }
  ]
}

const resetForm = () => {
  formData.value = {
    name: '',
    display_name: '',
    description: '',
    website: '',
    api_doc_url: '',
    default_base_url: '',
    api_key: '',
    api_secret: '',
    supported_features: [],
    provider_type: 'llm',
    is_active: true
  }
  selectedPreset.value = ''
}

watch(() => props.provider, (newProvider) => {
  if (newProvider && Object.keys(newProvider).length > 0) {
    const data = { ...newProvider } as any
    // 兼容旧数据：根据 supported_features 推导 provider_type
    if (!data.provider_type) {
      data.provider_type = (data.supported_features || []).includes('embedding') && !(data.supported_features || []).includes('chat')
        ? 'embedding'
        : 'llm'
    }
    // 编辑时不回填 API Key（后端返回的是截断值，不应覆盖真实值）
    // 用户填新值则更新，留空则不更新（后端会跳过）
    data.api_key = ''
    data.api_secret = ''
    formData.value = data
  } else {
    resetForm()
  }
}, { immediate: true, deep: true })

const handlePresetChange = (presetName: string) => {
  if (!presetName) return

  const preset = presetProviders.find(p => p.name === presetName)
  if (preset) {
    formData.value = {
      ...preset,
      is_active: true
    }
  }
}

const handleVisibleChange = (value: boolean) => {
  emit('update:visible', value)
}

const handleClose = () => {
  emit('update:visible', false)
  formRef.value?.resetFields()
}

const handleSubmit = async () => {
  try {
    await formRef.value?.validate()
    submitting.value = true

    const payload: any = { ...formData.value }

    // 根据厂家类型自动设置 supported_features
    if (payload.provider_type === 'embedding') {
      payload.supported_features = ['embedding']
    } else {
      payload.supported_features = ['chat', 'completion', 'function_calling', 'streaming']
    }
    delete payload.provider_type

    // 处理 API Key
    if ('api_key' in payload) {
      const apiKey = (payload.api_key || '').trim()
      if (!apiKey) {
        // 空字符串：编辑模式表示"不更新"，新增模式表示"不配置（fallback 到环境变量）"
        delete payload.api_key
      } else if (apiKey.includes('...') || apiKey.startsWith('your_') || apiKey.startsWith('your-')) {
        // 截断值/占位符：不更新，避免覆盖数据库中的真实密钥
        delete payload.api_key
      }
      // 否则是有效密钥，保留提交
    }

    // 处理 API Secret
    if ('api_secret' in payload) {
      const apiSecret = (payload.api_secret || '').trim()
      if (!apiSecret) {
        delete payload.api_secret
      } else if (apiSecret.includes('...') || apiSecret.startsWith('your_') || apiSecret.startsWith('your-')) {
        delete payload.api_secret
      }
    }

    let providerId: string | undefined

    if (isEdit.value) {
      await configApi.updateLLMProvider(formData.value.id!, payload)
      providerId = formData.value.id!
    } else {
      const result = await configApi.addLLMProvider(payload) as any
      providerId = result?.data?.id || result?.id
    }

    // 新增/编辑厂家后自动从 API 获取模型列表并写入模型目录
    if (!isEdit.value && providerId) {
      try {
        await configApi.fetchProviderModels(providerId)
        ElMessage.success('厂家添加成功，模型列表已自动获取')
      } catch {
        ElMessage.success('厂家添加成功（模型列表获取失败，可稍后在模型目录管理中刷新）')
      }
    } else if (isEdit.value) {
      // 编辑时也尝试刷新模型列表（用户可能更新了 API Key）
      try {
        await configApi.fetchProviderModels(formData.value.id!)
      } catch {
        // 静默失败，不影响用户操作
      }
      ElMessage.success('厂家信息更新成功')
    }

    emit('success')
    handleClose()
  } catch (error) {
    console.error('提交失败:', error)
    ElMessage.error(isEdit.value ? '更新失败' : '添加失败')
  } finally {
    submitting.value = false
  }
}
</script>

<style lang="scss" scoped>
.form-tip {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  margin-top: 4px;
}

.dialog-footer {
  text-align: right;
}

.mb-4 {
  margin-bottom: 16px;
}

.ml-2 {
  margin-left: 8px;
}

.register-guide {
  p {
    margin: 0 0 12px 0;
    font-size: 14px;
    line-height: 1.6;
    color: var(--el-text-color-regular);
  }

  :deep(.el-button) {
    font-size: 14px;
    padding: 8px 16px;
  }
}

.advanced-collapse {
  margin-top: 12px;
  border: none;

  :deep(.el-collapse-item__header) {
    background: var(--el-fill-color-lighter);
    padding: 0 12px;
    border-radius: 4px;
    border: none;
    font-weight: 500;
    color: var(--el-text-color-secondary);
    font-size: 13px;
  }

  :deep(.el-collapse-item__wrap) {
    border: none;
  }

  :deep(.el-collapse-item__content) {
    padding-top: 16px;
  }
}
</style>
