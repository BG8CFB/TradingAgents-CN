<template>
  <div class="mcp-page">
    <div class="page-header">
      <div class="header-left">
        <h1 class="page-title">MCP</h1>
        <el-tooltip content="Model Context Protocol" placement="top">
          <el-icon class="help-icon"><QuestionFilled /></el-icon>
        </el-tooltip>
      </div>
      <div class="header-right">
        <el-button class="icon-btn" @click="refresh" :loading="mcpStore.loading">
          <el-icon><Refresh /></el-icon>
        </el-button>
        <el-dropdown trigger="click" @command="handleCommand">
          <el-button class="add-btn">
            <el-icon><Plus /></el-icon> 添加
            <el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="form">手动添加</el-dropdown-item>
              <el-dropdown-item command="import">JSON 导入（支持 Cline / Kilo / Claude Desktop）</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>

    <div class="server-list" v-loading="mcpStore.loading">
      <div
        v-for="server in mcpStore.connectors"
        :key="server.name"
        class="server-item"
        :class="{ expanded: expandedItems.includes(server.name) }"
      >
        <div class="server-header" @click="toggleExpand(server.name)">
          <div class="item-left">
            <el-icon class="expand-arrow"><ArrowRight /></el-icon>
            <div class="server-icon" :style="{ backgroundColor: getIconColor(server.name) }">
              {{ server.name.charAt(0).toUpperCase() }}
            </div>
            <span class="server-name">{{ server.name }}</span>
            <el-tag size="small" :type="getTypeTagType(server.type)" class="type-tag">
              {{ server.type || 'stdio' }}
            </el-tag>
            <el-icon class="status-check" :class="getStatusClass(server.status)">
              <component :is="getStatusIcon(server.status)" />
            </el-icon>
            <span class="status-text" :class="getStatusClass(server.status)">{{ getStatusText(server.status) }}</span>
          </div>
          <div class="item-right">
            <el-switch
              :model-value="server.enabled"
              @change="(val) => handleToggle(server.name, val as boolean)"
              @click.stop
              style="--el-switch-on-color: #10b981;"
            />
          </div>
        </div>

        <div v-show="expandedItems.includes(server.name)" class="server-details">
          <div class="details-content">
            <!-- 健康信息 -->
            <div v-if="server.healthInfo" class="health-info">
              <div class="health-item">
                <span class="health-label">状态:</span>
                <span :class="getStatusClass(server.healthInfo.status)">{{ server.healthInfo.status }}</span>
              </div>
              <div v-if="server.healthInfo.latencyMs" class="health-item">
                <span class="health-label">延迟:</span>
                <span>{{ server.healthInfo.latencyMs.toFixed(0) }}ms</span>
              </div>
              <div v-if="server.healthInfo.lastCheck" class="health-item">
                <span class="health-label">最后检查:</span>
                <span>{{ formatTime(server.healthInfo.lastCheck) }}</span>
              </div>
              <div v-if="server.healthInfo.error" class="health-item error">
                <span class="health-label">错误:</span>
                <span>{{ server.healthInfo.error }}</span>
              </div>
            </div>

            <!-- 配置摘要 -->
            <div class="config-summary">
              <div v-if="server.config?.description" class="summary-item">
                <span class="health-label">描述:</span>
                <span>{{ server.config.description }}</span>
              </div>
              <div v-if="server.config?.command" class="summary-item code">
                {{ server.config.command }} {{ (server.config.args || []).join(' ') }}
              </div>
              <div v-if="server.config?.url" class="summary-item code">{{ server.config.url }}</div>
              <div v-if="server.config?.deps?.length" class="summary-item">
                <span class="health-label">deps:</span>
                <el-tag v-for="d in server.config.deps" :key="d" size="small" class="dep-tag">{{ d }}</el-tag>
              </div>
            </div>

            <!-- 测试结果 -->
            <div v-if="testResults[server.name]" class="health-info" :class="getStatusClass(testResults[server.name])">
              <div class="health-item">
                <span class="health-label">连接测试:</span>
                <span :class="getStatusClass(testResults[server.name])">{{ getStatusText(testResults[server.name]) }}</span>
              </div>
            </div>

            <div class="actions-row">
              <el-button size="small" @click="handleEdit(server)" text bg>编辑</el-button>
              <el-button size="small" :loading="testingName === server.name" @click="handleTest(server.name)" text bg>测试连接</el-button>
              <el-button
                v-if="server.config?.deps?.length"
                size="small"
                :loading="installingDeps === server.name"
                @click="handleInstallDeps(server.name)"
                text bg
              >安装依赖</el-button>
              <el-button type="danger" size="small" text bg @click="handleDelete(server.name)">删除配置</el-button>
            </div>
          </div>
        </div>
      </div>

      <div v-if="mcpStore.connectors.length === 0 && !mcpStore.loading" class="empty-state-card">
        <el-icon class="empty-icon"><Tools /></el-icon>
        <p class="empty-text">暂无 MCP Servers</p>
        <div class="empty-actions">
          <el-button type="primary" bg text class="action-btn" @click="handleCommand('form')">手动添加</el-button>
        </div>
      </div>
    </div>

    <!-- 结构化表单（添加/编辑） -->
    <McpServerFormDialog
      v-model="formDialogVisible"
      :edit-name="editName"
      :edit-config="editConfig"
      @saved="mcpStore.fetchConnectors()"
    />

    <!-- JSON 导入 Dialog -->
    <el-dialog
      v-model="importDialogVisible"
      title="JSON 导入"
      width="640px"
      class="mcp-config-dialog"
      :close-on-click-modal="false"
      align-center
    >
      <div class="dialog-body">
        <p class="dialog-desc">
          粘贴 MCP 配置 JSON，自动识别格式（Claude Desktop / Cline / Kilo / 单服务器对象），兼容 NPX / UVX 配置。
        </p>

        <div class="editor-container">
          <el-input
            v-model="jsonConfig"
            type="textarea"
            :rows="10"
            placeholder='// 支持以下格式，直接粘贴即可：
{
  "mcpServers": {
    "example-server": {
      "command": "npx",
      "args": ["-y", "mcp-server-example"]
    }
  }
}'
            class="json-editor"
          />
        </div>

        <!-- 识别结果预览 -->
        <div v-if="insight" class="insight-panel">
          <div class="insight-header">
            识别格式：
            <el-tag size="small" type="info">{{ insight.format }}</el-tag>
            <span class="insight-count">{{ Object.keys(insight.servers).length }} 个服务器</span>
          </div>
          <div v-for="(cfg, name) in insight.servers" :key="name" class="insight-server">
            <el-tag size="small" :type="getTypeTagType(cfg.type || 'stdio')">{{ cfg.type || 'stdio' }}</el-tag>
            <span class="server-name">{{ name }}</span>
            <span class="insight-detail">{{ cfg.command || cfg.url }}</span>
          </div>
          <el-alert
            v-for="w in insight.warnings"
            :key="w"
            type="warning"
            :title="w"
            :closable="false"
            show-icon
            class="insight-alert"
          />
          <el-alert
            v-for="(err, name) in insight.errors"
            :key="name"
            type="error"
            :title="`${name}: ${err}`"
            :closable="false"
            show-icon
            class="insight-alert"
          />
        </div>

        <div class="dialog-warning">
          <el-icon><Warning /></el-icon> 配置前请确认来源，甄别风险
        </div>
      </div>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="importDialogVisible = false">取消</el-button>
          <el-button @click="analyze" :loading="analyzing">解析识别</el-button>
          <el-button
            type="primary"
            @click="confirmImport"
            :loading="mcpStore.saving"
            :disabled="!insight || Object.keys(insight.servers).length === 0"
          >确认导入</el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import {
  QuestionFilled,
  Refresh,
  Plus,
  ArrowDown,
  ArrowRight,
  Check,
  Warning,
  Tools,
  Close,
  QuestionFilled as Unknown
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useMCPStore } from '@/stores/mcp'
import McpServerFormDialog from './components/McpServerFormDialog.vue'
import type { ImportInsight, MCPServerConfig } from '@/types/mcp'

