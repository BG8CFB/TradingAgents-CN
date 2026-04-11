import { useState, useEffect } from 'react'

/** 默认移动端断点 */
const DEFAULT_BREAKPOINT = 768

/**
 * 响应式检测 Hook — 统一管理移动端状态，带防抖避免高频重渲染
 * Sidebar 和 Header 共用此 Hook，确保 isMobile 状态同步
 */
export default function useIsMobile(breakpoint = DEFAULT_BREAKPOINT) {
  const [isMobile, setIsMobile] = useState(() => window.innerWidth < breakpoint)

  useEffect(() => {
    let rafId: number | null = null

    const checkMobile = () => {
      // 使用 requestAnimationFrame 节流：每帧最多执行一次
      if (rafId !== null) return
      rafId = requestAnimationFrame(() => {
        rafId = null
        const mobile = window.innerWidth < breakpoint
        setIsMobile((prev) => {
          // 仅在值变化时更新，避免不必要的重渲染
          if (prev === mobile) return prev
          return mobile
        })
      })
    }

    checkMobile()
    window.addEventListener('resize', checkMobile)

    return () => {
      window.removeEventListener('resize', checkMobile)
      if (rafId !== null) cancelAnimationFrame(rafId)
    }
  }, [breakpoint])

  return isMobile
}
