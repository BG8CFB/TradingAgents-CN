<template>
  <div class="category-page">
    <!-- 顶部导航 -->
    <div class="page-nav">
      <div class="nav-inner">
        <button class="back-btn" @click="goBack">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M15 18l-6-6 6-6"/>
          </svg>
          <span>返回学习中心</span>
        </button>
        <div class="breadcrumb">
          <span class="bc-link" @click="goBack">学习中心</span>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 18l6-6-6-6"/>
          </svg>
          <span class="bc-current">{{ categoryInfo.title }}</span>
        </div>
      </div>
    </div>

    <!-- 分类头部 -->
    <div class="category-hero" :style="{ '--accent': categoryInfo.color }">
      <div class="hero-inner">
        <div class="hero-icon">{{ categoryInfo.icon }}</div>
        <div class="hero-body">
          <h1>{{ categoryInfo.title }}</h1>
          <p>{{ categoryInfo.description }}</p>
        </div>
        <div class="hero-stat">
          <span class="stat-num">{{ articles.length }}</span>
          <span class="stat-label">篇文章</span>
        </div>
      </div>
    </div>

    <!-- 文章列表 -->
    <div class="articles-section">
      <div class="articles-list">
        <div
          v-for="article in articles"
          :key="article.id"
          class="article-item"
          @click="openArticle(article.id)"
        >
          <div class="item-left">
            <div class="item-index">
              <span>{{ String(articles.indexOf(article) + 1).padStart(2, '0') }}</span>
            </div>
            <div class="item-body">
              <h3>{{ article.title }}</h3>
              <p>{{ article.description }}</p>
            </div>
          </div>
          <div class="item-right">
            <el-tag :type="article.difficulty" size="small" effect="plain" round>
              {{ article.difficultyText }}
            </el-tag>
            <span class="item-meta">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>
              </svg>
              {{ article.readTime }}
            </span>
            <span class="item-meta">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>
              </svg>
              {{ article.views }}
            </span>
            <svg class="item-arrow" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M9 18l6-6-6-6"/>
            </svg>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const category = computed(() => route.params.category as string)

interface CategoryInfo {
  title: string
  icon: string
  description: string
  color: string
}

const categoryMap: Record<string, CategoryInfo> = {
  'ai-basics': {
    title: 'AI 基础知识',
    icon: '🤖',
    description: '了解大语言模型的核心概念与工作原理，掌握 AI 技术的基本脉络',
    color: '#C5A55A'
  },
  'prompt-engineering': {
    title: '提示词工程',
    icon: '✍️',
    description: '学习编写高质量提示词的方法论，让 AI 更精准地完成分析任务',
    color: '#7CB342'
  },
  'model-selection': {
    title: '模型选择指南',
    icon: '🎯',
    description: '对比主流大语言模型的能力与成本，选择最适合的分析引擎',
    color: '#D4AF37'
  },
  'analysis-principles': {
    title: 'AI 分析股票原理',
    icon: '📊',
    description: '深入理解多智能体协作机制，掌握 AI 驱动股票分析的底层逻辑',
    color: '#5C9CE6'
  },
  'risks-limitations': {
    title: '风险与局限性',
    icon: '⚠️',
    description: '正确认识 AI 辅助分析的边界与潜在风险，理性使用工具',
    color: '#E57373'
  },
  'resources': {
    title: '源项目与论文',
    icon: '📖',
    description: 'TradingAgents 学术论文深度解读与项目资源索引',
    color: '#B76E79'
  },
  'tutorials': {
    title: '实战教程',
    icon: '🎓',
    description: '从零开始使用本平台进行股票分析，跟着教程一步步操作',
    color: '#9C6ADE'
  },
  'faq': {
    title: '常见问题',
    icon: '❓',
    description: '快速找到关于功能使用、模型选择、分析结果等方面的解答',
    color: '#9E9688'
  }
}

const categoryInfo = computed(() => {
  return categoryMap[category.value] || {
    title: '未知分类',
    icon: '📚',
    description: '',
    color: '#9E9688'
  }
})

interface Article {
  id: string
  title: string
  description: string
  readTime: string
  views: number
  difficulty: 'success' | 'warning' | 'danger'
  difficultyText: string
}