const mcpStore = useMCPStore()
const expandedItems = ref<string[]>([])

// 结构化表单
const formDialogVisible = ref(false)
const editName = ref<string | undefined>(undefined)
const editConfig = ref<MCPServerConfig | undefined>(undefined)

// JSON 导入
const importDialogVisible = ref(false)
const jsonConfig = ref('')
const analyzing = ref(false)
const insight = ref<ImportInsight | null>(null)

// 测试与依赖安装
const testingName = ref('')
const testResults = ref<Record<string, string>>({})
const installingDeps = ref('')

const refresh = () => {
  mcpStore.fetchConnectors()
}

const handleCommand = (command: string) => {
  if (command === 'form') {
    editName.value = undefined
    editConfig.value = undefined
    formDialogVisible.value = true
  } else if (command === 'import') {
    jsonConfig.value = ''
    insight.value = null
    importDialogVisible.value = true
  }
}

const handleEdit = (server: { name: string; config: MCPServerConfig }) => {
  editName.value = server.name
  editConfig.value = server.config
  formDialogVisible.value = true
}

const handleTest = async (name: string) => {
  testingName.value = name
  try {
    const status = await mcpStore.testConnector(name)
    if (status) {
      testResults.value[name] = status
    }
  } finally {
    testingName.value = ''
  }
}

