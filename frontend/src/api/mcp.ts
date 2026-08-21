import { request, type ApiResponse } from './request'
import type {
  MCPConnector,
  MCPUpdatePayload,
  MCPTool,
  MCPServerConfig,
  ImportInsight,
  RuntimeCheckResult,
  DepsInstallResult
} from '@/types/mcp'

const BASE = '/api/mcp/connectors'
const ROOT = '/api/mcp'
const TOOLS_BASE = '/api/mcp/tools'

export const mcpApi = {
  list(): Promise<ApiResponse<MCPConnector[]>> {
    return request.get(BASE)
  },
  listTools(): Promise<ApiResponse<MCPTool[]>> {
    return request.get(TOOLS_BASE)
  },
  batchUpdate(payload: MCPUpdatePayload): Promise<ApiResponse<void>> {
    return request.post(`${BASE}/update`, payload)
  },
  toggle(name: string, enabled: boolean): Promise<ApiResponse<{ enabled: boolean }>> {
    return request.patch(`${BASE}/${name}/toggle`, { enabled })
  },
  delete(name: string): Promise<ApiResponse<void>> {
    return request.delete(`${BASE}/${name}`)
  },
  /** 多格式配置导入（dry-run，识别 Cline/Kilo/Claude Desktop/裸对象） */
  importConnectors(raw: string): Promise<ApiResponse<ImportInsight>> {
    return request.post(`${BASE}/import`, { raw })
  },
  /** 重载全部 MCP 连接（保存/导入后调用） */
  reload(): Promise<ApiResponse<{ connected: number }>> {
    return request.post(`${ROOT}/reload`)
  },
  /** 检测 stdio 服务器运行时可用性（未落盘即可测） */
  checkRuntime(config: MCPServerConfig): Promise<ApiResponse<RuntimeCheckResult>> {
    return request.post(`${BASE}/check-runtime`, config)
  },
  /** 测试已配置服务器的连接 */
  testConnector(name: string): Promise<ApiResponse<{ name: string; status: string }>> {
    return request.post(`${BASE}/${name}/test`)
  },
  /** 安装服务器声明的 deps 到容器 Python */
  installDeps(name: string): Promise<ApiResponse<DepsInstallResult>> {
    return request.post(`${BASE}/${name}/install-deps`)
  },
  /** 一键安装缺失的运行时工具（uv） */
  installRuntimeTool(tool: 'uv' | 'node'): Promise<ApiResponse<{ success?: boolean; error?: string }>> {
    return request.post(`${ROOT}/runtime/install-tool`, { tool })
  }
}

export type { MCPConnector, MCPUpdatePayload, MCPTool, ImportInsight, RuntimeCheckResult, DepsInstallResult }
