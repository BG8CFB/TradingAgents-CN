<template>
  <div class="skills-page">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-left">
        <h1 class="page-title">技能（Skill）管理</h1>
        <el-tooltip
          content="Skill 是可分发的分析能力包，支持带脚本、依赖、资源的完整能力扩展。首次加载自动安装依赖。"
          placement="top"
        >
          <el-icon class="help-icon"><QuestionFilled /></el-icon>
        </el-tooltip>
      </div>
      <div class="header-right">
        <el-button @click="showGitInstall = true" type="primary" plain>
          <el-icon><Download /></el-icon>
          <span>从 Git 安装</span>
        </el-button>
        <el-button @click="handleReload" :loading="reloading">
          <el-icon><Refresh /></el-icon>
          <span>重新扫描</span>
        </el-button>
        <el-button class="icon-btn" @click="refresh" :loading="skillsStore.loading">
          <el-icon><Refresh /></el-icon>
        </el-button>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="stats-row">
      <el-card class="stat-card" shadow="never">
        <div class="stat-value">{{ skillsStore.total }}</div>
        <div class="stat-label">技能总数</div>
      </el-card>
      <el-card class="stat-card" shadow="never">
        <div class="stat-value success">{{ skillsStore.enabledCount }}</div>
        <div class="stat-label">已启用</div>
      </el-card>
      <el-card class="stat-card" shadow="never">
        <div class="stat-value warning">{{ skillsStore.scriptCount }}</div>
        <div class="stat-label">含脚本</div>
      </el-card>
      <el-card class="stat-card" shadow="never">
        <div class="stat-value" :class="{ danger: skillsStore.needsInstallCount > 0 }">
          {{ skillsStore.needsInstallCount }}
        </div>
        <div class="stat-label">待安装依赖</div>
      </el-card>
    </div>

    <!-- 全局配置提示 -->
    <el-alert
      v-if="skillsStore.config"
      :type="skillsStore.config.auto_install ? 'success' : 'warning'"
      :closable="false"
      class="config-alert"
    >
      <template #title>
        <div class="config-summary">
          <el-icon><Check v-if="skillsStore.config.auto_install" /><Warning v-else /></el-icon>
          <span>
            自动安装: {{ skillsStore.config.auto_install ? '已开启' : '已关闭' }}
            | 超时: {{ skillsStore.config.install_timeout }}s
            | 可信 Git 主机: {{ skillsStore.config.git_trusted_hosts.join(', ') || '无' }}
            | 白名单: {{ skillsStore.config.allowed_packages.length || '不限' }}
          </span>
        </div>
      </template>
    </el-alert>

    <!-- Skill 列表 -->
    <div class="skills-list" v-loading="skillsStore.loading">
      <el-card
        v-for="skill in skillsStore.skills"
        :key="skill.name"
        class="skill-card"
        shadow="hover"
      >
        <div class="skill-header">
          <div class="skill-title-group">
            <span class="skill-name">{{ skill.name }}</span>
            <el-tag size="small" :type="sourceTagType(skill.source_type)">
              {{ sourceLabel(skill.source_type) }}
            </el-tag>
            <el-tag v-if="skill.has_scripts" size="small" type="warning">含脚本</el-tag>
            <el-tag v-if="skill.version !== '0.0.0'" size="small" type="info">
              v{{ skill.version }}
            </el-tag>
          </div>
          <el-switch
            :model-value="skill.enabled"
            @change="(val) => handleToggle(skill.name, val as boolean)"
            style="--el-switch-on-color: #10b981;"
          />
        </div>

        <p class="skill-description">{{ skill.description }}</p>

        <div class="skill-meta">
          <el-tag v-if="skill.entrypoint_count > 0" size="small">
            {{ skill.entrypoint_count }} 个入口
          </el-tag>
          <el-tag
            v-if="skill.dependencies_total > 0"
            size="small"
            :type="skill.dependencies_satisfied ? 'success' : 'danger'"
          >
            依赖 {{ skill.dependencies_total - skill.dependencies_missing }}/{{ skill.dependencies_total }}
          </el-tag>
          <el-tag
            v-if="skill.dependencies_missing > 0"
            size="small"
            type="danger"
            effect="plain"
          >
            缺失 {{ skill.dependencies_missing }}
          </el-tag>
        </div>

        <div class="skill-actions">
          <el-button size="small" @click="handleViewDetail(skill.name)">查看详情</el-button>
          <el-button
            v-if="skill.dependencies_missing > 0"
            size="small"
            type="primary"
            @click="handleInstall(skill.name)"
            :loading="installingSkill === skill.name"
          >
            安装依赖
          </el-button>
          <el-button
            v-if="skill.source_type !== 'builtin'"
            size="small"
            type="danger"
            plain
            @click="handleUninstall(skill)"
          >
            卸载
          </el-button>
        </div>
      </el-card>

      <div v-if="skillsStore.skills.length === 0 && !skillsStore.loading" class="empty-state">
        <el-icon class="empty-icon"><Tools /></el-icon>
        <p class="empty-text">暂无技能，可从 Git 安装或手动放置到 config/skills/</p>
      </div>
    </div>

    <!-- 详情抽屉 -->
    <el-drawer
      v-model="detailDrawer"
      :title="currentDetail?.name || '技能详情'"
      direction="rtl"
      size="60%"
      @open="onDetailOpen"
    >
      <div v-if="currentDetail" class="detail-content">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="名称">{{ currentDetail.name }}</el-descriptions-item>
          <el-descriptions-item label="版本">v{{ currentDetail.version }}</el-descriptions-item>
          <el-descriptions-item label="来源">
            {{ sourceLabel(currentDetail.source_type) }}
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="currentDetail.enabled ? 'success' : 'info'">
              {{ currentDetail.enabled ? '启用' : '禁用' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="描述" :span="2">
            {{ currentDetail.description }}
          </el-descriptions-item>
          <el-descriptions-item label="路径" :span="2">
            <code class="path-code">{{ currentDetail.skill_dir }}</code>
          </el-descriptions-item>
        </el-descriptions>

        <h4 class="section-title">入口（Entrypoints）</h4>
        <el-table
          v-if="currentDetail.entrypoints.length > 0"
          :data="currentDetail.entrypoints"
          size="small"
          border
        >
          <el-table-column prop="name" label="名称" width="140" />
          <el-table-column prop="display_name" label="中文名" width="140" />
          <el-table-column prop="description" label="描述" show-overflow-tooltip />
          <el-table-column label="市场" width="160">
            <template #default="{ row }">
              <el-tag v-for="m in row.markets" :key="m" size="small" class="mr-1">{{ m }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
        <p v-else class="empty-hint">无入口（纯 prompt 技能）</p>

        <h4 class="section-title">依赖状态</h4>
        <el-table
          v-if="currentDetail.availability.dependencies.length > 0"
          :data="currentDetail.availability.dependencies"
          size="small"
          border
        >
          <el-table-column prop="package" label="包名" />
          <el-table-column prop="version_constraint" label="版本约束" width="160" />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="row.satisfied ? 'success' : 'danger'" size="small">
                {{ row.satisfied ? '已安装' : '缺失' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="installed_version" label="已装版本" width="120" />
          <el-table-column prop="note" label="备注" show-overflow-tooltip />
        </el-table>
        <p v-else class="empty-hint">无 Python 依赖</p>

        <div v-if="currentDetail.availability.warnings.length > 0" class="warnings-section">
          <el-alert type="warning" :closable="false">
            <ul class="warning-list">
              <li v-for="(w, idx) in currentDetail.availability.warnings" :key="idx">{{ w }}</li>
            </ul>
          </el-alert>
        </div>

        <h4 class="section-title">SKILL.md 预览</h4>
        <pre class="skillmd-preview">{{ currentDetail.content_preview }}</pre>
      </div>
    </el-drawer>

    <!-- Git 安装对话框 -->
    <el-dialog v-model="showGitInstall" title="从 Git URL 安装技能" width="500px">
      <el-form label-position="top">
        <el-form-item label="Git URL">
          <el-input
            v-model="gitUrl"
            placeholder="https://github.com/user/my-skill.git"
          />
        </el-form-item>
        <el-form-item label="临时可信主机（可选，与全局合并）">
          <el-input
            v-model="gitTrustedHosts"
            placeholder="github.com,gitee.com（逗号分隔）"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showGitInstall = false">取消</el-button>
        <el-button
          type="primary"
          @click="handleGitInstall"
          :loading="gitInstalling"
        >
          安装
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { QuestionFilled, Refresh, Download, Tools, Check, Warning } from '@element-plus/icons-vue'
import { useSkillsStore } from '@/stores/skills'
import type { SkillSummary } from '@/api/skills'

const skillsStore = useSkillsStore()

const detailDrawer = ref(false)
const currentDetail = ref<any>(null)
const installingSkill = ref('')
const reloading = ref(false)
const showGitInstall = ref(false)
const gitUrl = ref('')
const gitTrustedHosts = ref('')
const gitInstalling = ref(false)

const refresh = async () => {
  await Promise.all([skillsStore.fetchSkills(), skillsStore.fetchConfig()])
}

const handleToggle = async (name: string, enabled: boolean) => {
  await skillsStore.toggleSkill(name, enabled)
}

const handleInstall = async (name: string) => {
  installingSkill.value = name
  try {
    await skillsStore.installSkill(name)
  } finally {
    installingSkill.value = ''
  }
}

const handleViewDetail = async (name: string) => {
  const detail = await skillsStore.fetchDetail(name)
  if (detail) {
    currentDetail.value = detail
    detailDrawer.value = true
  }
}

const onDetailOpen = () => {
  // 预留：打开时可以预加载安装日志
}

const handleReload = async () => {
  reloading.value = true
  try {
    await skillsStore.reloadSkills()
  } finally {
    reloading.value = false
  }
}

const handleUninstall = async (skill: SkillSummary) => {
  const force = skill.source_type === 'local'
  const msg = force
    ? `这是本地技能，卸载将删除目录 ${skill.name}。确认继续？`
    : `确认卸载技能 ${skill.name}？`
  try {
    await ElMessageBox.confirm(msg, '卸载确认', { type: 'warning' })
    await skillsStore.uninstallSkill(skill.name, force)
  } catch {
    // 用户取消
  }
}

const handleGitInstall = async () => {
  if (!gitUrl.value) {
    ElMessage.warning('请输入 Git URL')
    return
  }
  gitInstalling.value = true
  try {
    const hosts = gitTrustedHosts.value
      .split(',')
      .map((h) => h.trim())
      .filter(Boolean)
    await skillsStore.installFromGit(gitUrl.value, hosts.length ? hosts : undefined)
    showGitInstall.value = false
    gitUrl.value = ''
    gitTrustedHosts.value = ''
  } catch {
    // 错误已在 store 中处理
  } finally {
    gitInstalling.value = false
  }
}

const sourceLabel = (type: string): string => {
  const map: Record<string, string> = {
    local: '本地',
    builtin: '内置',
    git: 'Git',
    registry: '注册表',
  }
  return map[type] || type
}

const sourceTagType = (type: string): 'primary' | 'success' | 'warning' | 'info' => {
  const map: Record<string, 'primary' | 'success' | 'warning' | 'info'> = {
    local: 'primary',
    builtin: 'info',
    git: 'warning',
    registry: 'success',
  }
  return map[type] || 'info'
}

onMounted(() => {
  refresh()
})
</script>

<style scoped>
.skills-page {
  padding: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.page-title {
  font-size: 22px;
  margin: 0;
}

.header-right {
  display: flex;
  gap: 8px;
}

.help-icon {
  font-size: 16px;
  color: var(--el-text-color-secondary);
  cursor: help;
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

.stat-card {
  text-align: center;
}

.stat-value {
  font-size: 28px;
  font-weight: 600;
  color: var(--el-color-primary);
}

.stat-value.success {
  color: var(--el-color-success);
}

.stat-value.warning {
  color: var(--el-color-warning);
}

.stat-value.danger {
  color: var(--el-color-danger);
}

.stat-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}

.config-alert {
  margin-bottom: 16px;
}

.config-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.skills-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
  gap: 16px;
}

.skill-card {
  display: flex;
  flex-direction: column;
}

.skill-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.skill-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.skill-name {
  font-weight: 600;
  font-size: 15px;
}

.skill-description {
  color: var(--el-text-color-regular);
  font-size: 13px;
  margin: 8px 0;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.skill-meta {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.skill-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: auto;
}

.empty-state {
  grid-column: 1 / -1;
  text-align: center;
  padding: 60px 20px;
  color: var(--el-text-color-secondary);
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 12px;
}

.empty-text {
  font-size: 14px;
}

.detail-content {
  padding: 0 8px;
}

.section-title {
  margin: 20px 0 12px;
  font-size: 14px;
  color: var(--el-text-color-primary);
}

.path-code {
  background: var(--el-fill-color-light);
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 12px;
  word-break: break-all;
}

.skillmd-preview {
  background: var(--el-fill-color-light);
  padding: 12px;
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.5;
  max-height: 300px;
  overflow: auto;
  white-space: pre-wrap;
}

.empty-hint {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  text-align: center;
  padding: 20px;
}

.warnings-section {
  margin-top: 12px;
}

.warning-list {
  margin: 0;
  padding-left: 20px;
  font-size: 13px;
}

.mr-1 {
  margin-right: 4px;
}
</style>
