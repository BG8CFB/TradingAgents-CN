import { useEffect, useState, useCallback } from 'react'
import { getAnalysisStats, getUserQueueStatus, type AnalysisStats, type QueueStatus } from '@/services/api/analysis'
import { getReportList, type ReportItem } from '@/services/api/reports'

export interface DashboardData {
  stats: AnalysisStats | null
  queue: QueueStatus | null
  recentReports: ReportItem[]
  loading: boolean
  error: string | null
}

export function useDashboardData(): DashboardData & { refresh: () => void } {
  const [stats, setStats] = useState<AnalysisStats | null>(null)
  const [queue, setQueue] = useState<QueueStatus | null>(null)
  const [recentReports, setRecentReports] = useState<ReportItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(() => {
    setLoading(true)
    setError(null)

    Promise.all([
      getAnalysisStats({}).catch((e) => {
        console.warn('获取分析统计失败:', e)
        return null
      }),
      getUserQueueStatus().catch((e) => {
        console.warn('获取队列状态失败:', e)
        return null
      }),
      getReportList({ page: 1, page_size: 5 }).catch((e) => {
        console.warn('获取报告列表失败:', e)
        return null
      }),
    ])
      .then(([statsRes, queueRes, reportsRes]) => {
        if (statsRes?.data) setStats(statsRes.data as AnalysisStats)
        if (queueRes?.data) setQueue(queueRes.data as QueueStatus)
        if (reportsRes?.data?.reports) setRecentReports(reportsRes.data.reports as ReportItem[])
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : '数据加载失败')
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    // 数据获取在 effect 中调用是标准做法；规则在此处为 false positive
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchData()
  }, [fetchData])

  return { stats, queue, recentReports, loading, error, refresh: fetchData }
}
