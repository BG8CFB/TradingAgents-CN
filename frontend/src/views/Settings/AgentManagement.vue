<template>
  <div class="agent-page">
    <!-- 顶栏 -->
    <div class="page-header">
      <div class="page-title">
        <h2 class="title">智能体配置</h2>
        <el-tag size="small" type="info" effect="plain">phase{{ activePhase }}</el-tag>
        <span v-if="phaseConfigPath" class="config-path" :title="phaseConfigPath">{{ phaseConfigPath }}</span>
      </div>
      <div class="page-actions">
        <el-select v-model="activePhase" size="small" style="width: 180px" @change="fetchPhaseConfig">
          <el-option :value="1" label="第一阶段 · 分析师" />
          <el-option :value="2" label="第二阶段 · 多空辩论" />
          <el-option :value="3" label="第三阶段 · 风险管理" />
        </el-select>
        <el-button size="small" :loading="phaseLoading" @click="fetchPhaseConfig">
          <el-icon><Refresh /></el-icon>&nbsp;刷新
        </el-button>
        <el-button v-if="activePhase === 1" size="small" type="primary" @click="addAgent">
          <el-icon><Plus /></el-icon>&nbsp;新增智能体
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="!phaseFileExists"
      type="warning"
      :closable="false"
      show-icon
      title="配置文件不存在"
      description="未找到对应 phase 的 YAML 文件，保存后将自动创建。"
      class="page-alert"
    />

    <!-- 主体：左列表 + 右编辑区 -->
    <el-container v-loading="phaseLoading" class="page-body">
      <el-aside width="280px" class="agent-aside">
        <el-card shadow="never" class="aside-card">
          <template #header>
            <div class="aside-head">
              <span>智能体列表</span>
              <span class="aside-count">{{ modes.length }}</span>
            </div>
          </template>
          <el-empty v-if="!modes.length" description="暂无智能体" :image-size="60" />
          <div
            v-for="mode in modes"
            :key="mode.uiKey"
            class="agent-item"
            :class="{ 'is-active': mode.uiKey === activeUiKey }"
            @click="activeUiKey = mode.uiKey"
          >
            <div class="agent-item__name">{{ mode.name || '未命名智能体' }}</div>
            <div class="agent-item__slug">{{ mode.slug || '未设置 slug' }}</div>
            <div v-if="activePhase === 1" class="agent-item__chips">
              <el-tag v-if="mode.data_tools?.length" size="small" effect="plain">
                数据 ×{{ mode.data_tools.length }}
              </el-tag>
              <el-tag v-if="mode.mcp_tools?.length" size="small" type="warning" effect="plain">
                MCP ×{{ mode.mcp_tools.length }}
              </el-tag>
              <el-tag v-if="mode.skills?.length" size="small" type="danger" effect="plain">
                Skill ×{{ mode.skills.length }}
              </el-tag>
            </div>
          </div>
        </el-card>
      </el-aside>

      <el-main class="agent-main">
        <el-empty v-if="!currentMode" description="请在左侧选择一个智能体" />
        <template v-else>
          <!-- 基本信息卡 -->
          <el-card shadow="never" class="edit-card">
            <template #header><span class="card-title">基本信息</span></template>
            <el-form label-width="90px" label-position="left">
              <el-row :gutter="16">
                <el-col :span="12">
                  <el-form-item label="slug" required>
                    <el-input v-model="currentMode.slug" placeholder="唯一标识，必填" :disabled="!currentMode.isNew" />
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item label="名称" required>
                    <el-input v-model="currentMode.name" placeholder="显示名称，必填" />
                  </el-form-item>
                </el-col>
              </el-row>
              <el-form-item label="描述">
                <el-input v-model="currentMode.description" placeholder="简要描述（可选），默认使用 slug" />
              </el-form-item>
            </el-form>
          </el-card>

          <!-- 工具配置卡（仅 phase1） -->
          <el-card v-if="activePhase === 1" shadow="never" class="edit-card">
            <template #header><span class="card-title">工具配置</span></template>

            <el-tabs v-model="activeToolTab">
              <el-tab-pane label="数据工具" name="datasource">
                <div class="tab-hint">
                  预注入数据源：分析师启动时由系统预取并注入上下文（AI 不可主动调用）。
                  不勾选 = 该智能体不注入任何数据。
                </div>
                <ToolSelector
                  v-model="currentMode.data_tools"
                  :tools="toolsByKind.datasource"
                  :loading="toolsLoading"
                  empty-text="暂无数据源"
                  empty-hint="未选择数据源"
                />
              </el-tab-pane>

              <el-tab-pane label="MCP" name="mcp">
                <div class="tab-hint">
                  未开启限制 = 默认全部可用（任务级启用 MCP 时）。
                </div>
                <el-switch
                  v-model="mcpRestricted"
                  active-text="限制为指定工具"
                  class="restrict-switch"
                />
                <ToolSelector
                  v-if="mcpRestricted"
                  v-model="currentMode.mcp_tools"
                  :tools="toolsByKind.mcp"
                  :loading="toolsLoading"
                  empty-text="暂无 MCP 工具（需先配置 MCP 服务器）"
                  empty-hint="未勾选 = 全部 MCP 工具"
                />
              </el-tab-pane>

              <el-tab-pane label="Skill" name="skill">
                <div class="tab-hint">
                  未开启限制 = 默认全部可用（渐进式披露）。
                </div>
                <el-switch
                  v-model="skillRestricted"
                  active-text="限制为指定技能"
                  class="restrict-switch"
                />
                <ToolSelector
                  v-if="skillRestricted"
                  v-model="currentMode.skills"
                  :tools="toolsByKind.skill"
                  :loading="toolsLoading"
                  empty-text="暂无已安装技能"
                  empty-hint="未勾选 = 全部技能"
                />
              </el-tab-pane>

              <el-tab-pane label="内置工具" name="builtin" disabled>
                <el-alert
                  type="info"
                  :closable="false"
                  title="内置计算工具（calc）默认对所有智能体启用，无需配置"
                  description="为保证数值准确性，衍生数值计算统一走确定性代码工具，后端不可关闭。"
                />
              </el-tab-pane>
            </el-tabs>
          </el-card>

          <!-- 系统提示词卡 -->
          <el-card shadow="never" class="edit-card">
            <template #header><span class="card-title">系统提示词（roleDefinition）</span></template>
            <el-input
              v-model="currentMode.roleDefinition"
              type="textarea"
              :rows="14"
              class="prompt-editor"
              placeholder="系统提示词，必填"
              maxlength="20000"
              show-word-limit
            />
          </el-card>

          <!-- 底部操作 -->
          <div class="edit-actions">
            <el-button type="danger" plain v-if="activePhase === 1" @click="removeAgent">删除智能体</el-button>
            <el-button type="primary" :loading="phaseSaving" @click="savePhaseConfig">保存配置</el-button>
          </div>
        </template>
      </el-main>
    </el-container>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Refresh, Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { agentConfigApi, type PhaseAgentMode } from '@/api/agentConfigs'
