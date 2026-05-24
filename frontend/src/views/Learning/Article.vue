<template>
  <div class="article-page">
    <!-- 顶部导航栏 -->
    <div class="page-nav">
      <div class="nav-inner">
        <button class="back-btn" @click="goBack">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M15 18l-6-6 6-6"/>
          </svg>
          <span>返回</span>
        </button>
        <div class="breadcrumb">
          <span class="bc-link" @click="goBack">学习中心</span>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 18l6-6-6-6"/>
          </svg>
          <span class="bc-current">{{ article.title }}</span>
        </div>
        <div class="nav-actions">
          <button class="action-btn" @click="toggleToc" title="目录">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="15" y2="12"/><line x1="3" y1="18" x2="18" y2="18"/>
            </svg>
          </button>
          <button class="action-btn" @click="downloadArticle" title="下载">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
            </svg>
          </button>
        </div>
      </div>
    </div>

    <!-- 主内容区 -->
    <div class="article-body">
      <!-- 文章容器 -->
      <div class="article-main">
        <!-- 文章头部 -->
        <header class="article-header">
          <h1 class="article-title">{{ article.title }}</h1>
          <div class="article-meta">
            <span class="meta-tag" :style="{ background: categoryColor }">
              {{ article.category }}
            </span>
            <span class="meta-item">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>
              </svg>
              {{ article.readTime }}
            </span>
            <span class="meta-item">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>
              </svg>
              {{ article.updateTime }}
            </span>
          </div>
          <div class="header-divider"></div>
        </header>

        <!-- 文章内容 -->
        <article class="article-content" v-html="article.content"></article>

        <!-- 文章底部导航 -->
        <footer class="article-footer">
          <div class="footer-divider"></div>
          <div class="nav-buttons">
            <button v-if="prevArticle" class="nav-btn nav-prev" @click="navigateToArticle(prevArticle.id)">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M19 12H5M12 19l-7-7 7-7"/>
              </svg>
              <div class="nav-btn-body">
                <span class="nav-btn-label">上一篇</span>
                <span class="nav-btn-title">{{ prevArticle.title }}</span>
              </div>
            </button>
            <div v-else></div>
            <button v-if="nextArticle" class="nav-btn nav-next" @click="navigateToArticle(nextArticle.id)">
              <div class="nav-btn-body" style="text-align: right">
                <span class="nav-btn-label">下一篇</span>
                <span class="nav-btn-title">{{ nextArticle.title }}</span>
              </div>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M5 12h14M12 5l7 7-7 7"/>
              </svg>
            </button>
          </div>
        </footer>
      </div>

      <!-- 侧边栏目录 -->
      <aside class="article-toc" :class="{ 'toc-visible': tocVisible, 'toc-hidden': !tocVisible }">
        <div class="toc-sticky">
          <div class="toc-header">
            <span class="toc-title">目录</span>
            <button class="toc-close" @click="toggleToc">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M15 18l-6-6 6-6"/>
              </svg>
            </button>
          </div>
          <nav class="toc-list">
            <a
              v-for="heading in tableOfContents"
              :key="heading.id"
              :class="['toc-link', `toc-level-${heading.level}`, { 'toc-active': activeHeading === heading.id }]"
              @click.prevent="scrollToHeading(heading.id)"
            >
              {{ heading.text }}
            </a>
          </nav>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { marked } from 'marked'
import { sanitizeHtml } from '@/utils/markdown'

const route = useRoute()
const router = useRouter()

const articleId = computed(() => route.params.id as string)
const tocVisible = ref(true)
const activeHeading = ref('')

type ArticleInfo = {
  title: string
  category: string
  categoryType: any
  categoryColor?: string
  readTime: string
  loader?: () => Promise<any>
  externalUrl?: string
}

