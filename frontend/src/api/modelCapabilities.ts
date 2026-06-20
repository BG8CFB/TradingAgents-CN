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
  analyst_model: string
  debate_model: string
  analyst_model_info: ModelCapabilityInfo
  debate_model_info: ModelCapabilityInfo
  reason: string
}

/**
 * 推荐模型
 */
export function recommendModels() {
  return ApiClient.post('/api/model-capabilities/recommend')
}

/**
 * 获取指定模型的能力信息
 * @param modelName 模型名称
 */
export function getModelCapability(modelName: string) {
  return ApiClient.get(`/api/model-capabilities/model/${modelName}`)
}