import { toolsApi } from '@/api/tools'
import type { UnifiedTool, ToolKind } from '@/types/tools'
import ToolSelector, { type ToolOption } from '@/components/Settings/ToolSelector.vue'

type UiPhaseAgentMode = PhaseAgentMode & {
  uiKey: string
  isNew?: boolean
  data_tools: string[]
  mcp_tools: string[]
  skills: string[]
}

const createUiKey = () => `agent-${Date.now()}-${Math.random().toString(16).slice(2)}`

// ── 阶段配置状态 ──
const activePhase = ref(1)
const modes = ref<UiPhaseAgentMode[]>([])
const phaseLoading = ref(false)
const phaseSaving = ref(false)
const phaseFileExists = ref(true)
const phaseConfigPath = ref('')
const activeUiKey = ref('')
const activeToolTab = ref('datasource')

// ── 工具清单 ──
const toolOptions = ref<ToolOption[]>([])
const toolsLoading = ref(false)

const toolsByKind = computed<Record<ToolKind, ToolOption[]>>(() => {
  const grouped: Record<ToolKind, ToolOption[]> = {
    datasource: [],
    builtin: [],
    skill: [],
    mcp: [],
  }
  for (const tool of toolOptions.value) {
    if (tool.kind) grouped[tool.kind].push(tool)
  }
  return grouped
})

