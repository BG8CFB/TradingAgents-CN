<template>
  <div class="learning-center">
    <!-- Hero Banner -->
    <div class="hero">
      <div class="hero-bg">
        <div class="hero-orb hero-orb-1"></div>
        <div class="hero-orb hero-orb-2"></div>
        <div class="hero-orb hero-orb-3"></div>
      </div>
      <div class="hero-content">
        <div class="hero-badge">Learning Center</div>
        <h1 class="hero-title">学习中心</h1>
        <p class="hero-desc">
          从 AI 基础到智能投研实战，系统化构建你的知识体系
        </p>
        <div class="hero-stats">
          <div class="stat-item">
            <span class="stat-num">{{ totalArticles }}</span>
            <span class="stat-label">篇教程</span>
          </div>
          <div class="stat-divider"></div>
          <div class="stat-item">
            <span class="stat-num">{{ categories.length }}</span>
            <span class="stat-label">个专题</span>
          </div>
          <div class="stat-divider"></div>
          <div class="stat-item">
            <span class="stat-num">{{ totalReadTime }}</span>
            <span class="stat-label">阅读</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 学习路径 -->
    <div class="section">
      <div class="section-header">
        <h2 class="section-title">学习路径</h2>
        <p class="section-subtitle">按顺序学习，循序渐进掌握 AI 投资分析</p>
      </div>
      <div class="pathway">
        <div
          v-for="(cat, idx) in categories"
          :key="cat.slug"
          class="pathway-node"
          @click="navigateTo(cat.slug)"
        >
          <div class="pathway-connector" v-if="idx < categories.length - 1">
            <div class="connector-line"></div>
            <div class="connector-arrow">
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                <path d="M2 4L6 8L10 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
              </svg>
            </div>
          </div>
          <div class="pathway-card" :style="{ '--card-accent': cat.color }">
            <div class="pathway-step">Step {{ idx + 1 }}</div>
            <div class="pathway-icon">{{ cat.icon }}</div>
            <div class="pathway-info">
              <h3>{{ cat.title }}</h3>
              <p>{{ cat.description }}</p>
            </div>
            <div class="pathway-meta">
              <el-tag size="small" effect="plain" round>{{ cat.count }} 篇</el-tag>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 推荐阅读 -->
    <div class="section">
      <div class="section-header">
        <h2 class="section-title">推荐阅读</h2>
        <p class="section-subtitle">精选入门必读文章，快速上手本平台</p>
      </div>
      <div class="recommended-grid">
        <div
          v-for="(article, idx) in recommendedArticles"
          :key="article.id"
          class="recommend-card"
          :class="{ 'recommend-featured': idx === 0 }"
          @click="openArticle(article.id)"
        >
          <div class="recommend-badge" v-if="idx === 0">精选推荐</div>
          <div class="recommend-header">
            <span class="recommend-tag" :style="{ background: article.tagBg, color: article.tagColor }">
              {{ article.category }}
            </span>
            <span class="recommend-time">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>
              </svg>
              {{ article.readTime }}
            </span>
          </div>
          <h4 class="recommend-title">{{ article.title }}</h4>
          <p class="recommend-desc">{{ article.description }}</p>
          <div class="recommend-action">
            <span>开始阅读</span>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M5 12h14M12 5l7 7-7 7"/>
            </svg>
          </div>
        </div>
      </div>
    </div>

    <!-- 快速入口 -->
    <div class="section quick-links">
      <div class="section-header">
        <h2 class="section-title">快速入口</h2>
      </div>
      <div class="links-grid">
        <div class="link-card" @click="openArticle('getting-started')">
          <div class="link-icon">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
            </svg>
          </div>
          <div class="link-body">
            <h4>快速入门</h4>
            <p>5 分钟上手指南</p>
          </div>
          <svg class="link-arrow" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 18l6-6-6-6"/>
          </svg>
        </div>
        <div class="link-card" @click="openArticle('general-questions')">
          <div class="link-icon">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3"/><circle cx="12" cy="17" r="0.5"/>
            </svg>
          </div>
          <div class="link-body">
            <h4>常见问题</h4>
            <p>遇到问题先看这里</p>
          </div>
          <svg class="link-arrow" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 18l6-6-6-6"/>
          </svg>
        </div>
        <div class="link-card" @click="openArticle('risk-warnings')">
          <div class="link-icon">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>
              <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
            </svg>
          </div>
          <div class="link-body">
            <h4>风险提示</h4>
            <p>使用前必读声明</p>
          </div>
          <svg class="link-arrow" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 18l6-6-6-6"/>
          </svg>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

