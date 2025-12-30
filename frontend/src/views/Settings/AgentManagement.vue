<template>
  <div class="agent-page">
    <el-card class="phase-card" shadow="never">
      <template #header>
        <div class="phase-header">
          <div class="phase-title-group">
            <h2 class="phase-title">阶段智能体配置（YAML）</h2>
            <el-tag size="small" type="info" effect="plain">phase{{ activePhase }}</el-tag>
            <span v-if="phaseConfigPath" class="phase-path">{{ phaseConfigPath }}</span>
          </div>
          <div class="phase-actions">
            <el-select v-model="activePhase" size="small" style="width: 200px" @change="fetchPhaseConfig">
              <el-option :value="1" label="第一阶段 (phase1)" />
              <el-option :value="2" label="第二阶段 (phase2)" />
              <el-option :value="3" label="第三阶段 (phase3)" />
              <el-option :value="4" label="第四阶段 (phase4)" />
            </el-select>
            <el-button size="small" @click="fetchPhaseConfig" :loading="phaseLoading">
              <el-icon><Refresh /></el-icon>刷新
            </el-button>
            <el-button size="small" type="primary" @click="addPhaseAgent" v-if="activePhase === 1">
              <el-icon><Plus /></el-icon>新增智能体
            </el-button>
          </div>
        </div>
      </template>

      <el-alert
        v-if="!phaseFileExists"
        type="warning"
        :closable="false"
        title="配置文件不存在"
        description="未找到对应 phase 的 YAML 文件，保存后将自动创建；如不需要可忽略。"
        style="margin-bottom: 12px;"
      />
      <el-alert
        v-else
        type="info"
        :closable="false"
        title="说明"
        description="slug / name / roleDefinition 为必填；未选择工具默认启用全部；slug 需唯一。"
        style="margin-bottom: 12px;"
      />

      <el-skeleton v-if="phaseLoading" animated :rows="6" />
      <div v-else>
        <el-empty v-if="!phaseModes.length" description="暂无智能体，点击新增智能体" />
        <el-collapse v-else v-model="openedPanels">
          <el-collapse-item
            v-for="(mode, index) in phaseModes"
            :key="mode.uiKey"
            :name="mode.uiKey"
          >
            <template #title>
              <div class="collapse-title">
                <strong>{{ mode.name || '未命名智能体' }}</strong>
                <span class="collapse-sub">{{ mode.slug || '未设置 slug' }}</span>
              </div>
            </template>
            <el-form label-width="110px" class="mode-form">
              <el-row :gutter="16">
                <el-col :span="12">
                  <el-form-item label="slug" required>
                    <el-input v-model="mode.slug" placeholder="唯一标识，必填" :disabled="!mode.isNew" />
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item label="名称" required>
                    <el-input v-model="mode.name" placeholder="显示名称，必填" :disabled="!mode.isNew" />
                  </el-form-item>
                </el-col>
              </el-row>

              <el-form-item label="描述">
                <el-input v-model="mode.description" placeholder="简要描述（可选），默认使用 slug" />
              </el-form-item>

              <el-form-item label="工具权限" v-if="activePhase === 1">
                <div class="tool-inline">
                  <div class="tool-selector__header">
                    <el-input
                      v-model="toolSearch"
                      size="small"
                      clearable
                      placeholder="搜索工具名称或描述"
                    >
                      <template #prefix>
                        <el-icon><Search /></el-icon>
                      </template>
                    </el-input>
                    <el-radio-group v-model="toolSourceFilter" size="small">
                      <el-radio-button label="all">全部</el-radio-button>
                      <el-radio-button label="project">Project</el-radio-button>
                      <el-radio-button label="mcp">MCP</el-radio-button>
                    </el-radio-group>
                    <div class="tool-selector__summary">
                      <span>已选 {{ mode.tools?.length || 0 }} / {{ toolOptions.length }}</span>
                      <el-link type="primary" :underline="false" @click="mode.tools = []">清空</el-link>
                    </div>
                  </div>

                  <div class="tool-selector__body">
                    <div class="tool-selector__list">
                      <el-scrollbar height="260px">
                        <el-empty v-if="!filteredTools.length && !toolsLoading" description="暂无工具" />
                        <div
                          v-for="tool in filteredTools"
                          :key="tool.value"
                          class="tool-item"
                          @click="mode.tools = mode.tools?.includes(tool.value) ? mode.tools.filter((t) => t !== tool.value) : [...(mode.tools || []), tool.value]"
                        >
                          <div class="tool-item__head">
                            <el-checkbox
                              :model-value="mode.tools?.includes(tool.value)"
                              @change.stop=""
                            />
                            <div class="tool-item__title">
                              <span class="tool-item__name">{{ tool.value }}</span>
                              <el-tag size="small" type="info" v-if="tool.source">{{ tool.source }}</el-tag>
                            </div>
                          </div>
                          <el-tooltip
                            v-if="tool.description"
                            effect="light"
                            popper-class="tool-desc-tooltip"
                            placement="top-start"
                          >
                            <template #content>
                              <div class="tooltip-multiline">{{ tool.description }}</div>
                            </template>
                            <div class="tool-item__desc">{{ tool.description }}</div>
                          </el-tooltip>
                          <div v-else class="tool-item__desc muted">暂无描述</div>
                        </div>
                      </el-scrollbar>
                    </div>

                    <div class="tool-selector__selected">
                      <div class="tool-selector__selected-head">
                        <span>已选 {{ mode.tools?.length || 0 }}</span>
                        <el-link type="primary" :underline="false" @click="mode.tools = []">清空</el-link>
                      </div>
                      <el-scrollbar height="260px">
                        <div v-if="!mode.tools?.length" class="muted">留空=全工具</div>
                        <div
                          v-for="tool in mode.tools || []"
                          :key="tool"
                          class="tool-selected-item"
                        >
                          <div class="tool-selected-item__title">
                            <span>{{ resolveToolLabel(tool) }}</span>
                            <el-tag
                              size="small"
                              type="info"
                              v-if="toolOptions.find((o) => o.value === tool)?.source"
                            >
                              {{ toolOptions.find((o) => o.value === tool)?.source }}
                            </el-tag>
                          </div>
                          <div class="tool-selected-item__desc">
                              <el-tooltip
                                v-if="toolOptions.find((o) => o.value === tool)?.description"
                                effect="light"
                                popper-class="tool-desc-tooltip"
                                placement="top-start"
                              >
                                <template #content>
                                  <div class="tooltip-multiline">
                                    {{ toolOptions.find((o) => o.value === tool)?.description }}
                                  </div>
                                </template>
                                <div>
                                  {{ toolOptions.find((o) => o.value === tool)?.description || '无描述' }}
                                </div>
                              </el-tooltip>
                              <div v-else>
                                {{ toolOptions.find((o) => o.value === tool)?.description || '无描述' }}
                              </div>
                          </div>
                          <el-link type="danger" :underline="false" @click="removeTool(mode, tool)">移除</el-link>
                        </div>
                      </el-scrollbar>
                    </div>
                  </div>
                  <div class="form-hint">不选择即为默认全工具；选择后仅启用指定工具。</div>
                </div>
              </el-form-item>

              <el-form-item label="roleDefinition" required>
                <el-input
                  v-model="mode.roleDefinition"
                  type="textarea"
                  :rows="12"
                  class="prompt-editor"
                  placeholder="系统提示词，必填"
                  maxlength="20000"
                  show-word-limit
                />
              </el-form-item>

              <!-- 初始任务描述（仅1阶段显示） -->
              <el-form-item v-if="activePhase === 1" label="初始任务描述">
                <el-input
                  v-model="mode.initial_task"
                  type="textarea"
                  :rows="3"
                  placeholder="请输入初始任务描述，例如：请测试所有可用工具的功能"
                />
                <div class="form-hint">
                  <p>💡 说明：系统会自动在后面拼接股票代码、公司名称、交易日期等信息</p>
                  <p>示例：如果配置为"请测试所有可用工具的功能"，实际发送的消息将是：</p>
                  <p class="example">"请测试所有可用工具的功能。股票代码：600519，公司名称：贵州茅台，交易日期：2025-01-01"</p>
                  <p>留空则使用默认值："请对股票进行分析"</p>
                </div>
              </el-form-item>

              <div class="mode-actions">
                <el-button type="primary" text @click.stop="savePhaseConfig" :loading="phaseSaving">保存</el-button>
                <el-button type="danger" text @click.stop="removePhaseAgent(index)" v-if="activePhase === 1">删除</el-button>
              </div>
            </el-form>
          </el-collapse-item>
        </el-collapse>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Refresh, Plus, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { agentConfigApi, type PhaseAgentMode } from '@/api/agentConfigs'
