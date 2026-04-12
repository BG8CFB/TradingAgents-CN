/**
 * 配置管理 API 服务
 * 对应后端 app/routers/config.py（前缀 /api/config）
 *
 * 覆盖范围：
 * - 配置重载与系统配置
 * - LLM 厂家管理（CRUD + 启用/禁用 + 测试 + 拉取模型）
 * - LLM 模型配置管理（CRUD + 设默认）
 * - 数据源配置管理（CRUD + 设默认）
 * - 数据库配置管理（CRUD + 测试连接）
 * - 市场分类管理（CRUD）
 * - 数据源分组管理（CRUD + 排序）
 * - 系统设置（读取/更新/元数据）
 * - 模型目录管理（CRUD + 初始化）
 * - 可用模型查询
 * - 配置导入导出
 * - 环境迁移 / 初始化聚合器
 */

import apiClient from '../http/client'
import type { ApiResponse } from '@/types/common.types'
import type {
  SystemConfigResponse,
  LLMProviderResponse,
  LLMProviderRequest,
  LLMConfig,
  LLMConfigRequest,
  DataSourceConfig,
  DataSourceConfigRequest,
  DatabaseConfig,
  DatabaseConfigRequest,
  MarketCategory,
  MarketCategoryRequest,
  DataSourceGrouping,
  DataSourceGroupingRequest,
  DataSourceOrderItem,
  ConfigTestRequest,
  ConfigTestResponse,
  ModelCatalog,
  ModelCatalogRequest,
  ModelInfo,
  AvailableModelsByProvider,
  SystemSettingsMetaResponse,
  ExportConfigResponse,
  MigrateEnvResult,
  InitAggregatorsResult,
  SetDefaultRequest,
} from '@/types/config.types'

const BASE = '/api/config'

// ========== 配置重载 ==========

/** 重新加载配置（从数据库桥接到环境变量） */
export async function reloadConfig(): Promise<ApiResponse<{ reloaded_at: string }>> {
  return apiClient.post<{ reloaded_at: string }>(`${BASE}/reload`)
}

// ========== 系统配置 ==========

/** 获取完整系统配置（含脱敏） */
export async function getSystemConfig(): Promise<ApiResponse<SystemConfigResponse>> {
  return apiClient.get<SystemConfigResponse>(`${BASE}/system`)
}

// ========== LLM 厂家管理 ==========

/** 获取所有 LLM 厂家 */
export async function getLLMProviders(): Promise<ApiResponse<LLMProviderResponse[]>> {
  return apiClient.get<LLMProviderResponse[]>(`${BASE}/llm/providers`)
}

/** 添加 LLM 厂家 */
export async function addLLMProvider(data: LLMProviderRequest): Promise<ApiResponse<{ id: string }>> {
  return apiClient.post<{ id: string }>(`${BASE}/llm/providers`, data)
}

/** 更新 LLM 厂家 */
export async function updateLLMProvider(providerId: string, data: Partial<LLMProviderRequest>): Promise<ApiResponse<Record<string, never>>> {
  return apiClient.put<Record<string, never>>(`${BASE}/llm/providers/${providerId}`, data)
}

/** 删除 LLM 厂家 */
export async function deleteLLMProvider(providerId: string): Promise<ApiResponse<Record<string, never>>> {
  return apiClient.delete<Record<string, never>>(`${BASE}/llm/providers/${providerId}`)
}

/** 启用/禁用 LLM 厂家 */
export async function toggleLLMProvider(providerId: string, isActive: boolean): Promise<ApiResponse<Record<string, never>>> {
  return apiClient.patch<Record<string, never>>(`${BASE}/llm/providers/${providerId}/toggle`, { is_active: isActive })
}

/** 测试厂家 API 连接 */
export async function testProviderAPI(providerId: string): Promise<ApiResponse<ConfigTestResponse>> {
  return apiClient.post<ConfigTestResponse>(`${BASE}/llm/providers/${providerId}/test`)
}

/** 从厂家 API 拉取可用模型列表 */
export async function fetchProviderModels(providerId: string): Promise<ApiResponse<{ success?: boolean; message?: string; models?: ModelInfo[] }>> {
  return apiClient.post<{ success?: boolean; message?: string; models?: ModelInfo[] }>(`${BASE}/llm/providers/${providerId}/fetch-models`)
}

/** 将环境变量配置迁移到厂家管理 */
export async function migrateEnvToProviders(): Promise<ApiResponse<MigrateEnvResult>> {
  return apiClient.post<MigrateEnvResult>(`${BASE}/llm/providers/migrate-env`)
}

/** 初始化聚合渠道厂家（302.AI、OpenRouter 等） */
export async function initAggregatorProviders(): Promise<ApiResponse<InitAggregatorsResult>> {
  return apiClient.post<InitAggregatorsResult>(`${BASE}/llm/providers/init-aggregators`)
}

// ========== LLM 模型配置 ==========

