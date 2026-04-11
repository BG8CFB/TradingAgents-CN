/** 筛选字段信息 */
export interface ScreeningFieldInfo {
  name: string
  type: string
  label?: string
  description?: string
  min?: number
  max?: number
  unit?: string
}

/** 筛选字段配置响应 */
export interface ScreeningFieldConfig {
  fields: Record<string, ScreeningFieldInfo>
  categories: Record<string, string[]>
}

/** 排序项 */
export interface ScreeningOrderBy {
  field: string
  direction?: 'asc' | 'desc'
}

/** 传统筛选条件子项 */
export interface ScreeningConditionChild {
  field: string
  op: 'between' | 'gt' | 'lt' | 'gte' | 'lte' | 'eq' | 'ne' | 'in' | 'contains'
  value: unknown
}

/** 传统筛选条件 */
export interface ScreeningConditions {
  logic?: 'AND' | 'OR'
  children: ScreeningConditionChild[]
}

/** 传统筛选请求 */
export interface ScreeningRequest {
  market?: string
  date?: string
  adj?: string
  conditions?: ScreeningConditions
  order_by?: ScreeningOrderBy[]
  limit?: number
  offset?: number
}

/** 传统筛选响应 */
export interface ScreeningResponse {
  total: number
  items: Record<string, unknown>[]
}

/** 增强筛选条件 */
export interface EnhancedScreeningCondition {
  field: string
  operator: string
  value: unknown
}

/** 增强筛选请求 */
export interface EnhancedScreeningRequest {
  conditions: EnhancedScreeningCondition[]
  market?: string
  date?: string
  adj?: string
  order_by?: ScreeningOrderBy[]
  limit?: number
  offset?: number
  use_database_optimization?: boolean
}

/** 增强筛选响应 */
export interface EnhancedScreeningResponse {
  total: number
  items: Record<string, unknown>[]
  took_ms?: number
  optimization_used?: boolean
  source?: string
}

/** 行业项 */
export interface IndustryItem {
  value: string
  label: string
  count: number
}