const articlesDatabase: Record<string, Article[]> = {
  'ai-basics': [
    {
      id: 'what-is-llm',
      title: '什么是大语言模型（LLM）？',
      description: '深入了解大语言模型的定义、工作原理和在股票分析中的应用',
      readTime: '10分钟',
      views: 2345,
      difficulty: 'success',
      difficultyText: '入门'
    }
  ],
  'prompt-engineering': [
    {
      id: 'prompt-basics',
      title: '提示词基础',
      description: '学习提示词的基本概念、结构和编写技巧',
      readTime: '10分钟',
      views: 1876,
      difficulty: 'success',
      difficultyText: '入门'
    },
    {
      id: 'best-practices',
      title: '提示词工程最佳实践',
      description: '掌握提示词编写的核心原则和实用技巧',
      readTime: '12分钟',
      views: 1543,
      difficulty: 'warning',
      difficultyText: '进阶'
    }
  ],
  'model-selection': [
    {
      id: 'model-comparison',
      title: '大语言模型对比与选择',
      description: '对比主流大语言模型的特点，学会选择最适合的模型',
      readTime: '15分钟',
      views: 1987,
      difficulty: 'warning',
      difficultyText: '进阶'
    }
  ],
  'analysis-principles': [
    {
      id: 'multi-agent-system',
      title: '多智能体系统详解',
      description: '深入理解TradingAgents-CN的多智能体协作机制',
      readTime: '15分钟',
      views: 1654,
      difficulty: 'warning',
      difficultyText: '进阶'
    }
  ],
  'risks-limitations': [
    {
      id: 'risk-warnings',
      title: 'AI股票分析的风险与局限性',
      description: '了解AI的主要局限性、使用风险和正确的使用方式',
      readTime: '12分钟',
      views: 2134,
      difficulty: 'success',
      difficultyText: '入门'
    }
  ],
  'resources': [
    {
      id: 'tradingagents-intro',
      title: 'TradingAgents 项目介绍',
      description: '了解 TradingAgents-CN 的源项目架构和核心特性',
      readTime: '15分钟',
      views: 1432,
      difficulty: 'warning',
      difficultyText: '进阶'
    },
    {
      id: 'paper-guide',
      title: 'TradingAgents 论文解读',
      description: '深度解读 TradingAgents 学术论文的核心内容和创新点',
      readTime: '20分钟',
      views: 987,
      difficulty: 'danger',
      difficultyText: '高级'
    },
    {
      id: 'TradingAgents_论文中文版',
      title: 'TradingAgents 论文中文版',
      description: '完整中文版论文全文，适合深入研究系统设计细节',
      readTime: '40分钟',
      views: 756,
      difficulty: 'danger',
      difficultyText: '高级'
    }
  ],
  'tutorials': [
    {
      id: 'getting-started',
      title: '快速入门教程',
      description: '从零开始学习如何使用 TradingAgents-CN 进行股票分析',
      readTime: '10分钟',
      views: 3456,
      difficulty: 'success',
      difficultyText: '入门'
    },
    {
      id: 'usage-guide-preview',
      title: '使用指南（试用版）',
      description: 'TradingAgents-CN v1.0.0-preview 使用指南与试用说明',
      readTime: '15分钟',
      views: 1288,
      difficulty: 'success',
      difficultyText: '入门'
    }
  ],
  'faq': [
    {
      id: 'general-questions',
      title: '常见问题解答',
      description: '快速找到关于功能、模型选择、使用技巧等常见问题的答案',
      readTime: '15分钟',
      views: 2876,
      difficulty: 'success',
      difficultyText: '入门'
    }
  ]
}

const articles = computed(() => {
  return articlesDatabase[category.value] || []
})

const goBack = () => {
  router.push('/learning')
}

const openArticle = (articleId: string) => {
  const externalMap: Record<string, string> = {
    'getting-started': 'https://mp.weixin.qq.com/s/uAk4RevdJHMuMvlqpdGUEw',
    'usage-guide-preview': 'https://mp.weixin.qq.com/s/ppsYiBncynxlsfKFG8uEbw'
  }
  const external = externalMap[articleId]
  if (external) {
    window.open(external, '_blank')
    return
  }
  router.push(`/learning/article/${articleId}`)
}
</script>

<style scoped lang="scss">
.category-page {
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

  .bc-link {
    cursor: pointer;
    transition: color 0.2s;

    &:hover { color: var(--el-color-primary); }
  }

  .bc-current {
    color: var(--el-text-color-primary);
    font-weight: 500;
  }
}