/** 获取所有 LLM 模型配置（仅启用且供应商启用的） */
export async function getLLMConfigs(): Promise<ApiResponse<LLMConfig[]>> {
  return apiClient.get<LLMConfig[]>(`${BASE}/llm`)
}

/** 添加或更新 LLM 模型配置 */
export async function addOrUpdateLLMConfig(data: LLMConfigRequest): Promise<ApiResponse<{ message: string; model_name: string }>> {
  return apiClient.post<{ message: string; model_name: string }>(`${BASE}/llm`, data)
}

/** 删除 LLM 模型配置 */
export async function deleteLLMConfig(provider: string, modelName: string): Promise<ApiResponse<{ message: string }>> {
  return apiClient.delete<{ message: string }>(`${BASE}/llm/${encodeURIComponent(provider)}/${encodeURIComponent(modelName)}`)
}

/** 设置默认分析大模型（/llm/set-default） */
export async function setDefaultLLM(data: SetDefaultRequest): Promise<ApiResponse<{ message: string; default_llm: string }>> {
  return apiClient.post<{ message: string; default_llm: string }>(`${BASE}/llm/set-default`, data)
}

// ========== 数据源配置 ==========

/** 获取所有数据源配置 */
export async function getDataSourceConfigs(): Promise<ApiResponse<DataSourceConfig[]>> {
  return apiClient.get<DataSourceConfig[]>(`${BASE}/datasource`)
}

/** 添加数据源配置 */
export async function addDataSourceConfig(data: DataSourceConfigRequest): Promise<ApiResponse<{ message: string; name: string }>> {
  return apiClient.post<{ message: string; name: string }>(`${BASE}/datasource`, data)
}

/** 更新数据源配置 */
export async function updateDataSourceConfig(name: string, data: DataSourceConfigRequest): Promise<ApiResponse<{ message: string }>> {
  return apiClient.put<{ message: string }>(`${BASE}/datasource/${encodeURIComponent(name)}`, data)
}

/** 删除数据源配置 */
export async function deleteDataSourceConfig(name: string): Promise<ApiResponse<{ message: string }>> {
  return apiClient.delete<{ message: string }>(`${BASE}/datasource/${encodeURIComponent(name)}`)
}

/** 设置默认数据源（/datasource/set-default） */
export async function setDefaultDataSource(data: SetDefaultRequest): Promise<ApiResponse<{ message: string; default_data_source: string }>> {
  return apiClient.post<{ message: string; default_data_source: string }>(`${BASE}/datasource/set-default`, data)
}

// ========== 数据库配置 ==========

/** 获取所有数据库配置 */
export async function getDatabaseConfigs(): Promise<ApiResponse<DatabaseConfig[]>> {
  return apiClient.get<DatabaseConfig[]>(`${BASE}/database`)
}

/** 获取指定数据库配置 */
export async function getDatabaseConfig(dbName: string): Promise<ApiResponse<DatabaseConfig>> {
  return apiClient.get<DatabaseConfig>(`${BASE}/database/${encodeURIComponent(dbName)}`)
}

/** 添加数据库配置 */
export async function addDatabaseConfig(data: DatabaseConfigRequest): Promise<ApiResponse<{ success: boolean; message: string }>> {
  return apiClient.post<{ success: boolean; message: string }>(`${BASE}/database`, data)
}

/** 更新数据库配置 */
export async function updateDatabaseConfig(dbName: string, data: DatabaseConfigRequest): Promise<ApiResponse<{ success: boolean; message: string }>> {
  return apiClient.put<{ success: boolean; message: string }>(`${BASE}/database/${encodeURIComponent(dbName)}`, data)
}

/** 删除数据库配置 */
export async function deleteDatabaseConfig(dbName: string): Promise<ApiResponse<{ success: boolean; message: string }>> {
  return apiClient.delete<{ success: boolean; message: string }>(`${BASE}/database/${encodeURIComponent(dbName)}`)
}

/** 测试已保存的数据库配置连接（从 DB 取完整密码） */
export async function testSavedDatabaseConfig(dbName: string): Promise<ApiResponse<ConfigTestResponse>> {
  return apiClient.post<ConfigTestResponse>(`${BASE}/database/${encodeURIComponent(dbName)}/test`)
}

// ========== 配置测试（通用） ==========

/** 通用配置连接测试 */
export async function testConfig(data: ConfigTestRequest): Promise<ApiResponse<ConfigTestResponse>> {
  return apiClient.post<ConfigTestResponse>(`${BASE}/test`, data)
}

// ========== 市场分类 ==========

/** 获取所有市场分类 */
export async function getMarketCategories(): Promise<ApiResponse<MarketCategory[]>> {
  return apiClient.get<MarketCategory[]>(`${BASE}/market-categories`)
}

/** 添加市场分类 */
export async function addMarketCategory(data: MarketCategoryRequest): Promise<ApiResponse<{ message: string; id: string }>> {
  return apiClient.post<{ message: string; id: string }>(`${BASE}/market-categories`, data)
}

/** 更新市场分类 */
export async function updateMarketCategory(categoryId: string, data: Record<string, unknown>): Promise<ApiResponse<{ message: string }>> {
  return apiClient.put<{ message: string }>(`${BASE}/market-categories/${categoryId}`, data)
}

