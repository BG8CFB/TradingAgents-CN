import DOMPurify from 'dompurify'
import { marked } from 'marked'

/**
 * 安全地将 Markdown 转换为经过消毒的 HTML
 * 使用 DOMPurify 过滤 XSS 攻击向量
 */

// 配置 marked 的全局选项
marked.setOptions({
  breaks: true,
  gfm: true,
})

/** DOMPurify 消毒配置 */
const PURIFY_CONFIG = {
  ALLOWED_TAGS: [
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'p', 'br', 'hr', 'blockquote',
    'ul', 'ol', 'li',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'a', 'strong', 'em', 'del', 'code', 'pre',
    'img', 'div', 'span', 'sub', 'sup',
  ],
  ALLOWED_ATTR: ['href', 'src', 'alt', 'title', 'class', 'id', 'target'],
  ALLOW_DATA_ATTR: false,
}

export function renderMarkdown(content: string): string {
  if (!content) return ''
  try {
    const rawHtml = marked.parse(content, { async: false }) as string
    return DOMPurify.sanitize(rawHtml, PURIFY_CONFIG)
  } catch (e) {
    return `<pre style="white-space: pre-wrap; font-family: inherit;">${content}</pre>`
  }
}

/**
 * 对已有的 HTML 字符串执行 DOMPurify 消毒
 * 用于需要自定义 marked renderer 的场景（如 Article.vue 的标题锚点）
 */
export function sanitizeHtml(html: string): string {
  if (!html) return ''
  return DOMPurify.sanitize(html, PURIFY_CONFIG)
}