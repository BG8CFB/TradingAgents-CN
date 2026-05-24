<template>
  <div class="model-config-component">
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
          <el-select v-model="localAnalystModel" size="small" style="width: 100%" filterable @change="onAnalystModelChange">
            <el-option
              v-for="model in availableModels"
              :key="`analyst-${model.provider}/${model.model_name}`"
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
                  <span style="font-size: 12px; color: var(--el-text-color-placeholder);">{{ model.provider }}</span>
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
          <el-select v-model="localDebateModel" size="small" style="width: 100%" filterable @change="onDebateModelChange">
            <el-option
              v-for="model in availableModels"
              :key="`debate-${model.provider}/${model.model_name}`"
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
                    v-if="isDebateRole(model.suitable_roles)"
                    type="warning"
                    size="small"
                    effect="plain"
                  >
                    🧠辩论
                  </el-tag>
                  <span style="font-size: 12px; color: var(--el-text-color-placeholder);">{{ model.provider }}</span>
                </div>
              </div>
            </el-option>
          </el-select>
        </div>
      </div>

      <!-- 🆕 模型推荐提示 -->
      <el-alert
        v-if="modelRecommendation"
        :title="modelRecommendation.title"
        :type="modelRecommendation.type"
        :closable="false"
        style="margin-top: 12px;"
      >
        <template #default>
          <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 12px;">
            <div style="font-size: 13px; line-height: 1.8; flex: 1; white-space: pre-line;">
              {{ modelRecommendation.message }}
            </div>
            <el-button
              v-if="modelRecommendation.analystModel && modelRecommendation.debateModel"
              type="primary"
              size="small"
              @click="applyRecommendedModels"
              style="flex-shrink: 0;"
            >
              应用推荐
            </el-button>
          </div>
        </template>
      </el-alert>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { InfoFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { recommendModels } from '@/api/modelCapabilities'

// Props
interface Props {
  analystModel: string
  debateModel: string
  availableModels: any[]
}

const props = defineProps<Props>()

// Emits
const emit = defineEmits<{
  'update:analystModel': [value: string]
  'update:debateModel': [value: string]
}>()

// Local state
const localAnalystModel = ref(props.analystModel)
const localDebateModel = ref(props.debateModel)

// 模型推荐提示
const modelRecommendation = ref<{
  title: string
  message: string
  type: 'success' | 'warning' | 'info' | 'error'
  analystModel?: string
  debateModel?: string
} | null>(null)

// Watch props changes
watch(() => props.analystModel, (newVal) => {
  localAnalystModel.value = newVal
})

watch(() => props.debateModel, (newVal) => {
  localDebateModel.value = newVal
})

// Emit changes
const onAnalystModelChange = (value: string) => {
  emit('update:analystModel', value)
}

const onDebateModelChange = (value: string) => {
  emit('update:debateModel', value)
}

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
 * 判断是否适合一阶段分析
 */
const isAnalystRole = (roles: string[] | undefined): boolean => {
  if (!roles || !Array.isArray(roles)) return false
  return roles.includes('analyst') || roles.includes('both')
}

/**
 * 判断是否适合辩论推理
 */
const isDebateRole = (roles: string[] | undefined): boolean => {
  if (!roles || !Array.isArray(roles)) return false
  return roles.includes('debate') || roles.includes('both')
}

/**
 * 检查模型适配性并提供推荐
 */
const checkModelSuitability = async () => {
  try {
    // 获取推荐模型
    const recommendRes = await recommendModels()
    const responseData = recommendRes?.data?.data

    if (responseData) {
      const analystModel = responseData.analyst_model || '未知'
      const debateModel = responseData.debate_model || '未知'

      // 获取模型的显示名称
      const analystModelInfo = props.availableModels.find(m => m.model_name === analystModel)
      const debateModelInfo = props.availableModels.find(m => m.model_name === debateModel)

      const analystDisplayName = analystModelInfo?.model_display_name || analystModel
      const debateDisplayName = debateModelInfo?.model_display_name || debateModel

      // 获取推荐理由
      const reason = responseData.reason || ''

      const message = `推荐模型配置：\n• 分析师模型：${analystDisplayName}\n• 辩论模型：${debateDisplayName}\n\n${reason}`

      modelRecommendation.value = {
        title: '💡 模型推荐',
        message,
        type: 'info',
        analystModel,
        debateModel
      }
    } else {
      modelRecommendation.value = {
        title: '💡 模型推荐',
        message: '推荐根据模型能力自动选择最佳模型配置',
        type: 'info'
      }
    }
  } catch (error) {
    console.error('获取模型推荐失败:', error)
  }
}

/**
 * 应用推荐的模型配置
 */
const applyRecommendedModels = () => {
  if (modelRecommendation.value?.analystModel && modelRecommendation.value?.debateModel) {
    localAnalystModel.value = modelRecommendation.value.analystModel
    localDebateModel.value = modelRecommendation.value.debateModel

    emit('update:analystModel', modelRecommendation.value.analystModel)
    emit('update:debateModel', modelRecommendation.value.debateModel)

    // 清除推荐提示
    modelRecommendation.value = null

    ElMessage.success('已应用推荐的模型配置')
  }
}

// 监听模型选择变化
watch([localAnalystModel, localDebateModel], () => {
  checkModelSuitability()
})

// 初始化
onMounted(() => {
  checkModelSuitability()
})
</script>

<style lang="scss" scoped>
.model-config-component {
  .config-section {
    margin-bottom: 24px;

    &:last-child {
      margin-bottom: 0;
    }

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

        &:last-child {
          margin-bottom: 0;
        }

        .model-label {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 8px;
          font-size: 13px;
          color: var(--el-text-color-regular);

          .help-icon {
            color: var(--el-text-color-placeholder);
            cursor: help;
          }
        }
      }
    }
  }
}
</style>