const registry: Record<string, ArticleInfo> = {
  'what-is-llm': { title: '什么是大语言模型（LLM）？', loader: () => import('../../../../frontend/docs/learning/01-ai-basics/what-is-llm.md?raw'), category: 'AI 基础知识', categoryType: 'primary', categoryColor: 'rgba(197,165,90,0.12)', readTime: '10 分钟' },
  'prompt-basics': { title: '提示词基础', loader: () => import('../../../../frontend/docs/learning/02-prompt-engineering/prompt-basics.md?raw'), category: '提示词工程', categoryType: 'success', categoryColor: 'rgba(124,179,66,0.12)', readTime: '10 分钟' },
  'best-practices': { title: '提示词工程最佳实践', loader: () => import('../../../../frontend/docs/learning/02-prompt-engineering/best-practices.md?raw'), category: '提示词工程', categoryType: 'success', categoryColor: 'rgba(124,179,66,0.12)', readTime: '12 分钟' },
  'model-comparison': { title: '大语言模型对比与选择', loader: () => import('../../../../frontend/docs/learning/03-model-selection/model-comparison.md?raw'), category: '模型选择指南', categoryType: 'warning', categoryColor: 'rgba(212,175,55,0.12)', readTime: '15 分钟' },
  'multi-agent-system': { title: '多智能体系统详解', loader: () => import('../../../../frontend/docs/learning/04-analysis-principles/multi-agent-system.md?raw'), category: 'AI 分析原理', categoryType: 'info', categoryColor: 'rgba(92,156,230,0.12)', readTime: '15 分钟' },
  'risk-warnings': { title: 'AI股票分析的风险与局限性', loader: () => import('../../../../frontend/docs/learning/05-risks-limitations/risk-warnings.md?raw'), category: '风险与局限性', categoryType: 'danger', categoryColor: 'rgba(229,115,115,0.12)', readTime: '12 分钟' },
  'tradingagents-intro': { title: 'TradingAgents项目介绍', loader: () => import('../../../../frontend/docs/learning/06-resources/tradingagents-intro.md?raw'), category: '源项目与论文', categoryType: 'primary', categoryColor: 'rgba(183,110,121,0.12)', readTime: '15 分钟' },
  'paper-guide': { title: 'TradingAgents论文解读', loader: () => import('../../../../frontend/docs/learning/06-resources/paper-guide.md?raw'), category: '源项目与论文', categoryType: 'primary', categoryColor: 'rgba(183,110,121,0.12)', readTime: '20 分钟' },
  'TradingAgents_论文中文版': { title: 'TradingAgents 论文中文版', loader: () => import('../../../../frontend/docs/paper/TradingAgents_论文中文版.md?raw'), category: '源项目与论文', categoryType: 'primary', categoryColor: 'rgba(183,110,121,0.12)', readTime: '40 分钟' },
  'getting-started': { title: '快速入门教程（外链）', externalUrl: 'https://mp.weixin.qq.com/s/uAk4RevdJHMuMvlqpdGUEw', category: '实战教程', categoryType: 'success', categoryColor: 'rgba(156,106,222,0.12)', readTime: '10 分钟' },
  'usage-guide-preview': { title: '使用指南（试用版）', externalUrl: 'https://mp.weixin.qq.com/s/ppsYiBncynxlsfKFG8uEbw', category: '实战教程', categoryType: 'success', categoryColor: 'rgba(156,106,222,0.12)', readTime: '15 分钟' },
  'general-questions': { title: '常见问题解答', loader: () => import('../../../../frontend/docs/learning/08-faq/general-questions.md?raw'), category: '常见问题', categoryType: 'info', categoryColor: 'rgba(158,150,136,0.12)', readTime: '15 分钟' }
}

const articleOrder = [
  'what-is-llm',
  'prompt-basics',
  'best-practices',
  'model-comparison',
  'multi-agent-system',
  'risk-warnings',
  'tradingagents-intro',
  'paper-guide',
  'TradingAgents_论文中文版',
  'getting-started',
  'usage-guide-preview',
  'general-questions'
]

const article = ref({
  id: '',
  title: '',
  category: '',
  categoryType: 'primary' as any,
  readTime: '',
  views: 0,
  updateTime: '',
  content: ''
})

const categoryColor = computed(() => {
  const info = registry[article.value.id]
  return info?.categoryColor || 'rgba(197,165,90,0.12)'
})

const tableOfContents = ref<{ id: string; text: string; level: number }[]>([])
const prevArticle = ref<{ id: string; title: string } | null>(null)
const nextArticle = ref<{ id: string; title: string } | null>(null)

const goBack = () => {
  router.back()
}

const toggleToc = () => {
  tocVisible.value = !tocVisible.value
}