interface Category {
  slug: string
  icon: string
  title: string
  description: string
  count: number
  color: string
}

const categories = ref<Category[]>([
  {
    slug: 'ai-basics',
    icon: '🤖',
    title: 'AI 基础知识',
    description: '了解大语言模型的核心概念与工作原理',
    count: 1,
    color: '#C5A55A'
  },
  {
    slug: 'prompt-engineering',
    icon: '✍️',
    title: '提示词工程',
    description: '掌握与 AI 高效沟通的技巧与方法',
    count: 2,
    color: '#7CB342'
  },
  {
    slug: 'model-selection',
    icon: '🎯',
    title: '模型选择指南',
    description: '对比主流大模型，找到最适合的分析引擎',
    count: 1,
    color: '#D4AF37'
  },
  {
    slug: 'analysis-principles',
    icon: '📊',
    title: 'AI 分析原理',
    description: '深入理解多智能体协作分析股票的机制',
    count: 1,
    color: '#5C9CE6'
  },
  {
    slug: 'risks-limitations',
    icon: '⚠️',
    title: '风险与局限性',
    description: '正确认识 AI 辅助分析的边界与风险',
    count: 1,
    color: '#E57373'
  },
  {
    slug: 'resources',
    icon: '📖',
    title: '源项目与论文',
    description: 'TradingAgents 学术论文与项目资源',
    count: 3,
    color: '#B76E79'
  },
  {
    slug: 'tutorials',
    icon: '🎓',
    title: '实战教程',
    description: '从零开始使用本平台进行分析',
    count: 2,
    color: '#9C6ADE'
  },
  {
    slug: 'faq',
    icon: '❓',
    title: '常见问题',
    description: '快速找到关于功能与使用的解答',
    count: 1,
    color: '#9E9688'
  }
])

interface RecommendedArticle {
  id: string
  category: string
  tagBg: string
  tagColor: string
  title: string
  description: string
  readTime: string
}

const recommendedArticles = ref<RecommendedArticle[]>([
  {
    id: 'what-is-llm',
    category: 'AI 基础',
    tagBg: 'rgba(197, 165, 90, 0.12)',
    tagColor: '#C5A55A',
    title: '什么是大语言模型（LLM）？',
    description: '从零开始了解大语言模型的定义、工作原理和在股票分析中的应用场景',
    readTime: '10 分钟'
  },
  {
    id: 'multi-agent-system',
    category: 'AI 分析',
    tagBg: 'rgba(92, 156, 230, 0.12)',
    tagColor: '#5C9CE6',
    title: '多智能体系统详解',
    description: '了解本平台如何通过多个 AI 智能体协作，完成深度股票分析',
    readTime: '15 分钟'
  },
  {
    id: 'best-practices',
    category: '提示词',
    tagBg: 'rgba(124, 179, 66, 0.12)',
    tagColor: '#7CB342',
    title: '提示词工程最佳实践',
    description: '学习编写高质量提示词的核心原则，提升 AI 分析效果',
    readTime: '12 分钟'
  }
])

const totalArticles = computed(() => categories.value.reduce((sum, c) => sum + c.count, 0))
const totalReadTime = computed(() => {
  const mins = [10, 10, 12, 15, 15, 12, 15, 20, 40, 10, 15, 15]
  return Math.round(mins.reduce((a, b) => a + b, 0) / 60 * 10) / 10 + 'h'
})

