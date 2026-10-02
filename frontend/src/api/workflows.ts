import { request, type ApiResponse } from './request'

/**
 * 工作流通用化前端契约（设计文档 §5.5）：
 * - workflows 半区：列表（内置+自定义，带校验/默认标记）/ 详情 / 新建 / 更新 / 软删除 /
 *   设默认 / validate（保存前）/ validate-run（分析页裁剪可行性）
 * - agents 半区：智能体库列表（builtin/引用计数）/ 单条 CRUD / fork（内置定制唯一路径）
 *
 * 两层模型：agent_specs = prompt/契约层；执行属性（type/execution/memory）在
 * workflow spec 的 nodes 段，由工作流编辑器编辑。
 */

// ── workflows ───────────────────────────────────────────────────────────────

export interface StageSummary {
  id: string
  mode: 'parallel_batch' | 'debate' | 'single'
  optional: boolean
}

export interface WorkflowListItem {
  slug: string
  name: string
  description: string
  enabled: boolean
  builtin: boolean
  updated_at?: string
  stages: StageSummary[]
  valid: boolean
  validation_errors: string[]
  is_default: boolean
}

/** 槽连线值：str = 单来源（report 键 / 点路径 / all_upstream）；数组 = 报告键集合（后端 InputBinding） */
export type InputBinding = string | string[]

export interface NodeSpecDto {
  slug: string
  type?: string
  execution?: string
  memory?: string | null
  terminal?: boolean
  report_keys?: string[]
  node_name?: string
  event_key?: string
  default_selected?: boolean
}

export interface StageSpecDto {
  id: string
  mode: 'parallel_batch' | 'debate' | 'single'
  optional?: boolean
  rounds?: number
  concurrency?: number
  event_phase?: string
  state_key?: string
  report_view?: string
  report_key?: string
  pool?: string
  nodes?: { ref: string; inputs?: Record<string, InputBinding> }[]
  /** debate 组输入 / single 节点输入：槽 → 上游连线 */
  inputs?: Record<string, InputBinding>
  sides?: string[]
  judge?: string
  node?: string
}

export interface WorkflowSpecDto {
  slug: string
  name: string
  description?: string
  version?: number
  enabled?: boolean
  builtin?: boolean
  nodes: NodeSpecDto[]
  stages: StageSpecDto[]
  terminal: { decision_field: string; signal_fallback?: string[]; summary_node: string }
}

export interface WorkflowDetail {
  workflow: WorkflowSpecDto
  builtin: boolean
  updated_at?: string
  created_at?: string
}

export interface ValidateRunPayload {
  workflow_slug: string
  selected_nodes?: string[]
  stage_overrides?: Record<string, { enabled?: boolean; rounds?: number; concurrency?: number }>
}

export interface ValidateRunResult {
  valid: boolean
  errors: string[]
  plan?: {
    stages: { stage_id: string; kind: string; nodes: string[] }[]
    total_units: number
  }
}

const WF_BASE = '/api/workflows'

export const workflowApi = {
  list(): Promise<ApiResponse<{ workflows: WorkflowListItem[]; default_slug: string }>> {
    return request.get(WF_BASE)
  },
  get(slug: string): Promise<ApiResponse<WorkflowDetail>> {
    return request.get(`${WF_BASE}/${slug}`)
  },
  create(spec: WorkflowSpecDto): Promise<ApiResponse<{ workflow: WorkflowSpecDto }>> {
    return request.post(WF_BASE, spec)
  },
  update(slug: string, spec: WorkflowSpecDto): Promise<ApiResponse<{ workflow: WorkflowSpecDto }>> {
    return request.put(`${WF_BASE}/${slug}`, spec)
  },
  remove(slug: string): Promise<ApiResponse<{ slug: string }>> {
    return request.delete(`${WF_BASE}/${slug}`)
  },
  setDefault(slug: string): Promise<ApiResponse<{ default_slug: string }>> {
    return request.post(`${WF_BASE}/${slug}/default`)
  },
  validate(spec: WorkflowSpecDto): Promise<ApiResponse<{ valid: boolean; errors: string[] }>> {
    return request.post(`${WF_BASE}/validate`, spec)
  },
  validateRun(payload: ValidateRunPayload): Promise<ApiResponse<ValidateRunResult>> {
    return request.post(`${WF_BASE}/validate-run`, payload)
  },
}

// ── agents ──────────────────────────────────────────────────────────────────

export interface AgentSpecDto {
  slug: string
  name: string
  roleDefinition: string
  description?: string
  data_tools?: string[]
  mcp_tools?: string[]
  skills?: string[]
  default_selected?: boolean
  template_inputs?: { slot: string; required_sources?: string[] }[]
}

export interface AgentListItem {
  slug: string
  phase: number
  position?: number
  builtin: boolean
  updated_at?: string
  spec: AgentSpecDto
  referenced_by: string[]
  /** registry 权威报告键（画布输出端口） */
  report_keys?: string[]
  /** registry 权威节点类型（analyst/debater/judge/trader/summarizer；库外按 phase 兜底） */
  kind?: string
  /** registry 权威执行节点名（NodeSpec.node_name 派生锚；库外回退显示名） */
  node_name?: string
  /** registry 权威事件键（NodeSpec.event_key 派生锚；库外回退 slug） */
  event_key?: string
}

export interface AgentDetail {
  spec: AgentSpecDto
  phase: number
  position?: number
  builtin: boolean
  updated_at?: string
  created_at?: string
  referenced_by: string[]
  report_keys?: string[]
  kind?: string
  node_name?: string
  event_key?: string
}

const AG_BASE = '/api/agents'

export const agentApi = {
  list(phase?: number): Promise<ApiResponse<{ agents: AgentListItem[] }>> {
    return request.get(AG_BASE, { params: phase ? { phase } : {} })
  },
  get(slug: string): Promise<ApiResponse<AgentDetail>> {
    return request.get(`${AG_BASE}/${slug}`)
  },
  create(payload: AgentSpecDto & { phase: number }): Promise<ApiResponse<{ spec: AgentSpecDto }>> {
    return request.post(AG_BASE, payload)
  },
  update(
    slug: string,
    payload: AgentSpecDto & { phase: number },
  ): Promise<ApiResponse<{ spec: AgentSpecDto }>> {
    return request.put(`${AG_BASE}/${slug}`, payload)
  },
  remove(slug: string): Promise<ApiResponse<{ slug: string; action: string }>> {
    return request.delete(`${AG_BASE}/${slug}`)
  },
  fork(slug: string, payload: { new_slug: string; name?: string }): Promise<ApiResponse<{ spec: AgentSpecDto }>> {
    return request.post(`${AG_BASE}/${slug}/fork`, payload)
  },
}