const downloadArticle = async () => {
  if (!article.value.id) return
  const info = registry[article.value.id]
  if (!info) {
    ElMessage.warning('未找到文章资源')
    return
  }
  if (info.externalUrl) {
    window.open(info.externalUrl, '_blank')
    return
  }
  try {
    const mod = info.loader ? await info.loader() : ''
    const md: string = typeof mod === 'string' ? mod : (mod.default || '')
    const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${article.value.id}.md`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  } catch (e) {
    console.error(e)
    ElMessage.error('下载失败')
  }
}

const navigateToArticle = (id: string) => {
  router.push(`/learning/article/${id}`)
}

const scrollToHeading = (id: string) => {
  const element = document.getElementById(id)
  if (element) {
    element.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

// 滚动时高亮当前目录项
function updateActiveHeading() {
  for (let i = tableOfContents.value.length - 1; i >= 0; i--) {
    const heading = tableOfContents.value[i]
    const el = document.getElementById(heading.id)
    if (el) {
      const rect = el.getBoundingClientRect()
      if (rect.top <= 120) {
        activeHeading.value = heading.id
        return
      }
    }
  }
  activeHeading.value = ''
}

function convertLocalLinks(html: string): string {
  const div = document.createElement('div')
  div.innerHTML = html
  const links = div.querySelectorAll('a')
  for (const link of links) {
    const href = link.getAttribute('href')
    if (href && href.endsWith('.md')) {
      const fileName = href.split('/').pop()?.replace('.md', '')
      if (fileName && registry[fileName]) {
        link.setAttribute('href', `/learning/article/${fileName}`)
        link.setAttribute('data-internal', 'true')
      }
    } else if (href && href.endsWith('.pdf')) {
      const fileName = href.split('/').pop() || ''
      if (fileName) {
        const target = href.includes('/paper/') ? `/paper/${fileName}` : `/assets/${fileName}`
        link.setAttribute('href', target)
        link.setAttribute('target', '_blank')
        link.setAttribute('rel', 'noopener noreferrer')
      }
    }
  }
  return div.innerHTML
}

function rewriteImageSrc(html: string): string {
  const div = document.createElement('div')
  div.innerHTML = html
  const assetMap: Record<string, string> = {
    'assets/schema.png': '/assets/schema.png',
    'assets/analyst.png': '/assets/analyst.png',
    'assets/researcher.png': '/assets/researcher.png',
    'assets/trader.png': '/assets/trader.png',
    'assets/risk.png': '/assets/risk.png'
  }
  const imgs = div.querySelectorAll('img')
  for (const img of imgs) {
    const src = img.getAttribute('src') || ''
    if (src.startsWith('/')) continue
    for (const key in assetMap) {
      if (src.endsWith(key)) {
        img.setAttribute('src', assetMap[key])
        break
      }
    }
  }
  return div.innerHTML
}

async function loadArticle(id: string) {
  const info = registry[id]
  if (!info) {
    ElMessage.error('未找到文章')
    return
  }
  if (info.externalUrl) {
    window.open(info.externalUrl, '_blank')
    article.value = {
      id,
      title: info.title,
      category: info.category,
      categoryType: info.categoryType,
      readTime: info.readTime,
      views: 0,
      updateTime: new Date().toISOString().slice(0, 10),
      content: ''
    }
    ElMessage.info('已在新标签页打开外部页面')
    return
  }
  article.value = {
    id,
    title: info.title,
    category: info.category,
    categoryType: info.categoryType,
    readTime: info.readTime,
    views: 0,
    updateTime: new Date().toISOString().slice(0, 10),
    content: ''
  }

  try {
    const mod = info.loader ? await info.loader() : ''
    const md: string = typeof mod === 'string' ? mod : (mod.default || '')
    const renderer = new marked.Renderer()
    renderer.heading = function ({ tokens, depth, text }: any) {
      let htmlText = ''
      if (Array.isArray(tokens) && tokens.length) {
        htmlText = this.parser.parseInline(tokens)
      } else if (typeof text === 'string') {
        htmlText = marked.parseInline(text) as string
      }
      const plain = (htmlText || '').replace(/<[^>]+>/g, '')
      const id = plain
        .toLowerCase()
        .replace(/[^\w一-龥]+/g, '-')
        .replace(/^-+|-+$/g, '')
      return `<h${depth} class="article-heading" id="${id}">${htmlText}</h${depth}>`
    }
    marked.setOptions({ renderer })
    let html = marked.parse(md) as string
    html = sanitizeHtml(html)
    html = convertLocalLinks(html)
    html = rewriteImageSrc(html)
    article.value.content = html
    await nextTick()
    buildTOCFromHTML(html)
    buildPrevNext(id)
    setupInternalLinks()
  } catch (e) {
    console.error(e)
    ElMessage.error('加载文章失败：无法访问文档资源')
  }
}

function buildTOCFromHTML(html: string) {
  const div = document.createElement('div')
  div.innerHTML = html
  const headings = Array.from(div.querySelectorAll('h2, h3, h4')) as HTMLHeadingElement[]
  tableOfContents.value = headings.map(h => ({
    id: h.id || h.textContent?.trim().toLowerCase().replace(/\s+/g, '-') || '',
    text: h.textContent || '',
    level: Number(h.tagName.substring(1))
  }))
}

function setupInternalLinks() {
  nextTick(() => {
    const container = document.querySelector('.article-content')
    if (!container) return
    const links = container.querySelectorAll('a[data-internal="true"]')
    for (const link of links) {
      link.addEventListener('click', (e) => {
        e.preventDefault()
        const href = link.getAttribute('href')
        if (href) {
          router.push(href)
        }
      })
    }
  })
}

function buildPrevNext(id: string) {
  const idx = articleOrder.indexOf(id)
  prevArticle.value = idx > 0 ? { id: articleOrder[idx - 1], title: registry[articleOrder[idx - 1]].title } : null
  nextArticle.value = idx >= 0 && idx < articleOrder.length - 1 ? { id: articleOrder[idx + 1], title: registry[articleOrder[idx + 1]].title } : null
}

let scrollHandler: (() => void) | null = null

onMounted(() => {
  loadArticle(articleId.value)
  scrollHandler = updateActiveHeading
  window.addEventListener('scroll', scrollHandler, { passive: true })
})

onUnmounted(() => {
  if (scrollHandler) {
    window.removeEventListener('scroll', scrollHandler)
  }
})

watch(articleId, (id) => {
  loadArticle(id)
})
</script>

<style scoped lang="scss">
.article-page {
  min-height: 100vh;
}

/* ── Nav ── */
.page-nav {
  position: sticky;
  top: 0;
  z-index: 10;
  background: var(--el-bg-color);
  border-bottom: 1px solid var(--el-border-color-light);
  backdrop-filter: blur(12px);
}

.nav-inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 24px;
  height: 52px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.back-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  background: none;
  border: none;
  cursor: pointer;
  font-size: 14px;
  color: var(--el-text-color-regular);
  padding: 6px 12px;
  border-radius: 8px;
  transition: all 0.2s;

  &:hover {
    background: var(--el-fill-color-light);
    color: var(--el-color-primary);
  }
}

.breadcrumb {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  overflow: hidden;

  .bc-link {
    cursor: pointer;
    flex-shrink: 0;
    transition: color 0.2s;
    &:hover { color: var(--el-color-primary); }
  }

  svg { flex-shrink: 0; }

  .bc-current {
    color: var(--el-text-color-primary);
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.nav-actions {
  display: flex;
  gap: 4px;
}

.action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 8px;
  border: none;
  background: none;
  cursor: pointer;
  color: var(--el-text-color-secondary);
  transition: all 0.2s;

  &:hover {
    background: var(--el-fill-color-light);
    color: var(--el-color-primary);
  }
}

/* ── Article Body ── */
.article-body {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 24px;
  display: flex;
  gap: 40px;
}

.article-main {
  flex: 1;
  min-width: 0;
  max-width: 100%;
}

/* ── Article Header ── */
.article-header {
  padding-top: 40px;

  .article-title {
    font-size: 32px;
    font-weight: 800;
    line-height: 1.3;
    color: var(--el-text-color-primary);
    margin: 0 0 20px;
    letter-spacing: -0.5px;
  }

  .article-meta {
    display: flex;
    align-items: center;
    gap: 14px;
    flex-wrap: wrap;
    margin-bottom: 24px;
  }

  .meta-tag {
    font-size: 12px;
    font-weight: 600;
    padding: 4px 12px;
    border-radius: 6px;
    color: var(--el-color-primary);
  }

  .meta-item {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 13px;
    color: var(--el-text-color-secondary);
  }

  .header-divider {
    height: 2px;
    background: linear-gradient(90deg, var(--el-color-primary), var(--el-color-primary-light-7), transparent);
    border-radius: 1px;
    margin-bottom: 40px;
  }
}

/* ── Article Content ── */
.article-content {
  font-size: 16px;
  line-height: 1.9;
  color: var(--el-text-color-primary);
  word-break: break-word;

  :deep(h1) {
    font-size: 28px;
    font-weight: 700;
    margin: 48px 0 20px;
    padding-bottom: 12px;
    border-bottom: 2px solid var(--el-border-color-light);
    color: var(--el-text-color-primary);
    letter-spacing: -0.3px;
  }

  :deep(h2) {
    font-size: 24px;
    font-weight: 700;
    margin: 40px 0 16px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--el-border-color-lighter);
    color: var(--el-text-color-primary);
    letter-spacing: -0.2px;
  }

  :deep(h3) {
    font-size: 20px;
    font-weight: 600;
    margin: 28px 0 12px;
    color: var(--el-text-color-primary);
  }

  :deep(h4) {
    font-size: 18px;
    font-weight: 600;
    margin: 24px 0 10px;
    color: var(--el-text-color-primary);
  }

  :deep(p) {
    margin: 18px 0;
    text-align: justify;
  }

  :deep(ul), :deep(ol) {
    margin: 18px 0;
    padding-left: 24px;

    li {
      margin: 6px 0;
      line-height: 1.8;
    }
  }

  :deep(strong) {
    font-weight: 600;
    color: var(--el-text-color-primary);
  }

  :deep(code) {
    background: var(--el-fill-color-light);
    padding: 2px 8px;
    border-radius: 4px;
    font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
    font-size: 0.9em;
    color: var(--el-color-primary-dark-2);
  }

  :deep(pre) {
    background: var(--el-fill-color);
    padding: 20px 24px;
    border-radius: 12px;
    overflow-x: auto;
    margin: 24px 0;
    border: 1px solid var(--el-border-color-lighter);
    line-height: 1.7;

    code {
      background: none;
      padding: 0;
      color: inherit;
      font-size: 14px;
    }
  }

  :deep(blockquote) {
    border-left: 4px solid var(--el-color-primary);
    margin: 24px 0;
    padding: 16px 20px;
    color: var(--el-text-color-regular);
    background: var(--el-color-primary-light-9);
    border-radius: 0 8px 8px 0;
    font-style: italic;
  }

  :deep(img) {
    max-width: 100%;
    height: auto;
    display: block;
    margin: 24px auto;
    border-radius: 8px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  }

  :deep(table) {
    width: 100%;
    border-collapse: collapse;
    margin: 24px 0;
    font-size: 14px;

    th, td {
      padding: 10px 16px;
      border: 1px solid var(--el-border-color-light);
      text-align: left;
    }

    th {
      background: var(--el-fill-color-light);
      font-weight: 600;
      color: var(--el-text-color-primary);
    }

    tr:hover td {
      background: var(--el-fill-color-lighter);
    }
  }

  :deep(a) {
    color: var(--el-color-primary);
    text-decoration: none;
    border-bottom: 1px solid transparent;
    transition: border-color 0.2s;

    &:hover {
      border-bottom-color: var(--el-color-primary);
    }
  }

  :deep(hr) {
    border: none;
    height: 1px;
    background: var(--el-border-color-light);
    margin: 36px 0;
  }
}

/* ── Article Footer ── */
.article-footer {
  padding: 32px 0 64px;

  .footer-divider {
    height: 1px;
    background: var(--el-border-color-light);
    margin-bottom: 32px;
  }

  .nav-buttons {
    display: flex;
    justify-content: space-between;
    gap: 20px;
  }

  .nav-btn {
    display: flex;
    align-items: center;
    gap: 12px;
    background: var(--el-fill-color-blank);
    border: 1px solid var(--el-border-color-light);
    border-radius: 12px;
    padding: 16px 20px;
    cursor: pointer;
    flex: 1;
    max-width: 380px;
    transition: all 0.2s;

    &:hover {
      border-color: var(--el-color-primary-light-5);
      background: var(--el-color-primary-light-9);
    }

    &.nav-next {
      margin-left: auto;
    }

    svg {
      flex-shrink: 0;
      color: var(--el-text-color-secondary);
    }
  }

  .nav-btn-body {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .nav-btn-label {
    font-size: 12px;
    color: var(--el-text-color-secondary);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .nav-btn-title {
    font-size: 14px;
    font-weight: 500;
    color: var(--el-text-color-primary);
    line-height: 1.4;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 260px;
  }
}

/* ── TOC ── */
.article-toc {
  width: 240px;
  flex-shrink: 0;
  transition: all 0.3s ease;

  &.toc-hidden {
    width: 0;
    overflow: hidden;
    opacity: 0;
  }
}

.toc-sticky {
  position: sticky;
  top: 72px;
  max-height: calc(100vh - 96px);
  overflow-y: auto;
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-light);
  border-radius: 12px;
  padding: 16px;
}

.toc-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.toc-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.toc-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: none;
  background: none;
  cursor: pointer;
  color: var(--el-text-color-secondary);
  transition: all 0.2s;

  &:hover {
    background: var(--el-fill-color-light);
    color: var(--el-color-primary);
  }
}

.toc-list {
  display: flex;
  flex-direction: column;
}

.toc-link {
  display: block;
  padding: 6px 0 6px 12px;
  font-size: 13px;
  line-height: 1.5;
  color: var(--el-text-color-secondary);
  cursor: pointer;
  text-decoration: none;
  border-left: 2px solid transparent;
  transition: all 0.2s;

  &:hover {
    color: var(--el-color-primary);
    border-left-color: var(--el-color-primary-light-5);
  }

  &.toc-active {
    color: var(--el-color-primary);
    border-left-color: var(--el-color-primary);
    font-weight: 500;
  }

  &.toc-level-3 {
    padding-left: 24px;
    font-size: 12px;
  }

  &.toc-level-4 {
    padding-left: 36px;
    font-size: 12px;
  }
}

/* ── Dark Mode ── */
:global(html.dark) {
  .page-nav {
    background: rgba(12, 10, 15, 0.85);
    border-bottom-color: var(--el-border-color);
  }

  .article-header {
    .meta-tag {
      color: var(--el-color-primary) !important;
    }

    .header-divider {
      background: linear-gradient(90deg, var(--el-color-primary), var(--el-color-primary-light-7), transparent);
    }
  }

  .article-content {
    :deep(h1), :deep(h2), :deep(h3), :deep(h4) {
      color: var(--el-text-color-primary) !important;
    }

    :deep(h1) { border-bottom-color: var(--el-border-color) !important; }
    :deep(h2) { border-bottom-color: var(--el-border-color) !important; }

    :deep(pre) {
      background: var(--el-fill-color) !important;
      border-color: var(--el-border-color);
    }

    :deep(blockquote) {
      background: rgba(197, 165, 90, 0.06) !important;
      border-left-color: var(--el-color-primary) !important;
    }

    :deep(code) {
      background: var(--el-fill-color) !important;
      color: var(--el-color-primary) !important;
    }

    :deep(table th) {
      background: var(--el-fill-color);
    }

    :deep(img) {
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    }
  }

  .nav-btn {
    background: var(--el-fill-color-blank);
    border-color: var(--el-border-color);

    &:hover {
      border-color: var(--el-color-primary-dark-2);
      background: rgba(197, 165, 90, 0.06);
    }
  }

  .toc-sticky {
    background: var(--el-fill-color-blank);
    border-color: var(--el-border-color);
  }

  .toc-header {
    border-bottom-color: var(--el-border-color);
  }
}

/* ── Responsive ── */
@media (max-width: 1200px) {
  .article-toc {
    display: none;
  }
  .article-body {
    justify-content: center;
  }
  .article-main {
    max-width: 780px;
  }
}

@media (max-width: 768px) {
  .nav-inner {
    padding: 0 16px;
  }

  .breadcrumb {
    display: none;
  }

  .article-body {
    padding: 0 16px;
  }

  .article-header {
    padding-top: 24px;

    .article-title {
      font-size: 24px;
    }

    .header-divider {
      margin-bottom: 24px;
    }
  }

  .article-content {
    font-size: 15px;

    :deep(h1) { font-size: 22px; }
    :deep(h2) { font-size: 20px; }
    :deep(h3) { font-size: 18px; }
  }

  .article-footer {
    .nav-buttons {
      flex-direction: column;
    }

    .nav-btn {
      max-width: 100%;
    }
  }
}
</style>
