<template>
  <div class="basic-layout">
    <!-- 侧边栏 -->
    <aside
      class="sidebar"
      :class="{ collapsed: appStore.sidebarCollapsed }"
      :style="{ width: appStore.actualSidebarWidth + 'px' }"
    >
      <div class="sidebar-header">
        <div class="logo">
          <img src="/logo.svg" alt="TradingAgents-CN" />
          <span v-show="!appStore.sidebarCollapsed" class="logo-text">
            TradingAgents-CN
          </span>
        </div>
      </div>
      
      <nav class="sidebar-nav">
        <SidebarMenu />
      </nav>
      
      <div class="sidebar-footer">
        <UserProfile />
      </div>
    </aside>

    <!-- 点击蒙层：移动端展开时，点击空白处收起侧边栏 -->
    <div
      v-if="isMobile && !appStore.sidebarCollapsed"
      class="sidebar-overlay"
      @click="appStore.setSidebarCollapsed(true)"
    ></div>

    <!-- 主内容区 -->
    <div class="main-container" :style="{ marginLeft: appStore.actualSidebarWidth + 'px' }" @click="handleMainClick">
      <!-- 顶部导航栏 -->
      <header class="header">
        <div class="header-left">
          <el-button
            link
            @click.stop="appStore.toggleSidebar()"
            class="sidebar-toggle"
          >
            <el-icon><Expand v-if="appStore.sidebarCollapsed" /><Fold v-else /></el-icon>
          </el-button>
          
          <Breadcrumb />
        </div>
        
        <div class="header-right">
          <HeaderActions />
        </div>
      </header>

      <!-- 页面内容 -->
      <main class="main-content">
        <div class="content-wrapper">
          <!-- 不加内层 transition：App.vue 外层已有 out-in 过渡，双层动画会串联加倍耗时 -->
          <router-view v-slot="{ Component, route }">
            <keep-alive :include="keepAliveComponents">
              <component :is="Component" :key="route.fullPath" />
            </keep-alive>
          </router-view>
        </div>
      </main>

      <!-- 页脚 -->
      <footer class="footer">
        <AppFooter />
      </footer>
    </div>

    <!-- 回到顶部 -->
    <el-backtop :right="40" :bottom="isMobile ? 80 : 40" />

    <!-- 移动端底部导航 -->
    <MobileTabbar />
  </div>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useWindowSize } from '@vueuse/core'
import { useAppStore } from '@/stores/app'
import SidebarMenu from '@/components/Layout/SidebarMenu.vue'
import UserProfile from '@/components/Layout/UserProfile.vue'
import Breadcrumb from '@/components/Layout/Breadcrumb.vue'
import HeaderActions from '@/components/Layout/HeaderActions.vue'
import AppFooter from '@/components/Layout/AppFooter.vue'
import MobileTabbar from '@/components/Layout/MobileTabbar.vue'
import { Expand, Fold } from '@element-plus/icons-vue'

const appStore = useAppStore()
const route = useRoute()
const { width } = useWindowSize()

// 需要缓存的组件
const keepAliveComponents = computed(() => [
  'Dashboard',
  'StockScreening',
  'AiChat'
])

// 移动端判断
const isMobile = computed(() => width.value < 768)

// 点击主内容时，若移动端且侧边栏已展开，则收起
const handleMainClick = () => {
  if (isMobile.value && !appStore.sidebarCollapsed) {
    appStore.setSidebarCollapsed(true)
  }
}

// 监听窗口大小变化：在小屏幕上自动折叠侧边栏
// immediate：真机/小窗首次加载即处于移动宽度，无 resize 事件，需初始就折叠
watch(width, (newWidth) => {
  if (newWidth < 768 && !appStore.sidebarCollapsed) {
    appStore.setSidebarCollapsed(true)
  }
}, { immediate: true })

// 路由变化时，移动端收起侧边栏
watch(() => route.fullPath, () => {
  if (isMobile.value) {
    appStore.setSidebarCollapsed(true)
  }
})
</script>

<style lang="scss" scoped>
.basic-layout {
  min-height: 100vh;
  background-color: var(--el-bg-color-page);
}

.sidebar-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  z-index: 950; // 低于侧边栏(1000)，高于内容区
}

.sidebar {
  position: fixed;
  top: 0;
  left: 0;
  height: 100vh;
  background-color: var(--el-bg-color);
  border-right: 1px solid var(--el-border-color-light);
  transition: width 0.3s ease;
  z-index: 1000;
  display: flex;
  flex-direction: column;

  &.collapsed {
    width: 64px !important;
  }

  .sidebar-header {
    height: 60px;
    display: flex;
    align-items: center;
    padding: 0 16px;
    border-bottom: 1px solid var(--el-border-color-lighter);

    .logo {
      display: flex;
      align-items: center;
      gap: 12px;

      img {
        width: 32px;
        height: 32px;
      }

      .logo-text {
        font-size: 18px;
        font-weight: 600;
        color: var(--el-text-color-primary);
        white-space: nowrap;
      }
    }
  }

  .sidebar-nav {
    flex: 1;
    overflow-y: auto;
    padding: 8px 0;
  }

  .sidebar-footer {
    border-top: 1px solid var(--el-border-color-lighter);
    padding: 8px;
  }
}

.main-container {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  transition: margin-left 0.3s ease;
}

.header {
  height: 60px;
  background-color: var(--el-bg-color);
  border-bottom: 1px solid var(--el-border-color-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  position: sticky;
  top: 0;
  z-index: 999;

  .header-left {
    display: flex;
    align-items: center;
    gap: 16px;

    .sidebar-toggle {
      padding: 8px;
      
      .el-icon {
        font-size: 18px;
      }
    }
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: 16px;
  }
}

.main-content {
  flex: 1;
  padding: 24px 24px 0 24px;
  min-height: calc(100vh - 60px);

  .content-wrapper {
    max-width: 1400px;
    margin: 0 auto;
  }
}

.footer {
  height: 60px;
  background-color: transparent;
  display: flex;
  align-items: center;
  justify-content: center;
  border-top: 1px solid var(--el-border-color-light);
}

// 响应式设计
@media (max-width: 768px) {
  .sidebar {
    transform: translateX(-100%);

    &:not(.collapsed) {
      transform: translateX(0);
      // 抽屉模式展开为全宽菜单（collapsed 的 64px 仅图标态在移动端不可用）
      width: 240px !important;
    }
  }

  .main-container {
    margin-left: 0 !important;
  }

  .main-content {
    padding: 12px 12px calc(68px + env(safe-area-inset-bottom)) 12px;
  }

  .header {
    padding: 0 12px;

    .header-left {
      gap: 8px;
    }
  }

  // 底部导航存在时页脚收窄，避免双底栏叠占
  .footer {
    height: 48px;
  }
}
</style>