const navigateTo = (slug: string) => {
  router.push(`/learning/${slug}`)
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
.learning-center {
  min-height: 100vh;
}

/* ── Hero ── */
.hero {
  position: relative;
  overflow: hidden;
  padding: 64px 32px 56px;
  text-align: center;
  background: var(--gradient-gold);

  .hero-bg {
    position: absolute;
    inset: 0;
    pointer-events: none;
  }

  .hero-orb {
    position: absolute;
    border-radius: 50%;
    filter: blur(60px);
    opacity: 0.25;
  }
  .hero-orb-1 {
    width: 300px; height: 300px;
    background: #fff;
    top: -80px; left: 10%;
    animation: orbFloat 8s ease-in-out infinite;
  }
  .hero-orb-2 {
    width: 200px; height: 200px;
    background: #F7E7CE;
    bottom: -60px; right: 15%;
    animation: orbFloat 10s ease-in-out infinite reverse;
  }
  .hero-orb-3 {
    width: 150px; height: 150px;
    background: #fff;
    top: 20%; right: 30%;
    animation: orbFloat 12s ease-in-out infinite;
  }

  .hero-content {
    position: relative;
    z-index: 1;
    max-width: 700px;
    margin: 0 auto;
  }

  .hero-badge {
    display: inline-block;
    padding: 4px 16px;
    background: rgba(255, 255, 255, 0.2);
    border: 1px solid rgba(255, 255, 255, 0.3);
    border-radius: 20px;
    font-size: 13px;
    color: rgba(255, 255, 255, 0.9);
    letter-spacing: 1px;
    margin-bottom: 20px;
    backdrop-filter: blur(4px);
  }

  .hero-title {
    font-size: 42px;
    font-weight: 700;
    color: #fff;
    margin: 0 0 16px;
    letter-spacing: 2px;
  }

  .hero-desc {
    font-size: 17px;
    color: rgba(255, 255, 255, 0.88);
    line-height: 1.6;
    margin: 0 0 36px;
  }

  .hero-stats {
    display: inline-flex;
    align-items: center;
    gap: 24px;
    background: rgba(255, 255, 255, 0.15);
    backdrop-filter: blur(8px);
    border: 1px solid rgba(255, 255, 255, 0.2);
    border-radius: 16px;
    padding: 16px 36px;
  }

  .stat-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
  }
  .stat-num {
    font-size: 28px;
    font-weight: 700;
    color: #fff;
  }
  .stat-label {
    font-size: 13px;
    color: rgba(255, 255, 255, 0.8);
  }
  .stat-divider {
    width: 1px;
    height: 32px;
    background: rgba(255, 255, 255, 0.3);
  }
}

@keyframes orbFloat {
  0%, 100% { transform: translateY(0) scale(1); }
  50% { transform: translateY(-20px) scale(1.05); }
}

/* ── Section ── */
.section {
  max-width: 1200px;
  margin: 0 auto;
  padding: 48px 24px 0;

  .section-header {
    margin-bottom: 28px;
  }

  .section-title {
    font-size: 22px;
    font-weight: 700;
    color: var(--el-text-color-primary);
    margin: 0 0 6px;
  }

  .section-subtitle {
    font-size: 14px;
    color: var(--el-text-color-secondary);
    margin: 0;
  }
}

/* ── Pathway (Learning Path) ── */
.pathway {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.pathway-node {
  position: relative;
}

.pathway-connector {
  position: absolute;
  top: 50%;
  right: -10px;
  transform: translateY(-50%);
  z-index: 2;
  display: flex;
  align-items: center;
  color: var(--el-text-color-disabled);
  opacity: 0.5;
}

.pathway-card {
  position: relative;
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-light);
  border-radius: 14px;
  padding: 24px 20px;
  cursor: pointer;
  transition: all 0.3s ease;
  display: flex;
  flex-direction: column;
  gap: 12px;

  &:hover {
    transform: translateY(-4px);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08);
    border-color: var(--card-accent, var(--el-color-primary));

    .pathway-icon {
      transform: scale(1.1);
    }
  }

  .pathway-step {
    font-size: 11px;
    font-weight: 600;
    color: var(--el-text-color-secondary);
    text-transform: uppercase;
    letter-spacing: 1px;
  }

  .pathway-icon {
    font-size: 36px;
    transition: transform 0.3s ease;
  }

  .pathway-info {
    flex: 1;

    h3 {
      font-size: 16px;
      font-weight: 600;
      color: var(--el-text-color-primary);
      margin: 0 0 6px;
    }

    p {
      font-size: 13px;
      color: var(--el-text-color-secondary);
      line-height: 1.5;
      margin: 0;
    }
  }

  .pathway-meta {
    :deep(.el-tag) {
      font-size: 12px;
    }
  }
}

/* ── Recommended ── */
.recommended-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
}

