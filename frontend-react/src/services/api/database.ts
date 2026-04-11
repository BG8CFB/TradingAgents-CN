/**
 * 系统数据库管理 API
 * 对应后端 app/routers/database.py（前缀 /api/system/database）
 */

import apiClient from '../http/client'
import type { ApiResponse } from '@/types/common.types'

export interface DatabaseStatus {
  mongodb: Record<string, unknown>
  redis: Record<string, unknown>
}

export interface DatabaseStats {
  total_collections: number
  total_documents: number
  total_size: number
  collections: Array<{ name: string; documents: number; size: number }>
}

export interface BackupInfo {
  id: string
  name: string
  size: number
  created_at: string
  collections: string[]
}

/** 获取数据库状态 */
export async function getDatabaseStatus(): Promise<ApiResponse<DatabaseStatus>> {
  return apiClient.get<DatabaseStatus>('/api/system/database/status')
}

/** 获取数据库统计 */
export async function getDatabaseStats(): Promise<ApiResponse<DatabaseStats>> {
  return apiClient.get<DatabaseStats>('/api/system/database/stats')
}

/** 测试数据库连接 */
export async function testDatabaseConnections(): Promise<ApiResponse<unknown>> {
  return apiClient.post<unknown>('/api/system/database/test')
}

/** 创建备份 */
export async function createBackup(name: string, collections: string[] = []): Promise<ApiResponse<BackupInfo>> {
  return apiClient.post<BackupInfo>('/api/system/database/backup', { name, collections })
}

/** 获取备份列表 */
export async function listBackups(): Promise<ApiResponse<BackupInfo[]>> {
  return apiClient.get<BackupInfo[]>('/api/system/database/backups')
}

/** 删除备份 */
export async function deleteBackup(backupId: string): Promise<ApiResponse<Record<string, never>>> {
  return apiClient.delete<Record<string, never>>(`/api/system/database/backups/${backupId}`)
}

/** 清理旧数据 */
export async function cleanupOldData(days = 30): Promise<ApiResponse<{ deleted_count: number }>> {
  return apiClient.post<{ deleted_count: number }>('/api/system/database/cleanup', { days })
}

/** 清理过期分析结果 */
export async function cleanupAnalysisResults(days = 30): Promise<ApiResponse<{ deleted_count: number }>> {
  return apiClient.post<{ deleted_count: number }>('/api/system/database/cleanup/analysis', { days })
}

/** 清理操作日志 */
export async function cleanupOperationLogs(days = 90): Promise<ApiResponse<{ deleted_count: number }>> {
  return apiClient.post<{ deleted_count: number }>('/api/system/database/cleanup/logs', { days })
}