const currentMode = computed(() => modes.value.find((m) => m.uiKey === activeUiKey.value) || null)

// 「限制」开关：字段为 null/undefined = 不限制（默认全部可用）
const mcpRestricted = computed({
  get: () => currentMode.value?.mcp_tools != null,
  set: (on: boolean) => {
    if (currentMode.value) currentMode.value.mcp_tools = on ? [...(currentMode.value.mcp_tools || [])] : null as unknown as string[]
  },
})
const skillRestricted = computed({
  get: () => currentMode.value?.skills != null,
  set: (on: boolean) => {
    if (currentMode.value) currentMode.value.skills = on ? [...(currentMode.value.skills || [])] : null as unknown as string[]
  },
})

const normalizeMode = (mode?: PhaseAgentMode, isNew = false): UiPhaseAgentMode => ({
  uiKey: (mode as UiPhaseAgentMode)?.uiKey || createUiKey(),
  slug: mode?.slug || '',
  name: mode?.name || '',
  roleDefinition: mode?.roleDefinition || '',
  description: mode?.description || '',
  data_tools: Array.isArray(mode?.data_tools) ? [...mode.data_tools!] : [],
  mcp_tools: Array.isArray(mode?.mcp_tools) ? [...mode.mcp_tools!] : null as unknown as string[],
  skills: Array.isArray(mode?.skills) ? [...mode.skills!] : null as unknown as string[],
  isNew,
})

const fetchToolOptions = async () => {
  toolsLoading.value = true
  try {
    const res = await toolsApi.listUnified(true, true)
    const list = (res.data as UnifiedTool[]) || []
    toolOptions.value = list.map((tool) => ({
      label: tool.display_name || tool.name,
      value: tool.name,
      description: tool.description || '',
      kind: tool.kind || tool.tool_type,
      availabilityStatus: tool.availability?.status,
    }))
  } catch (error) {
    console.error('加载工具列表失败', error)
    ElMessage.error('加载工具列表失败')
  } finally {
    toolsLoading.value = false
  }
}

const fetchPhaseConfig = async () => {
  phaseLoading.value = true
  try {
    const res = await agentConfigApi.getPhase(activePhase.value)
    const data = res.data
    phaseFileExists.value = data?.exists ?? false
    phaseConfigPath.value = data?.path || ''
    modes.value = (data?.customModes || []).map((item) => normalizeMode(item, false))
    activeUiKey.value = modes.value[0]?.uiKey || ''
    if (data && data.exists === false) {
      ElMessage.info(`phase${activePhase.value} 配置文件不存在，保存后将自动创建`)
    }
  } catch (error) {
    console.error('获取阶段配置失败', error)
    ElMessage.error('获取阶段配置失败')
  } finally {
    phaseLoading.value = false
  }
}

const addAgent = () => {
  const item = normalizeMode(undefined, true)
  modes.value.push(item)
  activeUiKey.value = item.uiKey
}