const handleInstallDeps = async (name: string) => {
  installingDeps.value = name
  try {
    await mcpStore.installDeps(name)
  } finally {
    installingDeps.value = ''
  }
}

const toggleExpand = (name: string) => {
  const index = expandedItems.value.indexOf(name)
  if (index > -1) {
    expandedItems.value.splice(index, 1)
  } else {
    expandedItems.value.push(name)
  }
}

const getIconColor = (name: string) => {
  const colors = ['#3b82f6', '#eab308', '#a855f7', '#06b6d4', '#ec4899', '#f97316']
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash)
  }
  return colors[Math.abs(hash) % colors.length]
}

const getStatusClass = (status: string) => {
  switch (status) {
    case 'healthy': return 'success'
    case 'connected': return 'success'
    case 'degraded': return 'warning'
    case 'unreachable': return 'danger'
    case 'disconnected': return 'danger'
    case 'stopped': return 'info'
    default: return 'unknown'
  }
}

const getStatusIcon = (status: string) => {
  switch (status) {
    case 'healthy': return Check
    case 'connected': return Check
    case 'degraded': return Warning
    case 'unreachable': return Close
    case 'disconnected': return Close
    case 'stopped': return Close
    default: return Unknown
  }
}

const getStatusText = (status: string) => {
  switch (status) {
    case 'healthy': return '健康'
    case 'connected': return '已连接'
    case 'degraded': return '降级'
    case 'unreachable': return '不可达'
    case 'disconnected': return '连接失败'
    case 'stopped': return '已停止'
    case 'unknown': return '未知'
    default: return status
  }
}

const getTypeTagType = (type: string) => {
  switch (type) {
    case 'streamable-http': return 'success'
    case 'http': return 'warning'
    case 'sse': return 'warning'
    case 'stdio': return 'info'
    default: return 'info'
  }
}

const formatTime = (isoString: string) => {
  try {
    const date = new Date(isoString)
    return date.toLocaleTimeString()
  } catch {
    return isoString
  }
}

const handleToggle = (name: string, val: boolean) => {
  mcpStore.toggleConnector(name, val)
}

const analyze = async () => {
  if (!jsonConfig.value.trim()) {
    ElMessage.warning('请先粘贴配置 JSON')
    return
  }
  analyzing.value = true
  try {
    insight.value = await mcpStore.importRaw(jsonConfig.value)
  } finally {
    analyzing.value = false
  }
}

const confirmImport = async () => {
  if (!insight.value) return
  try {
    await mcpStore.batchUpdate({ mcpServers: insight.value.servers })
    importDialogVisible.value = false
    insight.value = null
    jsonConfig.value = ''
    ElMessage.success('导入成功')
  } catch (e: any) {
    const errorMsg = e?.response?.data?.detail || e?.message || '导入失败'
    ElMessage.error(`导入失败: ${errorMsg}`)
  }
}

const handleDelete = (name: string) => {
  ElMessageBox.confirm(`确定要删除 ${name} 吗？`, '警告', {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    type: 'warning',
  }).then(async () => {
    await mcpStore.deleteConnector(name)
  })
}

onMounted(() => {
  mcpStore.fetchConnectors()
})
</script>