import { toolsApi, type AvailableTool } from '@/api/tools'
import { mcpApi, type MCPTool } from '@/api/mcp'

type UiPhaseAgentMode = PhaseAgentMode & { uiKey: string; tools: string[]; isNew?: boolean }
type ToolOption = { label: string; value: string; description?: string; source?: string }

const createUiKey = () => `agent-${Date.now()}-${Math.random().toString(16).slice(2)}`

// 阶段 YAML 配置
const activePhase = ref(1)
const phaseModes = ref<UiPhaseAgentMode[]>([])
const phaseLoading = ref(false)
const phaseSaving = ref(false)
const phaseFileExists = ref(true)
const phaseConfigPath = ref('')
const openedPanels = ref<string[]>([])

// 工具列表
const toolOptions = ref<ToolOption[]>([])
const toolsLoading = ref(false)
const toolSearch = ref('')
const toolSourceFilter = ref<'all' | 'project' | 'mcp'>('all')

const normalizeMode = (mode?: PhaseAgentMode, isNew = false): UiPhaseAgentMode => ({
  uiKey: (mode as UiPhaseAgentMode)?.uiKey || createUiKey(),
  slug: mode?.slug || '',
  name: mode?.name || '',
  roleDefinition: mode?.roleDefinition || '',
  description: mode?.description || '',
  whenToUse: mode?.whenToUse || '',
  groups: Array.isArray(mode?.groups) ? [...mode.groups] : [],
  source: mode?.source || '',
  tools: Array.isArray(mode?.tools) ? [...mode.tools] : [],
  initial_task: mode?.initial_task || '',
  isNew
})

