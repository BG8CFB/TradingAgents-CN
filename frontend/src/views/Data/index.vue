<template>
  <div class="data-center">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-info">
        <h1 class="page-title">
          <el-icon class="title-icon"><Coin /></el-icon>
          数据中心
        </h1>
        <p class="page-description">统一管理多市场数据源同步、数据质量与数据查看</p>
      </div>
    </div>

    <!-- 市场切换 -->
    <div class="market-switcher">
      <div
        v-for="m in markets"
        :key="m.code"
        class="market-tab"
        :class="{ active: activeMarket === m.code }"
        @click="activeMarket = m.code"
      >
        <span class="market-flag">{{ m.flag }}</span>
        <span class="market-name">{{ m.label }}</span>
      </div>
    </div>

    <!-- 功能 Tab -->
    <div class="content-area">
      <div class="func-tabs">
        <div
          v-for="tab in funcTabs"
          :key="tab.key"
          class="func-tab"
          :class="{ active: activeTab === tab.key }"
          @click="activeTab = tab.key"
        >
          <el-icon><component :is="tab.icon" /></el-icon>
          <span>{{ tab.label }}</span>
        </div>
      </div>

      <div class="func-content">
        <MarketDashboard v-if="activeTab === 'dashboard'" :market="activeMarket" />
        <MarketSyncManagement v-else-if="activeTab === 'sync'" :market="activeMarket" />
        <MarketSourceConfig v-else-if="activeTab === 'source'" :market="activeMarket" />
        <MarketStockViewer v-else-if="activeTab === 'viewer'" :market="activeMarket" />
        <MarketDataQuality v-else-if="activeTab === 'quality'" :market="activeMarket" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, markRaw } from 'vue'
import { Coin, Monitor, Refresh, Connection, Search, DataAnalysis } from '@element-plus/icons-vue'
import MarketDashboard from '@/components/Data/MarketDashboard.vue'
import MarketSyncManagement from '@/components/Data/MarketSyncManagement.vue'
import MarketSourceConfig from '@/components/Data/MarketSourceConfig.vue'
import MarketStockViewer from '@/components/Data/MarketStockViewer.vue'
import MarketDataQuality from '@/components/Data/MarketDataQuality.vue'
import type { MarketCode } from '@/api/marketData'

const markets: Array<{ code: MarketCode; label: string; flag: string }> = [
  { code: 'cn', label: 'A股', flag: '🇨🇳' },
  { code: 'hk', label: '港股', flag: '🇭🇰' },
  { code: 'us', label: '美股', flag: '🇺🇸' },
]

const funcTabs = [
  { key: 'dashboard', label: '总览看板', icon: markRaw(Monitor) },
  { key: 'sync', label: '同步管理', icon: markRaw(Refresh) },
  { key: 'source', label: '数据源配置', icon: markRaw(Connection) },
  { key: 'viewer', label: '股票数据', icon: markRaw(Search) },
  { key: 'quality', label: '数据质量', icon: markRaw(DataAnalysis) },
]

const activeMarket = ref<MarketCode>('cn')
const activeTab = ref('dashboard')
</script>

<style scoped lang="scss">
.data-center {
  .page-header {
    margin-bottom: 24px;
    padding: 28px 32px;
    background: linear-gradient(135deg, var(--el-color-primary-light-9) 0%, var(--el-color-primary-light-7) 100%);
    border-radius: 16px;

    .header-info {
      .page-title {
        display: flex;
        align-items: center;
        margin: 0 0 8px;
        font-size: 28px;
        font-weight: 700;
        color: var(--el-text-color-primary);

        .title-icon {
          margin-right: 12px;
          font-size: 28px;
          color: var(--el-color-primary);
        }
      }

      .page-description {
        margin: 0;
        font-size: 15px;
        color: var(--el-text-color-secondary);
      }
    }
  }

  /* ── 市场切换 ── */
  .market-switcher {
    display: flex;
    gap: 8px;
    margin-bottom: 20px;

    .market-tab {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 12px 28px;
      border-radius: 12px;
      border: 2px solid var(--el-border-color-lighter);
      background: var(--el-bg-color);
      cursor: pointer;
      transition: all 0.25s ease;
      font-size: 15px;
      font-weight: 500;
      user-select: none;

      .market-flag { font-size: 20px; }

      &:hover {
        border-color: var(--el-color-primary-light-5);
        background: var(--el-color-primary-light-9);
      }

      &.active {
        border-color: var(--el-color-primary);
        background: var(--el-color-primary);
        color: #fff;
        box-shadow: 0 4px 12px rgba(var(--el-color-primary-rgb), 0.35);
      }
    }
  }

  /* ── 功能 Tab + 内容 ── */
  .content-area {
    background: var(--el-bg-color);
    border-radius: 16px;
    border: 1px solid var(--el-border-color-lighter);
    overflow: hidden;

    .func-tabs {
      display: flex;
      border-bottom: 1px solid var(--el-border-color-lighter);
      background: var(--el-fill-color-lighter);

      .func-tab {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 14px 24px;
        font-size: 14px;
        font-weight: 500;
        color: var(--el-text-color-regular);
        cursor: pointer;
        transition: all 0.2s ease;
        border-bottom: 2px solid transparent;
        user-select: none;

        &:hover {
          color: var(--el-color-primary);
          background: var(--el-color-primary-light-9);
        }

        &.active {
          color: var(--el-color-primary);
          border-bottom-color: var(--el-color-primary);
          background: var(--el-bg-color);
          font-weight: 600;
        }
      }
    }

    .func-content {
      padding: 24px;
      min-height: 400px;
    }
  }
}
</style>
