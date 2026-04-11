/**
 * MCP 服务管理 Hook
 * 封装 MCP 连接器的 CRUD 操作和状态管理
 */

import { useState, useCallback } from 'react'
import { message } from 'antd'
import {
  listMCPConnectors,
  toggleMCPConnector,
  deleteMCPConnector,
  updateMCPConnectors,
  reloadMCPConfig,
  triggerMCPHealthCheck,
  type MCPConnector,
} from '@/services/api/mcp'

export interface UseMCPReturn {
  connectors: MCPConnector[]
  loading: boolean
  saving: boolean
  healthData: Record<string, unknown> | null
  fetchConnectors: () => Promise<void>
  toggleConnector: (name: string, enabled: boolean) => Promise<void>
  removeConnector: (name: string) => Promise<void>
  batchUpdate: (mcpServers: Record<string, unknown>) => Promise<void>
  doReload: () => Promise<void>
  doHealthCheck: () => Promise<Record<string, unknown>>
}

export function useMCP(): UseMCPReturn {
  const [connectors, setConnectors] = useState<MCPConnector[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [healthData, setHealthData] = useState<Record<string, unknown> | null>(null)

  const fetchConnectors = useCallback(async () => {
    setLoading(true)
    try {
      const res = await listMCPConnectors()
      setConnectors(Array.isArray(res) ? res : [])
    } catch {
      message.error('加载 MCP 连接器列表失败')
      setConnectors([])
    } finally {
      setLoading(false)
    }
  }, [])

  const toggleConnector = useCallback(async (name: string, enabled: boolean) => {
    try {
      await toggleMCPConnector(name, enabled)
      message.success(`${enabled ? '启用' : '禁用'}成功`)
      await fetchConnectors()
    } catch {
      message.error('操作失败')
    }
  }, [fetchConnectors])

  const removeConnector = useCallback(async (name: string) => {
    try {
      await deleteMCPConnector(name)
      message.success('已删除')
      await fetchConnectors()
    } catch {
      message.error('删除失败')
    }
  }, [fetchConnectors])

  const batchUpdate = useCallback(async (mcpServers: Record<string, unknown>) => {
    setSaving(true)
    try {
      await updateMCPConnectors(mcpServers)
      message.success('配置更新成功')
      await fetchConnectors()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      message.error(`配置更新失败: ${err?.response?.data?.detail || err?.message || '未知错误'}`)
    } finally {
      setSaving(false)
    }
  }, [fetchConnectors])

  const doReload = useCallback(async () => {
    try {
      const res = await reloadMCPConfig()
      message.success(res.message || '重载成功')
      await fetchConnectors()
    } catch {
      message.error('重载失败')
    }
  }, [fetchConnectors])

  const doHealthCheck = useCallback(async () => {
    try {
      const res = await triggerMCPHealthCheck()
      setHealthData(res.data ?? res)
      return res.data ?? res
    } catch {
      message.error('健康检查失败')
      return {}
    }
  }, [])

  return {
    connectors,
    loading,
    saving,
    healthData,
    fetchConnectors,
    toggleConnector,
    removeConnector,
    batchUpdate,
    doReload,
    doHealthCheck,
  }
}