/* ── Category Hero ── */
.category-hero {
  max-width: 1200px;
  margin: 0 auto;
  padding: 36px 24px 0;

  .hero-inner {
    display: flex;
    align-items: center;
    gap: 24px;
    background: var(--el-fill-color-blank);
    border: 1px solid var(--el-border-color-light);
    border-left: 4px solid var(--accent, var(--el-color-primary));
    border-radius: 14px;
    padding: 28px 32px;
  }

  .hero-icon {
    font-size: 48px;
    flex-shrink: 0;
  }

  .hero-body {
    flex: 1;

    h1 {
      font-size: 24px;
      font-weight: 700;
      color: var(--el-text-color-primary);
      margin: 0 0 8px;
    }

    p {
      font-size: 15px;
      color: var(--el-text-color-secondary);
      line-height: 1.6;
      margin: 0;
    }
  }

  .hero-stat {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
    flex-shrink: 0;

    .stat-num {
      font-size: 32px;
      font-weight: 700;
      color: var(--accent, var(--el-color-primary));
    }

    .stat-label {
      font-size: 13px;
      color: var(--el-text-color-secondary);
    }
  }
}

/* ── Articles List ── */
.articles-section {
  max-width: 1200px;
  margin: 0 auto;
  padding: 28px 24px 48px;
}

.articles-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  background: var(--el-border-color-lighter);
  border: 1px solid var(--el-border-color-light);
  border-radius: 14px;
  overflow: hidden;
}

.article-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  background: var(--el-fill-color-blank);
  padding: 24px 28px;
  cursor: pointer;
  transition: all 0.2s;

  &:hover {
    background: var(--el-color-primary-light-9);

    .item-arrow {
      color: var(--el-color-primary);
      transform: translateX(3px);
    }

    .item-body h3 {
      color: var(--el-color-primary);
    }
  }

  .item-left {
    display: flex;
    align-items: flex-start;
    gap: 20px;
    flex: 1;
    min-width: 0;
  }

  .item-index {
    width: 40px;
    height: 40px;
    border-radius: 10px;
    background: var(--el-fill-color-light);
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;

    span {
      font-size: 14px;
      font-weight: 700;
      color: var(--el-text-color-secondary);
      font-variant-numeric: tabular-nums;
    }
  }

  .item-body {
    flex: 1;
    min-width: 0;

    h3 {
      font-size: 16px;
      font-weight: 600;
      color: var(--el-text-color-primary);
      margin: 0 0 6px;
      transition: color 0.2s;
    }

    p {
      font-size: 14px;
      color: var(--el-text-color-secondary);
      line-height: 1.5;
      margin: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }

  .item-right {
    display: flex;
    align-items: center;
    gap: 16px;
    flex-shrink: 0;
  }

  .item-meta {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 13px;
    color: var(--el-text-color-secondary);
  }

  .item-arrow {
    color: var(--el-text-color-disabled);
    transition: all 0.2s;
  }
}

/* ── Dark Mode ── */
:global(html.dark) {
  .page-nav {
    background: rgba(12, 10, 15, 0.85);
    border-bottom-color: var(--el-border-color);
  }

  .category-hero .hero-inner {
    background: var(--el-fill-color-blank);
    border-color: var(--el-border-color);
    border-left-color: var(--accent, var(--el-color-primary));
  }

  .articles-list {
    background: var(--el-border-color);
    border-color: var(--el-border-color);
  }

  .article-item {
    background: var(--el-fill-color-blank);

    &:hover {
      background: rgba(197, 165, 90, 0.06);
    }
  }

  .item-index {
    background: var(--el-fill-color) !important;
  }
}

/* ── Responsive ── */
@media (max-width: 768px) {
  .nav-inner {
    padding: 0 16px;
  }

  .breadcrumb {
    display: none;
  }

  .category-hero {
    padding: 24px 16px 0;

    .hero-inner {
      flex-direction: column;
      text-align: center;
      padding: 24px;
    }

    .hero-stat {
      flex-direction: row;
      gap: 6px;
    }
  }

  .articles-section {
    padding: 20px 16px 32px;
  }

  .article-item {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
    padding: 20px;

    .item-right {
      width: 100%;
      justify-content: space-between;
      border-top: 1px solid var(--el-border-color-lighter);
      padding-top: 12px;
    }
  }
}
</style>
