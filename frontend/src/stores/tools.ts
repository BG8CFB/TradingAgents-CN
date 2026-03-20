import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { toolsApi, type MCPTool } from '@/api/tools'

export const useToolsStore = defineStore('tools', () => {
  const tools = ref<MCPTool[]>([])
  const loading = ref(false)
  const summary = ref<any>(null)

  const enabledCount = computed(() => tools.value.filter((t) => t.enabled).length)
  const availableCount = computed(() => tools.value.filter((t) => t.available).length)

  const toolsByCategory = computed(() => {
    const grouped: Record<string, MCPTool[]> = {}
    for (const tool of tools.value) {
      if (!grouped[tool.category]) {
        grouped[tool.category] = []
      }
      grouped[tool.category].push(tool)
    }
    return grouped
  })

  const fetchTools = async () => {
    loading.value = true
    try {
      const res = await toolsApi.listMCP()
      if (res.success) {
        tools.value = res.data || []
        summary.value = res.summary
      }
    } catch (error) {
      console.error('加载 MCP 工具失败', error)
      ElMessage.error('加载 MCP 工具失败')
    } finally {
      loading.value = false
    }
  }

  const fetchSummary = async () => {
    try {
      const res = await toolsApi.getAvailabilitySummary()
      if (res.success) {
        summary.value = res.data
      }
    } catch (error) {
      console.error('加载可用性摘要失败', error)
    }
  }

  const toggleTool = async (name: string, enabled: boolean) => {
    // 乐观更新
    const tool = tools.value.find(t => t.name === name)
    const original = tool?.enabled
    if (tool) {
      tool.enabled = enabled
    }

    try {
      await toolsApi.toggle(name, enabled)
      ElMessage.success(enabled ? '工具已启用' : '工具已禁用')
    } catch (error) {
      console.error('切换工具状态失败', error)
      ElMessage.error('切换工具状态失败')
      // 回滚
      if (tool && original !== undefined) {
        tool.enabled = original
      }
      throw error
    }
  }

  return {
    tools,
    loading,
    summary,
    enabledCount,
    availableCount,
    toolsByCategory,
    fetchTools,
    fetchSummary,
    toggleTool
  }
})