.recommend-card {
  position: relative;
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-light);
  border-radius: 14px;
  padding: 24px;
  cursor: pointer;
  transition: all 0.3s ease;
  display: flex;
  flex-direction: column;
  gap: 14px;

  &:hover {
    transform: translateY(-4px);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08);

    .recommend-action {
      color: var(--el-color-primary);
      gap: 8px;
    }
  }

  &.recommend-featured {
    border-color: var(--el-color-primary-light-5);
    background: linear-gradient(
      135deg,
      var(--el-fill-color-blank) 0%,
      var(--el-color-primary-light-9) 100%
    );
  }

  .recommend-badge {
    position: absolute;
    top: -1px;
    right: 20px;
    background: var(--gradient-gold);
    color: #fff;
    font-size: 11px;
    font-weight: 600;
    padding: 4px 12px;
    border-radius: 0 0 8px 8px;
  }

  .recommend-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .recommend-tag {
    font-size: 12px;
    font-weight: 500;
    padding: 3px 10px;
    border-radius: 6px;
  }

  .recommend-time {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 13px;
    color: var(--el-text-color-secondary);
  }

  .recommend-title {
    font-size: 17px;
    font-weight: 600;
    color: var(--el-text-color-primary);
    margin: 0;
    line-height: 1.4;
  }

  .recommend-desc {
    font-size: 14px;
    color: var(--el-text-color-regular);
    line-height: 1.6;
    margin: 0;
    flex: 1;
  }

  .recommend-action {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 14px;
    font-weight: 500;
    color: var(--el-text-color-secondary);
    transition: all 0.3s ease;
  }
}

/* ── Quick Links ── */
.links-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.link-card {
  display: flex;
  align-items: center;
  gap: 16px;
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-light);
  border-radius: 12px;
  padding: 20px;
  cursor: pointer;
  transition: all 0.3s ease;

  &:hover {
    border-color: var(--el-color-primary-light-5);
    background: var(--el-color-primary-light-9);

    .link-arrow {
      color: var(--el-color-primary);
      transform: translateX(2px);
    }
  }

  .link-icon {
    width: 48px;
    height: 48px;
    border-radius: 12px;
    background: var(--el-color-primary-light-9);
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    color: var(--el-color-primary);
  }

  .link-body {
    flex: 1;

    h4 {
      font-size: 15px;
      font-weight: 600;
      color: var(--el-text-color-primary);
      margin: 0 0 2px;
    }

    p {
      font-size: 13px;
      color: var(--el-text-color-secondary);
      margin: 0;
    }
  }

  .link-arrow {
    color: var(--el-text-color-disabled);
    transition: all 0.3s ease;
    flex-shrink: 0;
  }
}

/* ── Dark Mode ── */
:global(html.dark) {
  .hero {
    background: linear-gradient(135deg, #1A1520 0%, #0C0A0F 100%);

    .hero-orb-1 { background: rgba(197, 165, 90, 0.15); }
    .hero-orb-2 { background: rgba(183, 110, 121, 0.1); }
    .hero-orb-3 { background: rgba(197, 165, 90, 0.08); }

    .hero-badge {
      background: rgba(197, 165, 90, 0.12);
      border-color: rgba(197, 165, 90, 0.25);
      color: var(--el-color-primary);
    }

    .hero-stats {
      background: rgba(197, 165, 90, 0.08);
      border-color: rgba(197, 165, 90, 0.15);
    }
  }

  .pathway-card:hover {
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
  }

  .recommend-card:hover {
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
  }

  .recommend-card.recommend-featured {
    background: linear-gradient(
      135deg,
      var(--el-fill-color-blank) 0%,
      rgba(197, 165, 90, 0.06) 100%
    );
  }

  .recommend-card .recommend-tag {
    background: rgba(197, 165, 90, 0.12) !important;
    color: var(--el-color-primary) !important;
  }

  .link-card .link-icon {
    background: rgba(197, 165, 90, 0.1);
  }
}

/* ── Responsive ── */
@media (max-width: 1200px) {
  .pathway {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 992px) {
  .pathway {
    grid-template-columns: repeat(2, 1fr);
  }
  .recommended-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .links-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .hero {
    padding: 40px 20px 36px;

    .hero-title { font-size: 30px; }
    .hero-desc { font-size: 15px; }
    .hero-stats { padding: 12px 20px; gap: 16px; }
    .stat-num { font-size: 22px; }
  }

  .section { padding: 32px 16px 0; }

  .pathway {
    grid-template-columns: 1fr;
  }

  .recommended-grid {
    grid-template-columns: 1fr;
  }

  .pathway-connector { display: none; }
}
</style>