const removeAgent = async () => {
  const mode = currentMode.value
  if (!mode) return
  try {
    await ElMessageBox.confirm(
      `确定要删除智能体「${mode.name || mode.slug}」吗？此操作将立即保存配置。`,
      '删除确认',
      { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' },
    )
    const index = modes.value.findIndex((m) => m.uiKey === mode.uiKey)
    if (index >= 0) modes.value.splice(index, 1)
    activeUiKey.value = modes.value[0]?.uiKey || ''
    await savePhaseConfig()
  } catch (error) {
    if (error !== 'cancel') console.error(error)
  }
}

const validateModes = () => {
  const slugSet = new Set<string>()
  for (let i = 0; i < modes.value.length; i++) {
    const mode = modes.value[i]
    const slug = mode.slug?.trim()
    if (!slug) {
      ElMessage.error(`第 ${i + 1} 个智能体缺少 slug`)
      return false
    }
    if (slugSet.has(slug)) {
      ElMessage.error(`slug "${slug}" 重复，请保持唯一`)
      return false
    }
    slugSet.add(slug)
    if (!mode.name?.trim()) {
      ElMessage.error(`slug "${slug}" 缺少名称`)
      return false
    }
    if (!mode.roleDefinition?.trim()) {
      ElMessage.error(`slug "${slug}" 缺少 roleDefinition`)
      return false
    }
  }
  return true
}

const savePhaseConfig = async () => {
  if (!validateModes()) return
  phaseSaving.value = true
  try {
    const payload = {
      customModes: modes.value.map((mode) => {
        const item: PhaseAgentMode = {
          slug: mode.slug.trim(),
          name: mode.name.trim(),
          roleDefinition: mode.roleDefinition,
          description: mode.description || mode.slug,
        }
        if (activePhase.value === 1) {
          item.data_tools = mode.data_tools?.length ? Array.from(new Set(mode.data_tools)) : []
          // 空列表 / 未开启限制 = 默认全部可用，存 null
          if (mode.mcp_tools != null && mode.mcp_tools.length) {
            item.mcp_tools = Array.from(new Set(mode.mcp_tools))
          }
          if (mode.skills != null && mode.skills.length) {
            item.skills = Array.from(new Set(mode.skills))
          }
        }
        return item
      }),
    }
    await agentConfigApi.savePhase(activePhase.value, payload)
    ElMessage.success('阶段配置已保存')
    await fetchPhaseConfig()
  } catch (error) {
    console.error('保存阶段配置失败', error)
    ElMessage.error('保存阶段配置失败')
  } finally {
    phaseSaving.value = false
  }
}

// 阶段切换后重置 tab
watch(activePhase, () => {
  activeToolTab.value = 'datasource'
})

onMounted(() => {
  fetchToolOptions()
  fetchPhaseConfig()
})
</script>

<style lang="scss" scoped>
.agent-page {
  padding: 16px;
  height: 100%;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
}

/* ── 顶栏 ── */
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.page-title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.config-path {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.page-actions {
  display: flex;
  align-items: center;
  gap: 8px;

  .el-button {
    height: 32px;
    margin: 0;
  }
}

.page-alert {
  margin-top: 12px;
}

/* ── 主体 ── */
.page-body {
  flex: 1;
  min-height: 0;
  margin-top: 12px;
}

.agent-aside {
  min-height: 0;
  overflow-y: auto;
}

.aside-card {
  :deep(.el-card__header) {
    padding: 10px 12px;
  }

  :deep(.el-card__body) {
    padding: 6px;
  }
}

.aside-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  font-weight: 600;
}

.aside-count {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-weight: 400;
}

.agent-item {
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: background-color 0.15s ease;

  &:hover {
    background-color: var(--el-fill-color-light);
  }

  &.is-active {
    background-color: var(--el-color-primary-light-9);
  }
}

.agent-item__name {
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-item__slug {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-item__chips {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-top: 4px;
}

.agent-main {
  padding: 0 0 0 12px;
  min-height: 0;
  overflow-y: auto;
}

.edit-card {
  margin-bottom: 12px;

  :deep(.el-card__header) {
    padding: 10px 16px;
  }
}

.card-title {
  font-size: 13px;
  font-weight: 600;
}

.tab-hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-bottom: 8px;
}

.restrict-switch {
  margin-bottom: 8px;
}

.edit-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 4px 0 12px;
}

:deep(.prompt-editor .el-textarea__inner) {
  font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
  background-color: var(--el-fill-color-darker);
  line-height: 1.6;
}

@media (max-width: 768px) {
  .page-body {
    flex-direction: column;
  }

  .agent-aside {
    width: 100% !important;
    max-height: 240px;
  }

  .agent-main {
    padding-left: 0;
  }
}
</style>
