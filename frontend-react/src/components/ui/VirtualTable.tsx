import { useRef, useState, useCallback, useLayoutEffect, type ReactNode } from 'react'
import { Spin, Empty } from 'antd'

/**
 * 虚拟滚动列表 — 用于大数据量场景（日志、历史记录等）
 * 仅渲染可视区域内的行，大幅减少 DOM 节点数量
 */
interface VirtualTableProps<T> {
  /** 数据源 */
  data: T[]
  /** 每行渲染函数 */
  rowRenderer: (item: T, index: number) => ReactNode
  /** 行高 (px) */
  rowHeight?: number
  /** 容器高度 (px) */
  height?: number
  /** 是否加载中 */
  loading?: boolean
  /** 空状态描述 */
  emptyText?: string
  /** 接近底部时回调（用于无限滚动） */
  onScrollEnd?: () => void
  /** 类名 */
  className?: string
  /** 样式 */
  style?: React.CSSProperties
}

export default function VirtualTable<T>({
  data,
  rowRenderer,
  rowHeight = 52,
  height = 500,
  loading = false,
  emptyText = '暂无数据',
  onScrollEnd,
  className,
  style,
}: VirtualTableProps<T>) {
  const containerRef = useRef<HTMLDivElement>(null)
  // 使用 ref 存储 scrollTop，避免每次滚动都触发 setState 重渲染
  const scrollTopRef = useRef(0)
  // 仅在可视区域索引变化时才触发重渲染
  const [viewportStart, setViewportStart] = useState(0)
  // 防止 onScrollEnd 重复触发的守卫
  const loadingMoreRef = useRef(false)

  const totalHeight = data.length * rowHeight

  // 从 scrollTop 计算可视区域起始索引
  const computeViewport = useCallback((top: number) => {
    return Math.max(0, Math.floor(top / rowHeight) - 3)
  }, [rowHeight])

  // 可视区域范围
  const visibleCount = Math.ceil(height / rowHeight) + 6 // 上下各缓冲 3 行
  const startIndex = Math.max(0, viewportStart)
  const endIndex = Math.min(data.length, startIndex + visibleCount)

  // 可见数据切片
  const visibleData = data.slice(startIndex, endIndex)

  // 滚动处理 — 使用 rAF 节流，仅在视口变化时更新 state
  const handleScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const newTop = e.currentTarget.scrollTop
    scrollTopRef.current = newTop

    // 检测视口是否变化（优化：仅当起始行号改变时 setState）
    const newStart = computeViewport(newTop)
    if (newStart !== viewportStart) {
      setViewportStart(newStart)
    }

    // 接近底部时触发加载更多（带防抖守卫）
    if (
      onScrollEnd &&
      !loadingMoreRef.current &&
      newTop + height >= totalHeight - rowHeight * 3 &&
      data.length > 0
    ) {
      loadingMoreRef.current = true
      onScrollEnd()
      // 调用者应在数据更新后调用 resetLoadingMore() 或数据变化自动解除
    }
  }, [height, totalHeight, data.length, onScrollEnd, rowHeight, viewportStart, computeViewport])

  // 当数据变化时，重置加载更多守卫（允许再次触发）
  const prevDataLengthRef = useRef(data.length)
  useLayoutEffect(() => {
    if (data.length !== prevDataLengthRef.current) {
      prevDataLengthRef.current = data.length
      loadingMoreRef.current = false
    }
  }, [data.length])

  // 数据量较小时不使用虚拟滚动（直接渲染全部）
  const useVirtual = data.length > 50

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
        <Spin />
      </div>
    )
  }

  if (data.length === 0) {
    return <Empty description={emptyText} style={{ padding: 40 }} />
  }

  // 数据量小，直接渲染
  if (!useVirtual) {
    return (
      <div ref={containerRef} className={className} style={{ ...style, maxHeight: height, overflowY: 'auto' }}>
        {data.map((item, idx) => rowRenderer(item, idx))}
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      className={className}
      style={{
        height,
        overflow: 'auto',
        position: 'relative',
        ...style,
      }}
      onScroll={handleScroll}
    >
      {/* 占位容器撑开滚动条 */}
      <div style={{ height: totalHeight, position: 'relative' }}>
        {/* 偏移到可视位置 */}
        <div
          style={{
            transform: `translateY(${startIndex * rowHeight}px)`,
            position: 'absolute',
            width: '100%',
            left: 0,
            top: 0,
          }}
        >
          {visibleData.map((item, idx) => (
            <div key={`${startIndex + idx}`} style={{ height: rowHeight }}>
              {rowRenderer(item, startIndex + idx)}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
