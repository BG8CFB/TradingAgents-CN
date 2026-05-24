<template>
  <el-menu
    :default-active="activeMenu"
    :collapse="appStore.sidebarCollapsed"
    :unique-opened="true"
    router
    class="sidebar-menu"
  >
    <!-- 工作台 -->
    <el-menu-item index="/dashboard">
      <el-icon><Odometer /></el-icon>
      <template #title>工作台</template>
    </el-menu-item>

    <!-- 行情中心 -->
    <el-sub-menu index="/market">
      <template #title>
        <el-icon><DataLine /></el-icon>
        <span>行情中心</span>
      </template>
      <el-menu-item index="/screening">股票筛选</el-menu-item>
      <el-menu-item index="/favorites">我的自选</el-menu-item>
    </el-sub-menu>

    <!-- 智能分析 -->
    <el-sub-menu index="/analysis">
      <template #title>
        <el-icon><TrendCharts /></el-icon>
        <span>智能分析</span>
      </template>
      <el-menu-item index="/analysis/single">单股分析</el-menu-item>
      <el-menu-item index="/analysis/batch">批量分析</el-menu-item>
      <el-menu-item index="/reports">分析报告</el-menu-item>
    </el-sub-menu>

    <!-- 任务中心 -->
    <el-menu-item index="/tasks">
      <el-icon><List /></el-icon>
      <template #title>任务中心</template>
    </el-menu-item>

    <!-- 学习中心 -->
    <el-menu-item index="/learning">
      <el-icon><Reading /></el-icon>
      <template #title>学习中心</template>
    </el-menu-item>

    <!-- 数据源管理 (移出3级菜单，作为顶级菜单) -->
    <el-menu-item index="/data">
      <el-icon><Coin /></el-icon>
      <template #title>数据源管理</template>
    </el-menu-item>

    <!-- 系统设置 -->
    <el-sub-menu index="/settings">
      <template #title>
        <el-icon><Setting /></el-icon>
        <span>系统设置</span>
      </template>

      <!-- 个人设置 -->
      <el-sub-menu index="/settings-personal">
        <template #title>个人设置</template>
        <el-menu-item index="/settings">通用设置</el-menu-item>
        <el-menu-item index="/settings?tab=appearance">外观设置</el-menu-item>
        <el-menu-item index="/settings?tab=analysis">分析偏好</el-menu-item>
        <el-menu-item index="/settings?tab=notifications">通知设置</el-menu-item>
        <el-menu-item index="/settings?tab=security">安全设置</el-menu-item>
      </el-sub-menu>

      <!-- 系统配置 -->
      <el-sub-menu index="/settings-config">
        <template #title>系统配置</template>
        <el-menu-item index="/settings/config">配置管理</el-menu-item>
        <el-menu-item index="/settings/mcp">MCP 管理</el-menu-item>
        <el-menu-item index="/settings/mcp-tools">MCP 工具</el-menu-item>
        <el-menu-item index="/settings/agents">智能体管理</el-menu-item>
        <el-menu-item index="/settings/cache">缓存管理</el-menu-item>
        <el-menu-item index="/settings/usage">使用统计</el-menu-item>
      </el-sub-menu>

      <!-- 系统运维 -->
      <el-sub-menu index="/settings-ops">
        <template #title>系统运维</template>
        <el-menu-item index="/settings/database">数据库管理</el-menu-item>
        <el-menu-item index="/settings/scheduler">定时任务</el-menu-item>
        <el-menu-item index="/settings/logs">操作日志</el-menu-item>
        <el-menu-item index="/settings/system-logs">系统日志</el-menu-item>
      </el-sub-menu>
    </el-sub-menu>

    <!-- 关于 -->
    <el-menu-item index="/about">
      <el-icon><InfoFilled /></el-icon>
      <template #title>关于</template>
    </el-menu-item>
  </el-menu>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'
import {
  Odometer,
  DataLine,
  TrendCharts,
  List,
  Reading,
  Setting,
  InfoFilled
} from '@element-plus/icons-vue'

const route = useRoute()
const appStore = useAppStore()

const activeMenu = computed(() => {
  const path = route.path
  const tab = route.query.tab as string | undefined
  return tab ? `${path}?tab=${tab}` : path
})
</script>

<style lang="scss" scoped>
.sidebar-menu {
  border: none;
  height: 100%;

  :deep(.el-menu-item),
  :deep(.el-sub-menu__title) {
    height: 48px;
    line-height: 48px;
  }

  :deep(.el-menu-item.is-active) {
    background-color: var(--el-color-primary-light-9);
    color: var(--el-color-primary);
    font-weight: 600;
  }
}
</style>
