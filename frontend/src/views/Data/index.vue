<template>
  <div class="data-center">
    <!-- 页面头部 -->
    <div class="hero-header">
      <div class="hero-bg"></div>
      <div class="hero-content">
        <div class="hero-info">
          <h1 class="hero-title">
            <span class="hero-icon-wrap">
              <el-icon :size="28"><Coin /></el-icon>
            </span>
            数据源管理
          </h1>
          <p class="hero-subtitle">全市场数据资产监控、同步调度与路由降级配置</p>
        </div>

        <!-- 市场切换器 -->
        <div class="market-switcher">
          <div
            v-for="m in markets"
            :key="m.code"
            class="market-chip"
            :class="{ active: activeMarket === m.code }"
            @click="activeMarket = m.code"
          >
            <span class="chip-flag">{{ m.flag }}</span>
            <span class="chip-label">{{ m.label }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 统计概览行 -->
    <div class="stats-row" v-if="summaryStats">
      <div class="stat-card">
        <div class="stat-icon healthy">
          <el-icon :size="20"><CircleCheck /></el-icon>
        </div>
        <div class="stat-body">
          <div class="stat-number">{{ summaryStats.healthySources }}</div>
          <div class="stat-desc">健康数据源</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon domains">
          <el-icon :size="20"><Grid /></el-icon>
        </div>
        <div class="stat-body">
          <div class="stat-number">{{ summaryStats.totalDomains }}</div>
          <div class="stat-desc">数据域</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon records">
          <el-icon :size="20"><DocumentCopy /></el-icon>
        </div>
        <div class="stat-body">
          <div class="stat-number">{{ formatNumber(summaryStats.totalRecords) }}</div>
          <div class="stat-desc">总记录数</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon sync">
          <el-icon :size="20"><Refresh /></el-icon>
        </div>
        <div class="stat-body">
          <div class="stat-number">{{ summaryStats.lastSync || '--' }}</div>
          <div class="stat-desc">最近同步</div>
        </div>
      </div>
    </div>

    <!-- 功能 Tab 导航 -->
    <div class="tab-nav-wrapper">
      <div class="tab-nav">
        <div
          v-for="tab in funcTabs"
          :key="tab.key"
          class="tab-item"
          :class="{ active: activeTab === tab.key }"
          @click="activeTab = tab.key"
        >
          <div class="tab-icon-wrap">
            <el-icon :size="18"><component :is="tab.icon" /></el-icon>
          </div>
          <span class="tab-label">{{ tab.label }}</span>
          <div v-if="activeTab === tab.key" class="tab-indicator"></div>
        </div>
      </div>
    </div>

    <!-- 内容区 -->
    <div class="tab-content">
      <transition name="fade-slide" mode="out-in">
        <DataOverview v-if="activeTab === 'overview'" :market="activeMarket" @stats-loaded="onStatsLoaded" />
        <SyncManager v-else-if="activeTab === 'sync'" :market="activeMarket" />
        <SourceConfig v-else-if="activeTab === 'source'" :market="activeMarket" />
      </transition>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, markRaw } from 'vue'
import { Coin, Monitor, Refresh, Connection, CircleCheck, Grid, DocumentCopy } from '@element-plus/icons-vue'
import DataOverview from '@/components/Data/DataOverview.vue'
import SyncManager from '@/components/Data/SyncManager.vue'
import SourceConfig from '@/components/Data/SourceConfig.vue'
import type { MarketCode } from '@/api/marketData'

interface SummaryStats {
  healthySources: number
  totalDomains: number
  totalRecords: number
  lastSync: string
}

const markets: Array<{ code: MarketCode; label: string; flag: string }> = [
  { code: 'cn', label: 'A股', flag: '🇨🇳' },
  { code: 'hk', label: '港股', flag: '🇭🇰' },
  { code: 'us', label: '美股', flag: '🇺🇸' },
]

const funcTabs = [
  { key: 'overview', label: '数据总览', icon: markRaw(Monitor) },
  { key: 'sync', label: '同步管理', icon: markRaw(Refresh) },
  { key: 'source', label: '路由与优先级', icon: markRaw(Connection) },
]

const activeMarket = ref<MarketCode>('cn')
const activeTab = ref('overview')
const summaryStats = ref<SummaryStats | null>(null)

function onStatsLoaded(stats: SummaryStats) {
  summaryStats.value = stats
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}
</script>

<style scoped lang="scss">
.data-center {
  min-height: 100%;
}

