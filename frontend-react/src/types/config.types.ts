/**
 * 配置管理相关类型定义
 * 对应后端 app/routers/config.py + app/models/config.py
 */

// ========== LLM 厂家 ==========

/** 支持的功能标签 */
export type SupportedFeature = 'chat' | 'completion' | 'embedding' | 'image_generation' | 'vision' | 'tool_calling' | 'function_calling' | 'streaming' | 'json_mode'

/** 聚合渠道类型 */
export type AggregatorType = 'openrouter' | '302ai' | 'siliconflow' | 'custom'

/** LLM 厂家请求体 */
export interface LLMProviderRequest {
  name: string
  display_name: string
  description?: string
  website?: string
  api_doc_url?: string
  logo_url?: string
  is_active: boolean
  supported_features: SupportedFeature[]
  default_base_url?: string
  api_key?: string
  api_secret?: string
  is_aggregator?: boolean
  aggregator_type?: AggregatorType
  model_name_format?: string
}

/** LLM 厂家响应（API Key 已脱敏） */
export interface LLMProviderResponse {
  id: string
  name: string
  display_name: string
  description?: string
  website?: string
  api_doc_url?: string
  logo_url?: string
  is_active: boolean
  supported_features: SupportedFeature[]
  default_base_url?: string
  /** 脱敏后的 API Key，如 sk-9905...6789 */
  api_key?: string | null
  api_secret?: string | null
  extra_config: {
    has_api_key: boolean
    has_api_secret: boolean
    [key: string]: unknown
  }
  is_aggregator?: boolean
  aggregator_type?: AggregatorType
  model_name_format?: string
  created_at?: string
  updated_at?: string
}

// ========== LLM 模型配置 ==========

/** 适用角色 */
export type SuitableRole = 'quick_analysis' | 'deep_analysis' | 'both'

/** 模型能力 */
export type ModelCapability = 'tool_calling' | 'long_context' | 'reasoning' | 'vision' | 'coding' | 'multimodal' | 'json_mode' | 'streaming'

/** LLM 模型配置请求 */
export interface LLMConfigRequest {
  provider: string
  model_name: string
  model_display_name?: string
  api_key?: string
  api_base?: string
  max_tokens?: number
  temperature?: number
  timeout?: number
  retry_times?: number
  enabled?: boolean
  description?: string
  input_price_per_1k?: number
  output_price_per_1k?: number
  currency?: string
  capability_level?: number
  suitable_roles?: SuitableRole[]
  features?: ModelCapability[]
  recommended_depths?: string[]
  performance_metrics?: {
    speed?: number
    cost?: number
    quality?: number
  }
}

/** LLM 模型配置响应 */
export interface LLMConfig {
  provider: string
  model_name: string
  model_display_name?: string
  api_key?: string | null
  api_base?: string
  max_tokens: number
  temperature: number
  timeout: number
  retry_times: number
  enabled: boolean
  description?: string
  input_price_per_1k?: number
  output_price_per_1k?: number
  currency?: string
  capability_level?: number
  suitable_roles?: SuitableRole[]
  features?: ModelCapability[]
  recommended_depths?: string[]
  performance_metrics?: {
    speed?: number
    cost?: number
    quality?: number
  }
}

// ========== 数据源配置 ==========

/** 数据源类型 */
export type DataSourceType = 'tushare' | 'akshare' | 'baostock' | 'finnhub' | 'yahoo_finance' | 'eastmoney' | 'sina' | 'custom'

/** 数据源配置请求/响应 */
export interface DataSourceConfig {
  name: string
  type: DataSourceType
  api_key?: string | null
  api_secret?: string | null
  endpoint?: string
  timeout?: number
  rate_limit?: number
  enabled?: boolean
  priority?: number
  config_params?: Record<string, unknown>
  description?: string
  market_categories?: string[]
  display_name?: string
  provider?: string
}

export type DataSourceConfigRequest = DataSourceConfig

// ========== 数据库配置 ==========

/** 数据库类型 */
export type DatabaseType = 'mongodb' | 'mysql' | 'postgresql' | 'redis' | 'sqlite'

/** 数据库配置 */
export interface DatabaseConfig {
  name: string
  type: DatabaseType
  host: string
  port: number
  username?: string
  password?: string | null
  database?: string
  connection_params?: Record<string, unknown>
  pool_size?: number
  max_overflow?: number
  enabled?: boolean
  description?: string
}

export type DatabaseConfigRequest = DatabaseConfig

// ========== 市场分类 ==========

/** 市场分类 */
export interface MarketCategory {
  id: string
  name: string
  display_name: string
  description?: string
  enabled: boolean
  sort_order?: number
}

export interface MarketCategoryRequest {
  id: string
  name: string
  display_name: string
  description?: string
  enabled?: boolean
  sort_order?: number
}

// ========== 数据源分组 ==========

/** 数据源与市场分类的关联关系 */
export interface DataSourceGrouping {
  data_source_name: string
  market_category_id: string
  priority: number
  enabled: boolean
}

export interface DataSourceGroupingRequest {
  data_source_name: string
  market_category_id: string
  priority?: number
  enabled?: boolean
}

/** 数据源排序项 */
export interface DataSourceOrderItem {
  name: string
  priority: number
}

export interface DataSourceOrderRequest {
  data_sources: DataSourceOrderItem[]
}

// ========== 系统配置（聚合） ==========

/** 完整系统配置响应 */
export interface SystemConfigResponse {
  config_name: string
  config_type: string
  llm_configs: LLMConfig[]
  default_llm: string
  data_source_configs: DataSourceConfig[]
  default_data_source: string
  database_configs: DatabaseConfig[]
  system_settings: Record<string, unknown>
  created_at?: string
  updated_at?: string
  version?: number
  is_active?: boolean
}

// ========== 配置测试 ==========

/** 配置测试类型 */
export type ConfigTestType = 'llm' | 'datasource' | 'database'

/** 配置测试请求 */
export interface ConfigTestRequest {
  config_type: ConfigTestType
  config_data: Record<string, unknown>
}

/** 配置测试响应 */
export interface ConfigTestResponse {
  success: boolean
  message: string
  details?: Record<string, unknown>
  response_time?: number
}

// ========== 模型目录 ==========

/** 模型信息 */
export interface ModelInfo {
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
}

/** 模型目录 */
export interface ModelCatalog {
  provider: string
  provider_name: string
  models: ModelInfo[]
}

export interface ModelCatalogRequest {
  provider: string
  provider_name: string
  models: ModelInfo[]
}

// ========== 可用模型列表 ==========

/** 按供应商分组的可用模型 */
export interface AvailableModelsByProvider {
  provider: string
  provider_name: string
  models: Array<{
    name: string
    display_name: string
  }>
}

// ========== 系统设置 ==========

/** 系统设置元数据项 */
export interface SettingMetaItem {
  key: string
  sensitive: boolean
  editable: boolean
  source: string
  has_value: boolean
}

export interface SystemSettingsMetaResponse {
  success: boolean
  data: {
    items: SettingMetaItem[]
  }
  message: string
}

// ========== 配置导入导出 ==========

/** 导出配置响应 */
export interface ExportConfigResponse {
  message: string
  data: Record<string, unknown>
  exported_at: string
}

/** 环境迁移结果 */
export interface MigrateEnvResult {
  success: boolean
  message: string
  migrated_count: number
  skipped_count: number
}

/** 初始化聚合器结果 */
export interface InitAggregatorsResult {
  success: boolean
  message: string
  added_count: number
  skipped_count: number
}

/** 设置默认值请求 */
export interface SetDefaultRequest {
  name: string
}
