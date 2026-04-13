/**
 * LLM 厂家管理 Hook
 * 封装厂家的 CRUD、启用/禁用切换、API 测试、模型拉取等操作
 */

import { useState, useCallback, useEffect, useRef } from 'react'
import { message } from 'antd'
import type { LLMProviderResponse, LLMProviderRequest } from '@/types/config.types'
import * as configApi from '@/services/api/config'

export interface UseProvidersReturn {
  providers: LLMProviderResponse[]
  loading: boolean
  refresh: () => Promise<void>

  addProvider: (data: LLMProviderRequest) => Promise<void>
  updateProvider: (providerId: string, data: Partial<LLMProviderRequest>) => Promise<void>
  deleteProvider: (providerId: string) => Promise<void>
  toggleProvider: (providerId: string, isActive: boolean) => Promise<void>
  testProviderConnection: (providerId: string) => Promise<{ success: boolean; message: string }>
  fetchModelsFromAPI: (providerId: string) => Promise<void>
  migrateFromEnv: () => Promise<{ success: boolean; message: string; migratedCount: number; skippedCount: number }>
  initAggregators: () => Promise<{ success: boolean; message: string; addedCount: number; skippedCount: number }>
}

export function useProviders(): UseProvidersReturn {
  const [providers, setProviders] = useState<LLMProviderResponse[]>([])
  const [loading, setLoading] = useState(false)

  const loadProviders = useCallback(async () => {
    setLoading(true)
    try {
      const res = await configApi.getLLMProviders()
      setProviders(res.data ?? [])
    } catch {
      // 静默
    } finally {
      setLoading(false)
    }
  }, [])

  // 初始加载（ guarded 防止 StrictMode 双调）
  const initializedRef = useRef(false)
  useEffect(() => {
    if (initializedRef.current) return
    initializedRef.current = true
    loadProviders()
  }, [loadProviders])

  const refresh = useCallback(async () => {
    await loadProviders()
  }, [loadProviders])

  const addProvider = useCallback(async (data: LLMProviderRequest) => {
    await configApi.addLLMProvider(data)
    message.success('厂家添加成功')
    await loadProviders()
  }, [loadProviders])

  const updateProvider = useCallback(async (providerId: string, data: Partial<LLMProviderRequest>) => {
    await configApi.updateLLMProvider(providerId, data)
    message.success('厂家更新成功')
    await loadProviders()
  }, [loadProviders])

  const deleteProvider = useCallback(async (providerId: string) => {
    await configApi.deleteLLMProvider(providerId)
    message.success('厂家已删除')
    await loadProviders()
  }, [loadProviders])

  const toggleProvider = useCallback(async (providerId: string, isActive: boolean) => {
    await configApi.toggleLLMProvider(providerId, isActive)
    message.success(`厂家已${isActive ? '启用' : '禁用'}`)
    await loadProviders()
  }, [loadProviders])

  const testProviderConnection = useCallback(async (providerId: string) => {
    const res = await configApi.testProviderAPI(providerId)
    return { success: res.data.success, message: res.data.message }
  }, [])

  const fetchModelsFromAPI = useCallback(async (providerId: string) => {
    const res = await configApi.fetchProviderModels(providerId)
    if (res.data.models?.length) {
      message.success(`拉取到 ${res.data.models.length} 个模型`)
    } else {
      message.info(res.data.message || '未获取到模型列表')
    }
  }, [])

  const migrateFromEnv = useCallback(async () => {
    const res = await configApi.migrateEnvToProviders()
    return {
      success: res.data.success,
      message: res.data.message,
      migratedCount: res.data.migrated_count,
      skippedCount: res.data.skipped_count,
    }
  }, [])

  const initAggregators = useCallback(async () => {
    const res = await configApi.initAggregatorProviders()
    return {
      success: res.data.success,
      message: res.data.message,
      addedCount: res.data.added_count,
      skippedCount: res.data.skipped_count,
    }
  }, [])

  return {
    providers,
    loading,
    refresh,
    addProvider,
    updateProvider,
    deleteProvider,
    toggleProvider,
    testProviderConnection,
    fetchModelsFromAPI,
    migrateFromEnv,
    initAggregators,
  }
}
