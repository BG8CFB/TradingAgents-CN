/**
 * 配置管理API
 */

import { ApiClient, type ApiResponse } from './request'

// 配置相关类型定义

// 大模型厂家
export interface LLMProvider {
  id: string
  name: string
  display_name: string
  description?: string
  website?: string
  api_doc_url?: string
  logo_url?: string
  is_active: boolean
  supported_features: string[]
  default_base_url?: string
  protocol?: string  // 请求协议: openai / anthropic，留空按厂家名自动推断
  extra_config?: {
    has_api_key?: boolean
    source?: 'environment' | 'database'
    [key: string]: any
  }
  // 🆕 聚合渠道支持
  is_aggregator?: boolean
  aggregator_type?: string
  model_name_format?: string
  created_at?: string
  updated_at?: string
}

export interface LLMConfig {
  provider: string
  model_name: string
  model_display_name?: string  // 新增：模型显示名称
  api_key?: string  // 可选，优先从厂家配置获取
  api_base?: string
  max_tokens: number
  context_window?: number | null  // 上下文窗口（输入侧，与 max_tokens 单次输出上限是两个概念；留空继承模型目录）
  temperature: number
  thinking_budget?: number | null  // 推理思考预算（Anthropic opt-in；>0 开启，留空不开启；OpenAI 兼容协议忽略）
  timeout: number
  retry_times: number
  enabled: boolean
  description?: string
  // 定价配置
  input_price_per_1k?: number
  output_price_per_1k?: number
  currency?: string
  // 高级配置
  enable_memory?: boolean
  enable_debug?: boolean
  priority?: number
  model_category?: string
  // 🆕 模型能力分级系统
  capability_level?: number  // 模型能力等级(1-5): 1=基础, 2=标准, 3=高级, 4=专业, 5=旗舰
  suitable_roles?: string[]  // 适用角色: analyst(一阶段分析师), debate(辩论推理), both(两者都适合)
  features?: string[]  // 模型特性: tool_calling, long_context, reasoning, vision, fast_response, cost_effective
  recommended_depths?: string[]  // 推荐的分析深度级别: 快速, 基础, 标准, 深度, 全面
  performance_metrics?: {  // 性能指标
    speed?: number  // 速度(1-5)
    cost?: number  // 成本(1-5)
    quality?: number  // 质量(1-5)
  }
}

export interface DataSourceConfig {
  name: string
  type: string
  api_key?: string
  api_secret?: string
  endpoint?: string
  timeout: number
  rate_limit: number
  enabled: boolean
  priority: number
  config_params: Record<string, any>
  description?: string
  // 新增字段：支持市场分类
  market_categories?: string[]  // 所属市场分类列表
  display_name?: string         // 显示名称
  provider?: string            // 数据提供商
  created_at?: string
  updated_at?: string
}

// 市场分类配置
export interface MarketCategory {
  id: string
  name: string
  display_name: string
  description?: string
  enabled: boolean
  sort_order: number
  created_at?: string
  updated_at?: string
}

// 数据源分组关系
export interface DataSourceGrouping {
  data_source_name: string
  market_category_id: string
  priority: number              // 在该分类中的优先级
  enabled: boolean
  created_at?: string
  updated_at?: string
}

export interface DatabaseConfig {
  name: string
  type: string
  host: string
  port: number
  username?: string
  password?: string
  database?: string
  connection_params: Record<string, any>
  pool_size: number
  max_overflow: number
  enabled: boolean
  description?: string
}

export interface SystemConfig {
  config_name: string
  config_type: string
  llm_configs: LLMConfig[]
  default_llm?: string
  data_source_configs: DataSourceConfig[]
  default_data_source?: string
  database_configs: DatabaseConfig[]
  system_settings: Record<string, any>
  created_at: string
  updated_at: string
  version: number
  is_active: boolean
}

export interface ConfigTestRequest {
  config_type: 'llm' | 'datasource' | 'database'
  config_data: Record<string, any>
}

export interface ConfigTestResponse {
  success: boolean
  message: string
  details?: Record<string, any>
  response_time?: number
}


// 系统设置元数据
export interface SettingMeta {
  key: string
  sensitive: boolean
  editable: boolean
  source: 'environment' | 'database' | 'default'
  has_value: boolean
}

