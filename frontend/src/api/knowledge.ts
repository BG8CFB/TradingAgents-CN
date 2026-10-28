/**
 * 知识库 API — 语料概览 / 索引状态与重建 / 检索测试 / 引用计数
 */
import { ApiClient } from './request'
import type { ApiResponse } from './request'

export interface KbIndexState {
  status: 'pending' | 'indexing' | 'rebuilding' | 'ready' | 'error' | 'skipped' | string
  embedding_model?: string | null
  embedding_provider?: string | null
  dimension?: number | null
  checkpoint?: string | null
  last_run?: string | null
  last_error?: string | null
}

export interface KbMarketOverview {
  market: string
  corpus_count: number
  indexed_count: number
  latest_publish_time?: string | null
  index_state: KbIndexState
}

export interface KbEmbeddingStatus {
  configured: boolean
  provider?: string | null
  model_name?: string | null
  dimension?: number | null
  source?: string | null
  message?: string
}

export interface KbOverview {
  markets: KbMarketOverview[]
  embedding: KbEmbeddingStatus
}

export interface KbSearchResult {
  title: string
  data_source: string
  publish_time: string
  type: string
  snippet: string
  url?: string
  symbol?: string
  similarity: number
}

export interface KbCitationRecord {
  task_id: string
  agent_key: string
  symbol?: string
  analysis_date?: string
  injected_count: number
  cited_refs?: number[]
  cited_count: number
  invalid_citations?: number[]
  invalid_count: number
  created_at?: string
}

export const knowledgeApi = {
  /** 语料概览 + 索引状态 + 向量模型配置（概览/索引状态两 tab 共用） */
  getOverview(): Promise<ApiResponse<KbOverview>> {
    return ApiClient.get<KbOverview>('/api/knowledge/overview')
  },

  /** 检索测试：symbol + 关键词 + 时间窗 → top-K 与出处 */
  search(params: {
    market: string
    symbol: string
    query: string
    as_of?: string
    start_date?: string
    top_k?: number
    types?: string[]
  }): Promise<ApiResponse<{ results: KbSearchResult[]; count: number }>> {
    return ApiClient.post<{ results: KbSearchResult[]; count: number }>(
      '/api/knowledge/search',
      params
    )
  },

  /** 手动触发一轮增量索引（后台执行，进度靠 overview 轮询） */
  runIndex(): Promise<ApiResponse<{ message: string }>> {
    return ApiClient.post<{ message: string }>('/api/knowledge/index', {})
  },

  /** 全量重建索引（切换向量模型/维度后必须执行；market 空 = 全部市场） */
  rebuild(market?: string): Promise<ApiResponse<{ message: string }>> {
    return ApiClient.post<{ message: string }>('/api/knowledge/rebuild', { market: market || null })
  },

  /** 引用校验计数（记分卡「引用有效率」数据源） */
  getCitations(params?: {
    task_id?: string
    agent_key?: string
    limit?: number
  }): Promise<ApiResponse<{ records: KbCitationRecord[] }>> {
    return ApiClient.get<{ records: KbCitationRecord[] }>('/api/knowledge/citations', params)
  },
}
