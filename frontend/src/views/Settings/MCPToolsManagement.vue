<template>
  <div class="mcp-tools-page">
    <div class="page-header">
      <div class="header-left">
        <h1 class="page-title">MCP 工具</h1>
        <el-tooltip content="管理本地 MCP 金融数据工具" placement="top">
          <el-icon class="help-icon"><QuestionFilled /></el-icon>
        </el-tooltip>
      </div>
      <div class="header-right">
        <el-button class="icon-btn" @click="refresh" :loading="toolsStore.loading">
          <el-icon><Refresh /></el-icon>
        </el-button>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="stats-row" v-if="toolsStore.summary">
      <el-card class="stat-card" shadow="never">
        <div class="stat-value">{{ toolsStore.summary.total }}</div>
        <div class="stat-label">总工具数</div>
      </el-card>
      <el-card class="stat-card" shadow="never">
        <div class="stat-value success">{{ toolsStore.summary.available }}</div>
        <div class="stat-label">可用</div>
      </el-card>
      <el-card class="stat-card" shadow="never">
        <div class="stat-value warning">{{ toolsStore.summary.unavailable }}</div>
        <div class="stat-label">不可用</div>
      </el-card>
      <el-card class="stat-card" shadow="never">
        <div class="stat-value">{{ toolsStore.summary.enabled }}</div>
        <div class="stat-label">已启用</div>
      </el-card>
    </div>

    <!-- Tushare 状态提示 -->
    <el-alert
      v-if="toolsStore.summary"
      :type="toolsStore.summary.tushare_available ? 'success' : 'warning'"
      :closable="false"
      class="tushare-alert"
    >
      <template #title>
        <div class="tushare-status">
          <el-icon v-if="toolsStore.summary.tushare_available"><Check /></el-icon>
          <el-icon v-else><Warning /></el-icon>
          <span>Tushare 数据源: {{ toolsStore.summary.tushare_available ? '可用' : '不可用' }}</span>
        </div>
      </template>
      <template v-if="!toolsStore.summary.tushare_available">
        <p>部分工具需要 Tushare 数据源支持，当前这些工具不可用</p>
      </template>
    </el-alert>

    <!-- 工具列表 -->
    <div class="tools-list" v-loading="toolsStore.loading">
      <div
        v-for="(tools, category) in toolsStore.toolsByCategory"
        :key="category"
        class="category-section"
      >
        <div class="category-header" @click="toggleCategory(category as string)">
          <el-icon class="expand-icon" :class="{ expanded: expandedCategories.includes(category as string) }">
            <ArrowRight />
          </el-icon>
          <span class="category-name">{{ category }}</span>
          <el-tag size="small" type="info">{{ tools.length }}个工具</el-tag>
        </div>

        <div v-show="expandedCategories.includes(category as string)" class="category-tools">
          <div
            v-for="tool in tools"
            :key="tool.name"
            class="tool-item"
            :class="{ disabled: !tool.available }"
          >
            <div class="tool-info">
              <div class="tool-name">{{ tool.name }}</div>
              <div class="tool-description">{{ tool.description || '暂无描述' }}</div>
              <div class="tool-meta">
                <el-tag
                  v-if="tool.tushare_only"
                  size="small"
                  type="warning"
                  class="source-tag"
                >
                  仅 Tushare
                </el-tag>
                <el-tag
                  v-if="!tool.available"
                  size="small"
                  type="danger"
                  class="availability-tag"
                >
                  数据源不可用
                </el-tag>
              </div>
            </div>
            <div class="tool-actions">
              <el-switch
                :model-value="tool.enabled"
                @change="(val) => handleToggle(tool.name, val as boolean)"
                :disabled="!tool.available"
                style="--el-switch-on-color: #10b981;"
              />
            </div>
          </div>
        </div>
      </div>

      <div v-if="toolsStore.tools.length === 0 && !toolsStore.loading" class="empty-state">
        <el-icon class="empty-icon"><Tools /></el-icon>
        <p class="empty-text">暂无 MCP 工具</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { QuestionFilled, Refresh, ArrowRight, Tools, Check, Warning } from '@element-plus/icons-vue'
import { useToolsStore } from '@/stores/tools'

const toolsStore = useToolsStore()
const expandedCategories = ref<string[]>(['核心数据', '宏观资金'])

const toggleCategory = (category: string) => {
  const index = expandedCategories.value.indexOf(category)
  if (index > -1) {
    expandedCategories.value.splice(index, 1)
  } else {
    expandedCategories.value.push(category)
  }
}

const handleToggle = (name: string, val: boolean) => {
  toolsStore.toggleTool(name, val)
}

const refresh = () => {
  toolsStore.fetchTools()
  toolsStore.fetchSummary()
}

onMounted(() => {
  refresh()
})
</script>

<style scoped>
.mcp-tools-page {
  padding: 20px;
  max-width: 900px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.page-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin: 0;
}

.help-icon {
  color: var(--el-text-color-secondary);
  font-size: 16px;
  cursor: pointer;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.icon-btn {
  background: transparent;
  border: 1px solid var(--el-border-color);
  color: var(--el-text-color-regular);
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}

.stat-card {
  text-align: center;
  padding: 16px;
}

.stat-value {
  font-size: 28px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin-bottom: 4px;
}

.stat-value.success {
  color: #10b981;
}

.stat-value.warning {
  color: #f59e0b;
}

.stat-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.tushare-alert {
  margin-bottom: 16px;
}

.tushare-status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
}

.category-section {
  background-color: var(--el-bg-color-overlay);
  border: 1px solid var(--el-border-color-darker);
  border-radius: 8px;
  margin-bottom: 12px;
  overflow: hidden;
}

.category-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  cursor: pointer;
  user-select: none;
  background-color: var(--el-fill-color-darker);
}

.expand-icon {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  transition: transform 0.2s;
}

.expand-icon.expanded {
  transform: rotate(90deg);
}

.category-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--el-text-color-primary);
  flex: 1;
}

.category-tools {
  border-top: 1px solid var(--el-border-color-darker);
}

.tool-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.tool-item:last-child {
  border-bottom: none;
}

.tool-item.disabled {
  background-color: var(--el-fill-color-light);
  opacity: 0.7;
}

.tool-info {
  flex: 1;
}

.tool-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--el-text-color-primary);
  margin-bottom: 4px;
  font-family: monospace;
}

.tool-description {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 8px;
}

.tool-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.source-tag {
  text-transform: uppercase;
}

.availability-tag {
  margin-left: auto;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  background-color: var(--el-bg-color-overlay);
  border: 1px solid var(--el-border-color-darker);
  border-radius: 8px;
}

.empty-icon {
  font-size: 48px;
  color: var(--el-text-color-placeholder);
  margin-bottom: 16px;
}

.empty-text {
  color: var(--el-text-color-secondary);
  font-size: 14px;
}
</style>