const fetchToolOptions = async () => {
  toolsLoading.value = true
  const dedup = new Set<string>()
  const options: ToolOption[] = []

  const pushOption = (name?: string | null, source?: string, description?: string) => {
    if (!name) return
    if (dedup.has(name)) return
    dedup.add(name)
    const label = source ? `${name}（${source}）` : name
    options.push({ label, value: name, description: description || '', source })
  }

  try {
    // 1) 统一工具清单（含项目工具）
    const res = await toolsApi.list(true)
    const list = (res.data as AvailableTool[]) || []
    list.forEach((tool) => pushOption(tool.name, tool.source, tool.description))

    // 2) 兜底：如果统一清单为空，再尝试 MCP 列表
    if (!options.length) {
      const mcpRes = await mcpApi.listTools()
      const mcpList = (mcpRes.data as MCPTool[]) || []
      mcpList.forEach((tool) => pushOption(tool.name || tool.id, tool.serverName, tool.description))
    }

    toolOptions.value = options
    if (!options.length) {
      ElMessage.warning('未获取到可用工具，请检查配置或 MCP 连接')
    }
  } catch (error) {
    console.error('加载工具列表失败', error)
    ElMessage.error('加载工具列表失败')
  } finally {
    toolsLoading.value = false
  }
}

const resolveToolLabel = (value?: string) => {
  if (!value) return ''
  const option = toolOptions.value.find((o) => o.value === value)
  return option?.label || value
}

const removeTool = (mode: UiPhaseAgentMode, tool: string) => {
  mode.tools = (mode.tools || []).filter((t) => t !== tool)
}

const filterToolOption = (query: string, option?: ToolOption) => {
  const q = (query || '').trim().toLowerCase()
  if (!q) return true
  if (!option) return true
  return (
    option.label.toLowerCase().includes(q) ||
    (option.description ? option.description.toLowerCase().includes(q) : false)
  )
}

const toolFilterMethod = (query: string, option: any) => {
  // option is el-option instance; we store raw option data on props
  const opt = option?.raw as ToolOption | undefined
  return filterToolOption(query, opt)
}

const filteredTools = computed(() => {
  const source = toolSourceFilter.value
  return toolOptions.value.filter((t) => {
    if (source !== 'all') {
      const s = (t.source || '').toLowerCase()
      if (source === 'project' && s === 'mcp') return false
      if (source === 'mcp' && s !== 'mcp') return false
    }
    return filterToolOption(toolSearch.value, t)
  })
})

