/**
 * ChatTimeline 组件族共享工具：markdown 渲染结果 memoize。
 * 以原文为 key 缓存 DOMPurify 消毒后的 HTML，避免消息流重渲时重复 parse+sanitize。
 */
import { renderMarkdown } from '@/utils/markdown'

const MD_CACHE_MAX = 300
const mdCache = new Map<string, string>()

export function cachedMarkdown(text: string): string {
  const hit = mdCache.get(text)
  if (hit !== undefined) return hit
  const html = renderMarkdown(text)
  if (mdCache.size >= MD_CACHE_MAX) {
    // 淘汰最旧插入项（Map 迭代序即插入序）
    const oldest = mdCache.keys().next().value
    if (oldest !== undefined) mdCache.delete(oldest)
  }
  mdCache.set(text, html)
  return html
}

/** markdown 气泡的公共 deep 样式类（各消息组件复用，样式定义在 ChatTimeline.vue 内非 scoped 段） */
export const MD_BUBBLE_CLASS = 'md-bubble'
