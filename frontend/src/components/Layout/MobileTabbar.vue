<template>
  <nav v-if="isMobile" class="mobile-tabbar" aria-label="底部导航">
    <button
      v-for="item in primaryItems"
      :key="item.path"
      class="tabbar-item"
      :class="{ active: isActive(item) }"
      :aria-current="isActive(item) ? 'page' : undefined"
      @click="router.push(item.path)"
    >
      <span class="tabbar-icon">
        <el-icon :size="22"><component :is="item.icon" /></el-icon>
      </span>
      <span class="tabbar-label">{{ item.label }}</span>
    </button>

    <!-- 更多：全量菜单 -->
    <button class="tabbar-item" :class="{ active: moreActive }" @click="moreVisible = true">
      <span class="tabbar-icon"><el-icon :size="22"><Menu /></el-icon></span>
      <span class="tabbar-label">更多</span>
    </button>

    <el-drawer
      v-model="moreVisible"
      direction="btt"
      size="62vh"
      :with-header="false"
      class="mobile-menu-drawer"
    >
      <div class="menu-grid">
        <button
          v-for="item in moreItems"
          :key="item.path"
          class="menu-cell"
          :class="{ active: route.fullPath === item.path }"
          @click="go(item.path)"
        >
          <el-icon :size="20"><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </button>
      </div>
    </el-drawer>
  </nav>
</template>

<script setup lang="ts">
/**
 * 移动端底部导航栏
 *
 * 设计依据（行业标准）：
 * - Material Design 3 Bottom navigation：3-5 个一级目的地、thumb zone（底部易触及）
 * - impeccable adapt.md：Bottom navigation instead of top/side navigation
 * - Apple HIG Tab Bar：当前项高亮、图标+文字组合、44pt+ 触控目标
 *
 * 只在视口宽小于 768px 渲染；目的地为侧栏一级菜单的高频子集（工作台/筛选/分析/AI/更多），
 * 「更多」弹出全量菜单抽屉（对应侧栏完整结构）。
 */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useWindowSize } from '@vueuse/core'
import {
  Odometer, DataLine, TrendCharts, List, Trophy, Menu, Star, ChatDotRound,
  Coin, Reading, Setting, InfoFilled, Collection
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const { width } = useWindowSize()

const isMobile = computed(() => width.value < 768)
const moreVisible = ref(false)

/** 底部固定 4 个高频目的地 + 更多 */
const primaryItems = [
  { path: '/dashboard', label: '工作台', icon: Odometer },
  { path: '/screening', label: '筛选', icon: DataLine },
  { path: '/analysis/single', label: '分析', icon: TrendCharts },
  { path: '/ai-chat', label: 'AI 助手', icon: ChatDotRound }
]

/** 「更多」抽屉里的全量入口（与侧栏信息架构一致） */
const moreItems = [
  { path: '/tasks', label: '任务中心', icon: List },
  { path: '/settlement', label: '结算记分卡', icon: Trophy },
  { path: '/favorites', label: '我的自选', icon: Star },
  { path: '/reports', label: '分析报告', icon: TrendCharts },
  { path: '/data', label: '数据中心', icon: Coin },
  { path: '/learning', label: '学习中心', icon: Reading },
  { path: '/knowledge', label: '知识库', icon: Collection },
  { path: '/settings', label: '系统设置', icon: Setting },
  { path: '/about', label: '关于', icon: InfoFilled }
]

function isActive(item: { path: string }): boolean {
  if (item.path === '/dashboard') return route.path === '/dashboard'
  return route.fullPath === item.path || route.path === item.path
}

const moreActive = computed(() =>
  moreItems.some((i) => isActive(i))
)

function go(path: string) {
  moreVisible.value = false
  router.push(path)
}

// 路由切换时关闭抽屉，避免返回后抽屉残留
watch(() => route.fullPath, () => { moreVisible.value = false })
</script>

<style lang="scss" scoped>
.mobile-tabbar {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 1001;
  display: flex;
  background: var(--el-bg-color);
  border-top: 1px solid var(--el-border-color-light);
  padding-bottom: env(safe-area-inset-bottom);
}

.tabbar-item {
  flex: 1;
  min-height: 56px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  border: none;
  background: none;
  color: var(--el-text-color-secondary);
  font-size: 11px;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;

  &.active {
    color: var(--el-color-primary);

    .tabbar-label {
      font-weight: 600;
    }
  }

  &:active {
    background: var(--el-fill-color-light);
  }
}

.tabbar-icon {
  line-height: 1;
}

.tabbar-label {
  line-height: 1.2;
}
</style>

<style lang="scss">
/* 底部菜单抽屉（全局样式：teleport 到 body） */
.mobile-menu-drawer {
  .el-drawer__body {
    padding: 16px;
    padding-bottom: calc(16px + env(safe-area-inset-bottom));
  }

  .menu-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 10px;
  }

  .menu-cell {
    min-height: 72px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    border: none;
    border-radius: 12px;
    background: var(--el-fill-color-light);
    color: var(--el-text-color-primary);
    font-size: 12px;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;

    &.active {
      background: var(--el-color-primary-light-9);
      color: var(--el-color-primary);
      font-weight: 600;
    }

    &:active {
      background: var(--el-fill-color);
    }
  }
}
</style>