const fetchPhaseConfig = async () => {
  phaseLoading.value = true
  try {
    const res = await agentConfigApi.getPhase(activePhase.value)
    const data = res.data
    phaseFileExists.value = data?.exists ?? false
    phaseConfigPath.value = data?.path || ''
    phaseModes.value = (data?.customModes || []).map((item) => normalizeMode(item, false))
    openedPanels.value = [] // 默认收起
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

const addPhaseAgent = () => {
  const item = normalizeMode(undefined, true)
  phaseModes.value.push(item)
  openedPanels.value = [item.uiKey]
}

const removePhaseAgent = async (index: number) => {
  try {
    await ElMessageBox.confirm('确定要删除该智能体吗？此操作将立即保存配置。', '删除确认', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })
    phaseModes.value.splice(index, 1)
    await savePhaseConfig()
  } catch (error) {
    if (error !== 'cancel') {
      console.error(error)
    }
  }
}

const validatePhaseModes = () => {
  const slugSet = new Set<string>()
  for (let i = 0; i < phaseModes.value.length; i++) {
    const mode = phaseModes.value[i]
    const slug = mode.slug?.trim()
    const name = mode.name?.trim()
    const prompt = mode.roleDefinition?.trim()

    if (!slug) {
      ElMessage.error(`第 ${i + 1} 个智能体缺少 slug`)
      return false
    }
    if (slugSet.has(slug)) {
      ElMessage.error(`slug "${slug}" 重复，请保持唯一`)
      return false
    }
    slugSet.add(slug)
    if (!name) {
      ElMessage.error(`slug "${slug}" 缺少名称`)
      return false
    }
    if (!prompt) {
      ElMessage.error(`slug "${slug}" 缺少 roleDefinition`)
      return false
    }
  }
  return true
}

const savePhaseConfig = async () => {
  if (!validatePhaseModes()) return
  phaseSaving.value = true
  try {
    const payload = {
      customModes: phaseModes.value.map((mode) => ({
        slug: mode.slug.trim(),
        name: mode.name.trim(),
        roleDefinition: mode.roleDefinition,
        description: mode.description || mode.slug,
        whenToUse: mode.whenToUse,
        groups: mode.groups,
        source: mode.source,
        tools: mode.tools && mode.tools.length ? Array.from(new Set(mode.tools)) : undefined,
        initial_task: mode.initial_task?.trim() || undefined
      }))
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

onMounted(() => {
  fetchToolOptions()
  fetchPhaseConfig()
})
</script>

<style scoped>
.agent-page {
  padding: 20px;
  max-width: 1200px;
  margin: 0 auto;
}

.phase-card {
  margin-bottom: 20px;
}

.phase-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.phase-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.phase-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.phase-path {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.phase-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.collapse-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.collapse-sub {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.mode-form {
  padding: 4px 0 8px;
}

.mode-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.form-hint {
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.tool-inline {
  padding: 10px;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  background: var(--el-fill-color-blank);
  box-shadow: var(--el-box-shadow-lighter);
}

.tool-selector {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.tool-selector__header {
  display: grid;
  grid-template-columns: 2fr auto auto;
  gap: 8px;
  align-items: center;
}

.tool-selector__summary {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  color: var(--el-text-color-secondary);
}

.tool-selector__body {
  display: grid;
  grid-template-columns: 1.3fr 1fr;
  gap: 12px;
}

.tool-selector__list,
.tool-selector__selected {
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  padding: 8px;
  background: var(--el-fill-color-blank);
  min-height: 280px;
}

.tool-item {
  padding: 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.tool-item:hover {
  background-color: var(--el-fill-color-light);
}

.tool-item__head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.tool-item__title {
  display: flex;
  align-items: center;
  gap: 6px;
}

.tool-item__name {
  font-weight: 600;
}

.tool-item__desc {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.muted {
  color: var(--el-text-color-secondary);
}

.tool-selector__selected-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.tool-selected-item {
  padding: 8px;
  border-radius: 6px;
  transition: background-color 0.1s ease;
}

.tool-selected-item:not(:last-child) {
  border-bottom: 1px solid var(--el-border-color-light);
}

.tool-selected-item__title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}

.tool-selected-item__desc {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin: 4px 0;
  line-height: 1.4;
}

.tool-desc-tooltip {
  max-width: 420px;
  white-space: pre-wrap;
  word-break: break-word;
}

.tooltip-multiline {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
  max-width: 420px;
}

:deep(.prompt-editor .el-textarea__inner) {
  font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
  background-color: var(--el-fill-color-darker);
  line-height: 1.6;
}

.example {
  background: var(--el-fill-color-light);
  padding: 8px 12px;
  border-radius: 4px;
  font-family: monospace;
  margin: 4px 0;
}
</style>