/** 删除市场分类 */
export async function deleteMarketCategory(categoryId: string): Promise<ApiResponse<{ message: string }>> {
  return apiClient.delete<{ message: string }>(`${BASE}/market-categories/${categoryId}`)
}

// ========== 数据源分组 ==========

/** 获取所有数据源分组关系 */
export async function getDataSourceGroupings(): Promise<ApiResponse<DataSourceGrouping[]>> {
  return apiClient.get<DataSourceGrouping[]>(`${BASE}/datasource-groupings`)
}

/** 将数据源添加到市场分类 */
export async function addDataSourceToCategory(data: DataSourceGroupingRequest): Promise<ApiResponse<{ message: string }>> {
  return apiClient.post<{ message: string }>(`${BASE}/datasource-groupings`, data)
}

/** 从分类中移除数据源 */
export async function removeDataSourceFromCategory(dataSourceName: string, categoryId: string): Promise<ApiResponse<{ message: string }>> {
  return apiClient.delete<{ message: string }>(`${BASE}/datasource-groupings/${encodeURIComponent(dataSourceName)}/${encodeURIComponent(categoryId)}`)
}

/** 更新数据源分组关系 */
export async function updateDataSourceGrouping(dataSourceName: string, categoryId: string, data: Record<string, unknown>): Promise<ApiResponse<{ message: string }>> {
  return apiClient.put<{ message: string }>(`${BASE}/datasource-groupings/${encodeURIComponent(dataSourceName)}/${encodeURIComponent(categoryId)}`, data)
}

/** 更新分类内数据源排序 */
export async function updateCategoryDatasourceOrder(categoryId: string, dataSources: DataSourceOrderItem[]): Promise<ApiResponse<{ message: string }>> {
  return apiClient.put<{ message: string }>(`${BASE}/market-categories/${categoryId}/datasource-order`, { data_sources: dataSources })
}

// ========== 系统设置 ==========

/** 获取系统设置（敏感字段已脱敏） */
export async function getSystemSettings(): Promise<ApiResponse<Record<string, unknown>>> {
  return apiClient.get<Record<string, unknown>>(`${BASE}/settings`)
}

/** 获取系统设置元数据 */
export async function getSystemSettingsMeta(): Promise<ApiResponse<SystemSettingsMetaResponse>> {
  return apiClient.get<SystemSettingsMetaResponse>(`${BASE}/settings/meta`)
}

/** 更新系统设置 */
export async function updateSystemSettings(settings: Record<string, unknown>): Promise<ApiResponse<{ message: string }>> {
  return apiClient.put<{ message: string }>(`${BASE}/settings`, settings)
}

// ========== 模型目录 ==========

/** 获取所有模型目录 */
export async function getModelCatalog(): Promise<ApiResponse<ModelCatalog[]>> {
  return apiClient.get<ModelCatalog[]>(`${BASE}/model-catalog`)
}

/** 获取指定厂家的模型目录 */
export async function getProviderModelCatalog(provider: string): Promise<ApiResponse<ModelCatalog>> {
  return apiClient.get<ModelCatalog>(`${BASE}/model-catalog/${encodeURIComponent(provider)}`)
}

/** 保存或更新模型目录 */
export async function saveModelCatalog(data: ModelCatalogRequest): Promise<ApiResponse<{ success: boolean; message: string }>> {
  return apiClient.post<{ success: boolean; message: string }>(`${BASE}/model-catalog`, data)
}

/** 删除模型目录 */
export async function deleteModelCatalog(provider: string): Promise<ApiResponse<{ success: boolean; message: string }>> {
  return apiClient.delete<{ success: boolean; message: string }>(`${BASE}/model-catalog/${encodeURIComponent(provider)}`)
}

/** 初始化默认模型目录 */
export async function initModelCatalog(): Promise<ApiResponse<{ success: boolean; message: string }>> {
  return apiClient.post<{ success: boolean; message: string }>(`${BASE}/model-catalog/init`)
}

// ========== 可用模型 ==========

/** 获取可用模型列表（按供应商分组） */
export async function getAvailableModels(): Promise<ApiResponse<AvailableModelsByProvider[]>> {
  return apiClient.get<AvailableModelsByProvider[]>(`${BASE}/models`)
}

// ========== 配置导入导出 ==========

/** 导出完整配置 */
export async function exportConfig(): Promise<ApiResponse<ExportConfigResponse>> {
  return apiClient.post<ExportConfigResponse>(`${BASE}/export`)
}

/** 导入配置 */
export async function importConfig(configData: Record<string, unknown>): Promise<ApiResponse<{ message: string }>> {
  return apiClient.post<{ message: string }>(`${BASE}/import`, configData)
}

/** 迁移传统配置格式 */
export async function migrateLegacyConfig(): Promise<ApiResponse<{ message: string }>> {
  return apiClient.post<{ message: string }>(`${BASE}/migrate-legacy`)
}