// 配置管理API
export const configApi = {
  // 获取系统配置
  getSystemConfig(): Promise<ApiResponse<SystemConfig>> {
    return ApiClient.get('/api/config/system')
  },

  // ========== 大模型厂家管理 ==========

  // 获取所有大模型厂家
  getLLMProviders(): Promise<ApiResponse<LLMProvider[]>> {
    return ApiClient.get('/api/config/llm/providers')
  },

  // 添加大模型厂家
  addLLMProvider(provider: Partial<LLMProvider>): Promise<ApiResponse<{ message: string; id: string }>> {
    return ApiClient.post('/api/config/llm/providers', provider)
  },

  // 更新大模型厂家
  updateLLMProvider(id: string, provider: Partial<LLMProvider>): Promise<ApiResponse<{ message: string }>> {
    return ApiClient.put(`/api/config/llm/providers/${id}`, provider)
  },

  // 删除大模型厂家
  deleteLLMProvider(id: string): Promise<ApiResponse<{ message: string }>> {
    return ApiClient.delete(`/api/config/llm/providers/${id}`)
  },

  // 启用/禁用大模型厂家
  toggleLLMProvider(id: string, isActive: boolean): Promise<ApiResponse<{ message: string }>> {
    return ApiClient.patch(`/api/config/llm/providers/${id}/toggle`, { is_active: isActive })
  },

  // 迁移环境变量到厂家管理
  migrateEnvToProviders(): Promise<ApiResponse<{ message: string; data: any }>> {
    return ApiClient.post('/api/config/llm/providers/migrate-env')
  },

  // ========== 模型目录管理 ==========

  // 获取所有模型目录
  getModelCatalog(): Promise<ApiResponse<Array<{
    provider: string
    provider_name: string
    models: Array<{
      name: string
      display_name: string
      description?: string
      context_length?: number
      max_tokens?: number
      input_price_per_1k?: number
      output_price_per_1k?: number
      currency?: string
      is_deprecated?: boolean
      release_date?: string
      capabilities?: string[]
    }>
  }>>> {
    return ApiClient.get('/api/config/model-catalog')
  },

  // 保存模型目录
  saveModelCatalog(catalog: {
    provider: string
    provider_name: string
    models: Array<{ name: string; display_name: string; description?: string }>
  }): Promise<ApiResponse<{ success: boolean; message: string }>> {
    return ApiClient.post('/api/config/model-catalog', catalog)
  },

  // 删除模型目录
  deleteModelCatalog(provider: string): Promise<ApiResponse<{ success: boolean; message: string }>> {
    return ApiClient.delete(`/api/config/model-catalog/${provider}`)
  },

  // 从厂家 API 获取模型列表
  fetchProviderModels(provider: string): Promise<ApiResponse<{
    success: boolean
    message?: string
    models?: Array<{
      id: string
      name: string
      context_length?: number
    }>
  }>> {
    return ApiClient.post(`/api/config/llm/providers/${provider}/fetch-models`)
  },

  // ========== 大模型配置管理 ==========

  // 获取所有大模型配置
  getLLMConfigs(): Promise<ApiResponse<LLMConfig[]>> {
    return ApiClient.get('/api/config/llm')
  },

  // 添加或更新大模型配置
  updateLLMConfig(config: Partial<LLMConfig>): Promise<ApiResponse<{ message: string; model_name: string }>> {
    return ApiClient.post('/api/config/llm', config)
  },

  // 删除大模型配置
  deleteLLMConfig(provider: string, modelName: string): Promise<ApiResponse<{ message: string }>> {
    return ApiClient.delete(`/api/config/llm/${provider}/${modelName}`)
  },

  // 设置默认大模型
  setDefaultLLM(name: string): Promise<ApiResponse<{ message: string; default_llm: string }>> {
    return ApiClient.post('/api/config/llm/set-default', { name })
  },

  // 获取所有数据源配置
  getDataSourceConfigs(): Promise<ApiResponse<DataSourceConfig[]>> {
    return ApiClient.get('/api/config/datasource')
  },

  // 添加数据源配置
  addDataSourceConfig(config: Partial<DataSourceConfig>): Promise<ApiResponse<{ message: string; name: string }>> {
    return ApiClient.post('/api/config/datasource', config)
  },

  // 设置默认数据源
  setDefaultDataSource(name: string): Promise<ApiResponse<{ message: string; default_data_source: string }>> {
    return ApiClient.post('/api/config/datasource/set-default', { name })
  },

  // 更新数据源配置
  updateDataSourceConfig(name: string, config: Partial<DataSourceConfig>): Promise<ApiResponse<{ message: string }>> {
    return ApiClient.put(`/api/config/datasource/${name}`, config)
  },

  // 删除数据源配置
  deleteDataSourceConfig(name: string): Promise<ApiResponse<{ message: string }>> {
    return ApiClient.delete(`/api/config/datasource/${name}`)
  },

  // 市场分类管理
  getMarketCategories(): Promise<ApiResponse<MarketCategory[]>> {
    return ApiClient.get('/api/config/market-categories')
  },

  addMarketCategory(category: Partial<MarketCategory>): Promise<ApiResponse<{ message: string; id: string }>> {
    return ApiClient.post('/api/config/market-categories', category)
  },

  updateMarketCategory(id: string, category: Partial<MarketCategory>): Promise<ApiResponse<{ message: string }>> {
    return ApiClient.put(`/api/config/market-categories/${id}`, category)
  },

  deleteMarketCategory(id: string): Promise<ApiResponse<{ message: string }>> {
    return ApiClient.delete(`/api/config/market-categories/${id}`)
  },

  // 数据源分组管理
  getDataSourceGroupings(): Promise<ApiResponse<DataSourceGrouping[]>> {
    return ApiClient.get('/api/config/datasource-groupings')
  },

  addDataSourceToCategory(dataSourceName: string, categoryId: string, priority?: number): Promise<ApiResponse<{ message: string }>> {
    return ApiClient.post('/api/config/datasource-groupings', {
      data_source_name: dataSourceName,
      market_category_id: categoryId,
      priority: priority || 0,
      enabled: true
    })
  },

  removeDataSourceFromCategory(dataSourceName: string, categoryId: string): Promise<ApiResponse<{ message: string }>> {
    return ApiClient.delete(`/api/config/datasource-groupings/${dataSourceName}/${categoryId}`)
  },

  updateDataSourceGrouping(dataSourceName: string, categoryId: string, updates: Partial<DataSourceGrouping>): Promise<ApiResponse<{ message: string }>> {
    return ApiClient.put(`/api/config/datasource-groupings/${dataSourceName}/${categoryId}`, updates)
  },

  // 批量更新分类内数据源排序
  updateCategoryDataSourceOrder(categoryId: string, orderedDataSources: Array<{name: string, priority: number}>): Promise<ApiResponse<{ message: string }>> {
    return ApiClient.put(`/api/config/market-categories/${categoryId}/datasource-order`, {
      data_sources: orderedDataSources
    })
  },

  // 获取系统设置元数据
  getSystemSettingsMeta(): Promise<{ items: SettingMeta[] }> {
    return ApiClient.get('/api/config/settings/meta').then((r: any) => r.data)
  },


  // ========== 数据库配置管理 ==========

  // 获取所有数据库配置
  getDatabaseConfigs(): Promise<ApiResponse<DatabaseConfig[]>> {
    return ApiClient.get('/api/config/database')
  },

  // 更新数据库配置
  updateDatabaseConfig(dbName: string, config: Partial<DatabaseConfig>): Promise<ApiResponse<{ success: boolean; message: string }>> {
    return ApiClient.put(`/api/config/database/${encodeURIComponent(dbName)}`, config)
  },

  // 测试数据库配置连接
  testDatabaseConfig(dbName: string): Promise<ConfigTestResponse> {
    return ApiClient.post(`/api/config/database/${encodeURIComponent(dbName)}/test`)
  },

  // 获取系统设置
  getSystemSettings(): Promise<Record<string, any>> {
    return ApiClient.get('/api/config/settings').then((response: any) => {
      // 🔧 返回实际的配置对象，如果是嵌套结构则提取 config
      return response.config || response
    })
  },

  // 获取默认模型配置
  getDefaultModels(): Promise<{ analyst_model: string; debate_model: string }> {
    return ApiClient.get('/api/config/settings').then((response: any) => {
      // 🔧 修复：后端返回的是 {config: {...}, version, cached_at}
      const settings = response.config || response
      return {
        analyst_model: settings.analyst_model || '',
        debate_model: settings.debate_model || ''
      }
    })
  },

  // 更新系统设置
  updateSystemSettings(settings: Record<string, any>): Promise<ApiResponse<{ message: string }>> {
    return ApiClient.put('/api/config/settings', settings)
  },

  // 测试配置连接
  testConfig(testRequest: ConfigTestRequest): Promise<ConfigTestResponse> {
    return ApiClient.post('/api/config/test', testRequest)
  },

  // 导出配置
  exportConfig(): Promise<ApiResponse<{ message: string; data: Record<string, any>; exported_at: string }>> {
    return ApiClient.post('/api/config/export')
  },

  // 导入配置
  importConfig(configData: Record<string, any>): Promise<ApiResponse<{ message: string }>> {
    return ApiClient.post('/api/config/import', configData)
  },

  // 迁移传统配置
  migrateLegacyConfig(): Promise<ApiResponse<{ message: string }>> {
    return ApiClient.post('/api/config/migrate-legacy')
  },

  // 配置重载
  reloadConfig(): Promise<ApiResponse<{ success: boolean; message: string; data?: any }>> {
    return ApiClient.post('/api/config/reload')
  }
}

// 默认 LLM 配置从单一源头导入
export { DEFAULT_LLM_CONFIG } from '@/constants/llmDefaults'

// 配置验证函数
export const validateLLMConfig = (config: Partial<LLMConfig>): string[] => {
  const errors: string[] = []

  if (!config.provider) errors.push('供应商不能为空')
  if (!config.model_name) errors.push('模型名称不能为空')
  // 注意：API密钥不在这里验证，因为它是在厂家配置中管理的
  if (config.max_tokens && config.max_tokens <= 0) errors.push('最大Token数必须大于0')
  if (config.temperature && (config.temperature < 0 || config.temperature > 2)) {
    errors.push('温度参数必须在0-2之间')
  }

  return errors
}

