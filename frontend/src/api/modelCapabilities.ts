/**
 * 模型能力管理 API
 */
import { ApiClient } from './request'

/**
 * 模型能力信息
 */
export interface ModelCapabilityInfo {
  model_name: string
  capability_level: number
  suitable_roles: string[]
  features: string[]
  recommended_depths: string[]
  performance_metrics?: {
    speed: number
    cost: number
    quality: number
  }
  description?: string
}

/**
 * 模型推荐响应
 */
export interface ModelRecommendationResponse {
  quick_model: string
  deep_model: string
  quick_model_info: ModelCapabilityInfo
  deep_model_info: ModelCapabilityInfo
  reason: string
}

/**
 * 模型验证响应
 */
export interface ModelValidationResponse {
  valid: boolean
  warnings: string[]
  recommendations: string[]
}

/**
 * 徽章样式
 */
export interface BadgeStyle {
  text: string
  color: string
  icon: string
}

/**
 * 所有徽章样式
 */
export interface AllBadges {
  capability_levels: Record<string, BadgeStyle>
  roles: Record<string, BadgeStyle>
  features: Record<string, BadgeStyle>
}

/**
 * 分析深度要求
 */
export interface DepthRequirement {
  min_capability: number
  quick_model_min: number
  deep_model_min: number
  required_features: string[]
  description: string
}

/**
 * 获取所有默认模型能力配置
 */
export function getDefaultModelConfigs() {
  return ApiClient.get('/api/model-capabilities/default-configs')
}

/**
 * 获取分析深度要求
 */
export function getDepthRequirements() {
  return ApiClient.get('/api/model-capabilities/depth-requirements')
}

/**
 * 获取能力等级描述
 */
export function getCapabilityDescriptions() {
  return ApiClient.get('/api/model-capabilities/capability-descriptions')
}

/**
 * 获取所有徽章样式
 */
export function getAllBadges() {
  return ApiClient.get('/api/model-capabilities/badges')
}

/**
 * 推荐模型
 * @param researchDepth 研究深度：快速/基础/标准/深度/全面
 */
export function recommendModels(researchDepth: string) {
  return ApiClient.post('/api/model-capabilities/recommend', {
    research_depth: researchDepth
  })
}

/**
 * 验证模型对
 * @param quickModel 快速模型
 * @param deepModel 深度模型
 * @param researchDepth 研究深度
 */
export function validateModels(quickModel: string, deepModel: string, researchDepth: string) {
  return ApiClient.post('/api/model-capabilities/validate', {
    quick_model: quickModel,
    deep_model: deepModel,
    research_depth: researchDepth
  })
}

/**
 * 批量初始化模型能力
 * @param overwrite 是否覆盖已有配置
 */
export function batchInitCapabilities(overwrite: boolean = false) {
  return ApiClient.post('/api/model-capabilities/batch-init', {
    overwrite
  })
}

/**
 * 获取指定模型的能力信息
 * @param modelName 模型名称
 */
export function getModelCapability(modelName: string) {
  return ApiClient.get(`/api/model-capabilities/model/${modelName}`)
}
