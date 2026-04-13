/**
 * 配置管理核心 Hook
 * 封装系统配置、数据源、数据库、市场分类、系统设置等 CRUD 操作
 */

import { useState, useCallback, useEffect, useRef } from 'react'
import { message } from 'antd'
import type {
  SystemConfigResponse,
  DataSourceConfig,
  DataSourceConfigRequest,
  DatabaseConfig,
  DatabaseConfigRequest,
  MarketCategory,
  MarketCategoryRequest,
  DataSourceGrouping,
  ConfigTestResponse,
} from '@/types/config.types'
import * as configApi from '@/services/api/config'

export interface UseConfigReturn {
  // 系统配置
  systemConfig: SystemConfigResponse | null
  loading: boolean
  refresh: () => Promise<void>

  // 数据源
  dataSources: DataSourceConfig[]
  addDataSource: (data: DataSourceConfigRequest) => Promise<void>
  updateDataSource: (name: string, data: DataSourceConfigRequest) => Promise<void>
  deleteDataSource: (name: string) => Promise<void>
  setDefaultDS: (name: string) => Promise<void>

  // 数据库
  databases: DatabaseConfig[]
  addDatabase: (data: DatabaseConfigRequest) => Promise<void>
  updateDatabase: (name: string, data: DatabaseConfigRequest) => Promise<void>
  deleteDatabase: (name: string) => Promise<void>
  testDatabase: (name: string) => Promise<ConfigTestResponse>

  // 市场分类
  categories: MarketCategory[]
  addCategory: (data: MarketCategoryRequest) => Promise<void>
  updateCategory: (id: string, data: Record<string, unknown>) => Promise<void>
  deleteCategory: (id: string) => Promise<void>

  // 分组关系
  groupings: DataSourceGrouping[]

  // 系统设置
  settings: Record<string, unknown>
  updateSettings: (data: Record<string, unknown>) => Promise<void>

  // 操作方法
  reloadSystemConfig: () => Promise<void>
}

export function useConfig(): UseConfigReturn {
  const [systemConfig, setSystemConfig] = useState<SystemConfigResponse | null>(null)
  const [dataSources, setDataSources] = useState<DataSourceConfig[]>([])
  const [databases, setDatabases] = useState<DatabaseConfig[]>([])
  const [categories, setCategories] = useState<MarketCategory[]>([])
  const [groupings, setGroupings] = useState<DataSourceGrouping[]>([])
  const [settings, setSettings] = useState<Record<string, unknown>>({})
  const [loading, setLoading] = useState(false)

  const loadAll = useCallback(async () => {
    setLoading(true)
    try {
      const [configRes, dsRes, dbRes, catRes, grpRes, setRes] = await Promise.all([
        configApi.getSystemConfig().catch(() => null),
        configApi.getDataSourceConfigs().catch(() => ({ data: [] as DataSourceConfig[] })),
        configApi.getDatabaseConfigs().catch(() => ({ data: [] as DatabaseConfig[] })),
        configApi.getMarketCategories().catch(() => ({ data: [] as MarketCategory[] })),
        configApi.getDataSourceGroupings().catch(() => ({ data: [] as DataSourceGrouping[] })),
        configApi.getSystemSettings().catch(() => ({ data: {} as Record<string, unknown> })),
      ])
      setSystemConfig(configRes?.data ?? null)
      setDataSources(dsRes.data ?? [])
      setDatabases(dbRes.data ?? [])
      setCategories(catRes.data ?? [])
      setGroupings(grpRes.data ?? [])
      setSettings(setRes.data ?? {})
    } catch {
      // 静默处理
    } finally {
      setLoading(false)
    }
  }, [])

  // 初始加载（ guarded 防止 StrictMode 双调）
  const initializedRef = useRef(false)
  useEffect(() => {
    if (initializedRef.current) return
    initializedRef.current = true
    loadAll()
  }, [loadAll])

  const refresh = useCallback(async () => {
    await loadAll()
  }, [loadAll])

  // ========== 数据源操作 ==========

  const addDataSource = useCallback(async (data: DataSourceConfigRequest) => {
    await configApi.addDataSourceConfig(data)
    message.success('数据源添加成功')
    await loadAll()
  }, [loadAll])

  const updateDataSource = useCallback(async (name: string, data: DataSourceConfigRequest) => {
    await configApi.updateDataSourceConfig(name, data)
    message.success('数据源更新成功')
    await loadAll()
  }, [loadAll])

  const deleteDataSource = useCallback(async (name: string) => {
    await configApi.deleteDataSourceConfig(name)
    message.success('数据源已删除')
    await loadAll()
  }, [loadAll])

  const setDefaultDS = useCallback(async (name: string) => {
    await configApi.setDefaultDataSource({ name })
    message.success(`已设 ${name} 为默认数据源`)
    await loadAll()
  }, [loadAll])

  // ========== 数据库操作 ==========

  const addDatabase = useCallback(async (data: DatabaseConfigRequest) => {
    await configApi.addDatabaseConfig(data)
    message.success('数据库配置添加成功')
    await loadAll()
  }, [loadAll])

  const updateDatabase = useCallback(async (name: string, data: DatabaseConfigRequest) => {
    await configApi.updateDatabaseConfig(name, data)
    message.success('数据库配置更新成功')
    await loadAll()
  }, [loadAll])

  const deleteDatabase = useCallback(async (name: string) => {
    await configApi.deleteDatabaseConfig(name)
    message.success('数据库配置已删除')
    await loadAll()
  }, [loadAll])

  const testDatabase = useCallback(async (name: string): Promise<ConfigTestResponse> => {
    const res = await configApi.testSavedDatabaseConfig(name)
    return res.data
  }, [])

  // ========== 市场分类操作 ==========

  const addCategory = useCallback(async (data: MarketCategoryRequest) => {
    await configApi.addMarketCategory(data)
    message.success('分类添加成功')
    await loadAll()
  }, [loadAll])

  const updateCategory = useCallback(async (id: string, data: Record<string, unknown>) => {
    await configApi.updateMarketCategory(id, data)
    message.success('分类更新成功')
    await loadAll()
  }, [loadAll])

  const deleteCategory = useCallback(async (id: string) => {
    await configApi.deleteMarketCategory(id)
    message.success('分类已删除')
    await loadAll()
  }, [loadAll])

  // ========== 系统设置操作 ==========

  const updateSettings = useCallback(async (data: Record<string, unknown>) => {
    await configApi.updateSystemSettings(data)
    message.success('系统设置更新成功')
    await loadAll()
  }, [loadAll])

  // ========== 重载配置 ==========

  const reloadSystemConfig = useCallback(async () => {
    const res = await configApi.reloadConfig()
    if (res.data?.reloaded_at) {
      message.success('配置重载成功')
    }
    await loadAll()
  }, [loadAll])

  return {
    systemConfig,
    loading,
    refresh,
    dataSources,
    addDataSource,
    updateDataSource,
    deleteDataSource,
    setDefaultDS,
    databases,
    addDatabase,
    updateDatabase,
    deleteDatabase,
    testDatabase,
    categories,
    addCategory,
    updateCategory,
    deleteCategory,
    groupings,
    settings,
    updateSettings,
    reloadSystemConfig,
  }
}