<style lang="scss" scoped>
.mcp-page {
  padding: 20px;
  max-width: 800px;
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

.add-btn {
  background-color: #f3f4f6;
  border: none;
  color: #1f2937;
}

/* Dark mode adjustments for buttons if needed */
:deep(.dark) .add-btn {
  background-color: #374151;
  color: #e5e7eb;
}

.server-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.server-item {
  background-color: var(--el-bg-color-overlay);
  border: 1px solid var(--el-border-color-darker);
  border-radius: 8px;
  overflow: hidden;
  transition: all 0.2s;
}

.server-item:hover {
  border-color: var(--el-border-color-light);
}

.server-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  cursor: pointer;
  user-select: none;
}

.item-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.expand-arrow {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  transition: transform 0.2s;
}

.server-item.expanded .expand-arrow {
  transform: rotate(90deg);
}

.server-icon {
  width: 32px;
  height: 32px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  color: white;
  font-size: 16px;
}

.server-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--el-text-color-primary);
}

.status-check {
  font-size: 12px;
  margin-left: 4px;
}

.status-check.success {
  color: #10b981;
}

.status-check.warning {
  color: #eab308;
}

.status-check.danger {
  color: #ef4444;
}

.status-check.info {
  color: #6b7280;
}

.status-check.unknown {
  color: var(--el-text-color-placeholder);
}

.status-text {
  font-size: 12px;
  margin-left: 4px;
}

.status-text.success {
  color: #10b981;
}

.status-text.warning {
  color: #eab308;
}

.status-text.danger {
  color: #ef4444;
}

.status-text.info {
  color: #6b7280;
}

.type-tag {
  margin-left: 8px;
}

.health-info {
  background-color: var(--el-fill-color-light);
  padding: 12px;
  border-radius: 6px;
  margin-bottom: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}

.health-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}

.health-label {
  color: var(--el-text-color-secondary);
}

.health-item.error {
  color: #ef4444;
  width: 100%;
}

.config-summary {
  margin-bottom: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.summary-item {
  font-size: 13px;
  color: var(--el-text-color-regular);
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;

  &.code {
    font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
    font-size: 12px;
    background-color: var(--el-fill-color-light);
    padding: 6px 10px;
    border-radius: 4px;
    width: fit-content;
  }
}

.dep-tag {
  margin-right: 4px;
}

.server-details {
  border-top: 1px solid var(--el-border-color-darker);
  background-color: var(--el-fill-color-darker);
  padding: 16px;
}

.actions-row {
  display: flex;
  justify-content: flex-end;
  gap: 4px;
}

.empty-state-card {
  background-color: var(--el-bg-color-overlay);
  border: 1px solid var(--el-border-color-darker);
  border-radius: 8px;
  padding: 60px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
}

.empty-icon {
  font-size: 48px;
  color: var(--el-color-primary);
  margin-bottom: 16px;
}

.empty-text {
  color: var(--el-text-color-secondary);
  font-size: 14px;
  margin: 0 0 24px 0;
}

.empty-actions {
  display: flex;
  gap: 12px;
}

.action-btn {
  background-color: var(--el-fill-color-dark);
  border-color: var(--el-border-color-darker);
  color: var(--el-text-color-primary);
}

.action-btn:hover {
  background-color: var(--el-fill-color-light);
}

/* Dialog Styles */
.dialog-desc {
  margin-bottom: 16px;
  color: var(--el-text-color-regular);
  font-size: 14px;
  line-height: 1.5;
}

.editor-container {
  margin-bottom: 16px;
}

:deep(.json-editor .el-textarea__inner) {
  font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
  background-color: var(--el-fill-color-darker);
  color: var(--el-text-color-primary);
  line-height: 1.5;
}

/* 导入识别结果面板 */
.insight-panel {
  border: 1px solid var(--el-border-color-darker);
  border-radius: 6px;
  padding: 12px;
  margin-bottom: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.insight-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--el-text-color-primary);
}

.insight-count {
  color: var(--el-text-color-secondary);
}

.insight-server {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  padding: 4px 0;
}

.insight-detail {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
}

.insight-alert {
  :deep(.el-alert__title) {
    font-size: 12px;
  }
}

.dialog-warning {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #eab308;
  font-size: 12px;
}
</style>
