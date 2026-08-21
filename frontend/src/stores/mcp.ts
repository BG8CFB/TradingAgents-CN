import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import {
  mcpApi,
  type MCPConnector,
  type MCPUpdatePayload,
  type ImportInsight,
  type RuntimeCheckResult
} from '@/api/mcp'
import type { MCPServerConfig } from '@/types/mcp'

export const useMCPStore = defineStore('mcp', () => {
  const connectors = ref<MCPConnector[]>([])
  const loading = ref(false)
  const saving = ref(false)
  const reloading = ref(false)

  const enabledCount = computed(() => connectors.value.filter((c) => c.enabled).length)

  const fetchConnectors = async () => {
    loading.value = true
    try {
      const res = await mcpApi.list()
      connectors.value = res.data || []
    } catch (error) {
      console.error('加载 MCP 连接器失败', error)
      ElMessage.error('加载 MCP 连接器失败')
    } finally {
      loading.value = false
    }
  }

  /** 重载全部 MCP 连接（配置变更后立即生效） */
  const reload = async () => {
    reloading.value = true
    try {
      const res = await mcpApi.reload()
      const connected = (res.data as any)?.connected
      ElMessage.success(connected !== undefined ? `配置已生效，已连接 ${connected} 个服务器` : '配置已生效')
    } catch (error) {
      console.error('重载 MCP 连接失败', error)
      ElMessage.warning('配置已保存，但重载连接失败，稍后将自动重连')
    } finally {
      reloading.value = false
    }
  }

  const batchUpdate = async (payload: MCPUpdatePayload) => {
    saving.value = true
    try {
      await mcpApi.batchUpdate(payload)
      await fetchConnectors()
      await reload()
    } catch (error) {
      console.error('更新 MCP 配置失败', error)
      ElMessage.error('更新配置失败')
      throw error
    } finally {
      saving.value = false
    }
  }

  /** 多格式导入识别（dry-run，不落盘） */
  const importRaw = async (raw: string): Promise<ImportInsight | null> => {
    try {
      const res = await mcpApi.importConnectors(raw)
      return (res.data as ImportInsight) || null
    } catch (error: any) {
      const detail = error?.response?.data?.detail || error?.message || '导入解析失败'
      ElMessage.error(String(detail))
      return null
    }
  }

  const toggleConnector = async (name: string, enabled: boolean) => {
    // 乐观更新
    const original = connectors.value.find(c => c.name === name)?.enabled
    connectors.value = connectors.value.map(c =>
      c.name === name ? { ...c, enabled } : c
    )

    try {
      await mcpApi.toggle(name, enabled)
      // 启停改变连接集合，需重建会话并刷新状态（reload 自带成功提示）
      await reload()
      await fetchConnectors()
    } catch (error) {
      console.error('切换连接器状态失败', error)
      ElMessage.error('切换状态失败')
      // 回滚
      if (original !== undefined) {
          connectors.value = connectors.value.map(c =>
            c.name === name ? { ...c, enabled: original } : c
          )
      }
      throw error
    }
  }

  const deleteConnector = async (name: string) => {
    try {
      await mcpApi.delete(name)
      connectors.value = connectors.value.filter((item) => item.name !== name)
      await reload()
      ElMessage.success('已删除连接器')
    } catch (error) {
      console.error('删除 MCP 连接器失败', error)
      ElMessage.error('删除连接器失败')
      throw error
    }
  }

  /** 测试已配置服务器的连接（返回状态；失败返回 null） */
  const testConnector = async (name: string): Promise<string | null> => {
    try {
      const res = await mcpApi.testConnector(name)
      return (res.data as any)?.status || 'unknown'
    } catch (error) {
      console.error('测试连接失败', error)
      ElMessage.error('测试连接失败')
      return null
    }
  }

  /** 检测 stdio 运行时（未落盘的配置也可测） */
  const checkRuntime = async (config: MCPServerConfig): Promise<RuntimeCheckResult | null> => {
    try {
      const res = await mcpApi.checkRuntime(config)
      return (res.data as RuntimeCheckResult) || null
    } catch (error: any) {
      const detail = error?.response?.data?.detail || error?.message || '运行时检测失败'
      ElMessage.error(String(detail))
      return null
    }
  }

  /** 一键安装运行时工具（uv） */
  const installRuntimeTool = async (tool: 'uv' | 'node') => {
    try {
      const res = await mcpApi.installRuntimeTool(tool)
      const ok = res.success || (res.data as any)?.success
      if (ok) {
        ElMessage.success('安装成功')
      } else {
        ElMessage.error((res.data as any)?.error || '安装失败')
      }
      return Boolean(ok)
    } catch (error) {
      console.error('安装运行时工具失败', error)
      ElMessage.error('安装运行时工具失败')
      return false
    }
  }

  /** 安装服务器声明的 deps */
  const installDeps = async (name: string) => {
    try {
      const res = await mcpApi.installDeps(name)
      const data = res.data as any
      if (data?.satisfied) {
        ElMessage.success('依赖安装成功')
      } else if (data?.skipped_reason === 'no_deps') {
        ElMessage.info('该服务器未声明依赖')
      } else {
        ElMessage.error(data?.error || '依赖安装失败')
      }
      return data
    } catch (error: any) {
      const detail = error?.response?.data?.detail || error?.message || '依赖安装失败'
      ElMessage.error(String(detail))
      return null
    }
  }

  return {
    connectors,
    loading,
    saving,
    reloading,
    enabledCount,
    fetchConnectors,
    reload,
    batchUpdate,
    importRaw,
    toggleConnector,
    deleteConnector,
    testConnector,
    checkRuntime,
    installRuntimeTool,
    installDeps
  }
})