/* ── Hero Header ── */
.hero-header {
  position: relative;
  padding: 32px 36px 28px;
  border-radius: 20px;
  overflow: hidden;
  margin-bottom: 24px;
  box-shadow: 0 10px 30px rgba(45, 53, 97, 0.15);

  .hero-bg {
    position: absolute;
    inset: 0;
    background: linear-gradient(135deg, #0C0A0F 0%, #1A1520 50%, #2A2030 100%);
    z-index: 0;
  }

  .hero-content {
    position: relative;
    z-index: 1;
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 24px;
  }

  .hero-info {
    .hero-title {
      display: flex;
      align-items: center;
      gap: 14px;
      margin: 0 0 10px;
      font-size: 30px;
      font-weight: 700;
      color: #fff;
      letter-spacing: -0.5px;
    }

    .hero-icon-wrap {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 44px;
      height: 44px;
      border-radius: 12px;
      background: rgba(255, 255, 255, 0.15);
      backdrop-filter: blur(10px);
    }

    .hero-subtitle {
      margin: 0;
      font-size: 15px;
      color: rgba(255, 255, 255, 0.7);
    }
  }
}

/* ── 市场切换 ── */
.market-switcher {
  display: flex;
  gap: 8px;
  flex-shrink: 0;

  .market-chip {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 10px 20px;
    border-radius: 12px;
    border: 1.5px solid rgba(255, 255, 255, 0.2);
    background: rgba(255, 255, 255, 0.08);
    backdrop-filter: blur(10px);
    cursor: pointer;
    transition: all 0.3s ease;
    user-select: none;
    color: rgba(255, 255, 255, 0.8);
    font-weight: 500;
    font-size: 14px;

    .chip-flag { font-size: 18px; }

    &:hover {
      background: rgba(255, 255, 255, 0.16);
      border-color: rgba(255, 255, 255, 0.35);
    }

    &.active {
      background: rgba(255, 255, 255, 0.95);
      border-color: transparent;
      color: var(--el-text-color-primary);
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
      font-weight: 600;
    }
  }
}

/* ── 统计概览行 ── */
.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px 24px;
  background: var(--el-bg-color);
  border-radius: 16px;
  border: 1px solid var(--el-border-color-lighter);
  transition: all 0.3s ease;

  &:hover {
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.06);
    transform: translateY(-2px);
  }

  .stat-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 48px;
    height: 48px;
    border-radius: 14px;
    flex-shrink: 0;

    &.healthy { background: #e8f5e9; color: #7CB342; }
    &.domains { background: #e3f2fd; color: #C5A55A; }
    &.records { background: #fff3e0; color: #B76E79; }
    &.sync { background: #f3e5f5; color: #9E7E3E; }
  }

  .stat-body {
    .stat-number {
      font-size: 22px;
      font-weight: 700;
      color: var(--el-text-color-primary);
      line-height: 1.2;
    }
    .stat-desc {
      font-size: 13px;
      color: var(--el-text-color-secondary);
      margin-top: 2px;
    }
  }
}

/* ── Tab 导航 ── */
.tab-nav-wrapper {
  margin-bottom: 24px;
}

.tab-nav {
  display: flex;
  gap: 4px;
  padding: 6px;
  background: var(--el-fill-color-lighter);
  border-radius: 14px;
  border: 1px solid var(--el-border-color-lighter);
}

.tab-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 22px;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.25s ease;
  font-size: 14px;
  font-weight: 500;
  color: var(--el-text-color-regular);
  position: relative;
  user-select: none;

  .tab-icon-wrap {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border-radius: 8px;
    background: transparent;
    transition: all 0.25s ease;
  }

  &:hover {
    color: var(--el-color-primary);
    background: var(--el-color-primary-light-9);

    .tab-icon-wrap { background: var(--el-color-primary-light-8); }
  }

  &.active {
    color: var(--el-color-primary);
    background: var(--el-bg-color);
    font-weight: 600;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);

    .tab-icon-wrap {
      background: var(--el-color-primary-light-8);
      color: var(--el-color-primary);
    }
  }
}

/* ── 内容过渡动画 ── */
.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: all 0.25s ease;
}
.fade-slide-enter-from {
  opacity: 0;
  transform: translateY(8px);
}
.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

/* ── 响应式 ── */
@media (max-width: 900px) {
  .hero-header .hero-content {
    flex-direction: column;
    align-items: flex-start;
  }
  .stats-row {
    grid-template-columns: repeat(2, 1fr);
  }
  .tab-nav { overflow-x: auto; }
  .tab-item { white-space: nowrap; }
}
</style>
