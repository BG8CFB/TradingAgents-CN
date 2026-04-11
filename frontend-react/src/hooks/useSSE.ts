import { useEffect, useRef, useState, useCallback } from 'react'
import type { SSEProgressData } from '@/types/analysis.types'

interface UseSSEOptions {
  url: string
  onConnected?: () => void
  onProgress?: (data: SSEProgressData) => void
  onError?: (error: string) => void
  onFinished?: (data: SSEProgressData) => void
  autoReconnect?: boolean
  maxReconnectAttempts?: number
}

interface UseSSEReturn {
  isConnected: boolean
  latestData: SSEProgressData | null
  error: string | null
  close: () => void
  reconnect: () => void
}

export function useSSE(options: UseSSEOptions): UseSSEReturn {
  const {
    url,
    onConnected,
    onProgress,
    onError,
    onFinished,
    autoReconnect = true,
    maxReconnectAttempts = 3,
  } = options

  const [isConnected, setIsConnected] = useState(false)
  const [latestData, setLatestData] = useState<SSEProgressData | null>(null)
  const [error, setError] = useState<string | null>(null)

  const esRef = useRef<EventSource | null>(null)
  const reconnectCountRef = useRef(0)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const connectRef = useRef<(() => void) | null>(null)

  const close = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }
    if (esRef.current) {
      esRef.current.close()
      esRef.current = null
    }
    setIsConnected(false)
  }, [])

  const connect = useCallback(() => {
    close()
    setError(null)

    try {
      const es = new EventSource(url, { withCredentials: true })
      esRef.current = es

      es.onopen = () => {
        setIsConnected(true)
        reconnectCountRef.current = 0
      }

      es.addEventListener('connected', (event) => {
        try {
          const data = JSON.parse((event as MessageEvent).data) as SSEProgressData
          setLatestData(data)
          onConnected?.()
        } catch {
          // ignore parse error
        }
      })

      es.addEventListener('progress', (event) => {
        try {
          const data = JSON.parse((event as MessageEvent).data) as SSEProgressData
          setLatestData(data)
          onProgress?.(data)
        } catch {
          // ignore parse error
        }
      })

      es.addEventListener('heartbeat', (event) => {
        try {
          const data = JSON.parse((event as MessageEvent).data) as SSEProgressData
          setLatestData(data)
        } catch {
          // ignore parse error
        }
      })

      es.addEventListener('error', (event) => {
        try {
          const data = JSON.parse((event as MessageEvent).data) as SSEProgressData
          const errMsg = data.error || 'SSE 连接异常'
          setError(errMsg)
          onError?.(errMsg)
        } catch {
          const errMsg = 'SSE 连接异常'
          setError(errMsg)
          onError?.(errMsg)
        }
      })

      es.addEventListener('finished', (event) => {
        try {
          const data = JSON.parse((event as MessageEvent).data) as SSEProgressData
          setLatestData(data)
          onFinished?.(data)
          // 完成后关闭连接
          close()
        } catch {
          // ignore parse error
        }
      })

      es.onerror = () => {
        setIsConnected(false)
        if (autoReconnect && reconnectCountRef.current < maxReconnectAttempts) {
          reconnectCountRef.current += 1
          const delay = Math.min(1000 * Math.pow(2, reconnectCountRef.current), 10000)
          reconnectTimerRef.current = setTimeout(() => {
            connectRef.current?.()
          }, delay)
        } else if (reconnectCountRef.current >= maxReconnectAttempts) {
          const errMsg = 'SSE 重连次数已达上限'
          setError(errMsg)
          onError?.(errMsg)
          close()
        }
      }
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : 'SSE 连接失败'
      setError(errMsg)
      onError?.(errMsg)
    }
  }, [url, autoReconnect, maxReconnectAttempts, onConnected, onProgress, onError, onFinished, close])

  useEffect(() => {
    connectRef.current = connect
  })

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    connect()
    return () => {
      close()
    }
  }, [connect, close])

  return {
    isConnected,
    latestData,
    error,
    close,
    reconnect: connect,
  }
}
