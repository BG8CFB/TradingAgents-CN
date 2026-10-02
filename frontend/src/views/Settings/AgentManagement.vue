<template>
  <div class="agent-page">
    <!-- 顶栏 -->
    <div class="page-header">
      <div class="page-title">
        <h2 class="title">智能体管理</h2>
        <span class="subtitle">提示词与工具契约库；执行属性（类型/记忆槽）在工作流编辑器维护</span>
      </div>
      <div class="page-actions">
        <el-select v-model="filterPhase" size="small" style="width: 200px" @change="fetchList">
          <el-option :value="0" label="全部阶段" />
          <el-option :value="1" label="第一阶段 · 分析师" />
          <el-option :value="2" label="第二阶段 · 多空辩论" />
          <el-option :value="3" label="第三阶段 · 风险管理" />
        </el-select>
        <el-button size="small" :loading="loading" @click="fetchList">
          <el-icon><Refresh /></el-icon>&nbsp;刷新
        </el-button>
        <el-button size="small" type="primary" @click="addAgent">
          <el-icon><Plus /></el-icon>&nbsp;新增智能体
        </el-button>
      </div>
    </div>

    <!-- 主体：左列表 + 右编辑区 -->
    <el-container v-loading="loading" class="page-body">
      <el-aside width="280px" class="agent-aside">
        <el-card shadow="never" class="aside-card">
          <template #header>
            <div class="aside-head">
              <span>智能体库</span>
              <span class="aside-count">{{ visibleItems.length }}</span>
            </div>
          </template>
          <el-empty v-if="!visibleItems.length && !editForm?.isNew" description="暂无智能体" :image-size="60" />
          <div
            v-for="item in visibleItems"
            :key="item.slug"
            class="agent-item"
            :class="{ 'is-active': item.slug === activeSlug }"
            @click="selectAgent(item.slug)"
          >
            <div class="agent-item__name">{{ item.spec.name || item.slug }}</div>
            <div class="agent-item__slug">{{ item.slug }}</div>
            <div class="agent-item__chips">
              <el-tag v-if="item.builtin" size="small" type="info" effect="plain">内置</el-tag>
              <el-tag v-if="item.referenced_by?.length" size="small" effect="plain" title="被工作流引用">
                引用 ×{{ item.referenced_by.length }}
              </el-tag>
              <el-tag v-if="item.spec.default_selected" size="small" type="success" effect="plain">
                默认选中
              </el-tag>
              <el-tag v-if="item.spec.data_tools?.length" size="small" effect="plain">
                数据 ×{{ item.spec.data_tools.length }}
              </el-tag>
              <el-tag v-if="item.spec.mcp_tools?.length" size="small" type="warning" effect="plain">
                MCP ×{{ item.spec.mcp_tools.length }}
              </el-tag>
              <el-tag v-if="item.spec.skills?.length" size="small" type="danger" effect="plain">
                Skill ×{{ item.spec.skills.length }}
              </el-tag>
            </div>
          </div>
          <!-- 新建中的条目（尚未落库） -->
          <div v-if="editForm?.isNew" class="agent-item is-active is-new">
            <div class="agent-item__name">{{ editForm.name || '未命名智能体' }}</div>
            <div class="agent-item__slug">{{ editForm.slug || '未设置 slug（新建）' }}</div>
          </div>
        </el-card>
      </el-aside>

      <el-main class="agent-main">
        <el-empty v-if="!editForm" description="请在左侧选择一个智能体" />
        <template v-else>
          <!-- 内置只读横幅 -->
          <el-alert
            v-if="editForm.builtin"
            type="info"
            :closable="false"
            show-icon
            class="page-alert"
            title="内置智能体（只读）— 复制（fork）为自定义副本后可编辑提示词与工具"
          />

          <!-- 基本信息 -->
          <el-card shadow="never" class="edit-card">
            <template #header>
              <div class="card-head-row">
                <span class="card-title">基本信息</span>
                <el-tag v-if="editForm.referenced_by?.length" size="small" effect="plain">
                  被 {{ editForm.referenced_by.length }} 个工作流引用
                </el-tag>
              </div>
            </template>
            <el-form label-width="90px" label-position="left" :disabled="readonly">
              <el-row :gutter="16">
                <el-col :span="8">
                  <el-form-item label="slug" required>
                    <el-input v-model="editForm.slug" placeholder="唯一标识" :disabled="!editForm.isNew" />
                  </el-form-item>
                </el-col>
                <el-col :span="8">
                  <el-form-item label="名称" required>
                    <el-input v-model="editForm.name" placeholder="显示名称" @input="markDirty" />
                  </el-form-item>
                </el-col>
                <el-col :span="8">
                  <el-form-item label="阶段" required>
                    <el-select v-model="editForm.phase" :disabled="!editForm.isNew" @change="markDirty">
                      <el-option :value="1" label="第一阶段 · 分析师" />
                      <el-option :value="2" label="第二阶段 · 多空辩论" />
                      <el-option :value="3" label="第三阶段 · 风险管理" />
                    </el-select>
                  </el-form-item>
                </el-col>
              </el-row>
              <el-form-item label="描述">
                <el-input v-model="editForm.description" placeholder="简要描述（可选）" @input="markDirty" />
              </el-form-item>
              <el-form-item v-if="editForm.phase === 1" label="默认选中">
                <el-switch v-model="editForm.default_selected" active-text="发起分析时默认勾选" @change="markDirty" />
              </el-form-item>
            </el-form>
            <div v-if="editForm.referenced_by?.length" class="ref-list">
              引用它的自定义工作流：{{ editForm.referenced_by.join('、') }}
            </div>
          </el-card>

          <!-- 输入契约（只读展示：改契约会触发编译期拒绝，由工作流编辑器/接口层维护） -->
          <el-card v-if="editForm.template_inputs?.length" shadow="never" class="edit-card">
            <template #header><span class="card-title">输入契约（template_inputs）</span></template>
            <el-table :data="editForm.template_inputs" size="small" border>
              <el-table-column prop="slot" label="槽位" width="200" />
              <el-table-column label="必需来源键">
                <template #default="{ row }">
                  <template v-if="row.required_sources?.length">
                    <el-tag v-for="src in row.required_sources" :key="src" size="small" class="src-tag">
                      {{ src }}
                    </el-tag>
                  </template>
                  <span v-else class="no-src">—</span>
                </template>
              </el-table-column>
            </el-table>
          </el-card>

          <!-- 工具配置（仅分析师；内置只读展示） -->
          <el-card v-if="editForm.phase === 1" shadow="never" class="edit-card">
            <template #header><span class="card-title">工具配置</span></template>

            <!-- 内置只读：标签平铺（ToolSelector 无禁用态，编辑视图仅自定义条目渲染） -->
            <div v-if="readonly" class="readonly-tools">
              <div class="readonly-tools__row">
                <span class="readonly-tools__label">预注入数据源</span>
                <template v-if="editForm.data_tools?.length">
                  <el-tag v-for="t in editForm.data_tools" :key="t" size="small" class="src-tag">{{ t }}</el-tag>
                </template>
                <span v-else class="no-src">—</span>
              </div>
              <div class="readonly-tools__row">
                <span class="readonly-tools__label">MCP 工具</span>
                <template v-if="editForm.mcp_tools?.length">
                  <el-tag v-for="t in editForm.mcp_tools" :key="t" size="small" type="warning" class="src-tag">
                    {{ t }}
                  </el-tag>
                </template>
                <span v-else class="no-src">不限制（默认全部可用）</span>
              </div>
              <div class="readonly-tools__row">
                <span class="readonly-tools__label">技能</span>
                <template v-if="editForm.skills?.length">
                  <el-tag v-for="t in editForm.skills" :key="t" size="small" type="danger" class="src-tag">
                    {{ t }}
                  </el-tag>
                </template>
                <span v-else class="no-src">不限制（默认全部可用）</span>
              </div>
            </div>

            <el-tabs v-else v-model="activeToolTab">
              <el-tab-pane label="数据工具" name="datasource">
                <div class="tab-hint">
                  预注入数据源：分析师启动时由系统预取并注入上下文（AI 不可主动调用）。
                  不勾选 = 该智能体不注入任何数据。
                </div>
                <ToolSelector
                  v-model="editForm.data_tools"
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
                  :model-value="editForm.mcp_tools || []"
                  :tools="toolsByKind.mcp"
                  :loading="toolsLoading"
                  empty-text="暂无 MCP 工具（需先配置 MCP 服务器）"
                  empty-hint="未勾选 = 全部 MCP 工具"
                  @update:model-value="setMcpTools"
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
                  :model-value="editForm.skills || []"
                  :tools="toolsByKind.skill"
                  :loading="toolsLoading"
                  empty-text="暂无已安装技能"
                  empty-hint="未勾选 = 全部技能"
                  @update:model-value="setSkills"
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

          <!-- 系统提示词 -->
          <el-card shadow="never" class="edit-card">
            <template #header><span class="card-title">系统提示词（roleDefinition）</span></template>
            <el-input
              v-model="editForm.roleDefinition"
              type="textarea"
              :rows="14"
              class="prompt-editor"
              placeholder="系统提示词，必填"
              maxlength="20000"
              show-word-limit
              :disabled="readonly"
              @input="markDirty"
            />
          </el-card>

          <!-- 底部操作 -->
          <div class="edit-actions">
            <el-button v-if="editForm.builtin" type="primary" plain :loading="forking" @click="openForkDialog">
              复制为自定义副本
            </el-button>
            <template v-else>
              <el-popconfirm
                title="确定删除该智能体吗？被工作流引用时删除会被拒绝。"
                confirm-button-text="删除"
                cancel-button-text="取消"
                @confirm="removeAgent"
              >
                <template #reference>
                  <el-button type="danger" plain :loading="deleting">删除智能体</el-button>
                </template>
              </el-popconfirm>
              <el-button type="primary" :loading="saving" :disabled="readonly" @click="saveAgent">
                保存
              </el-button>
            </template>
          </div>
        </template>
      </el-main>
    </el-container>

    <!-- fork 对话框 -->
    <el-dialog v-model="forkDialogVisible" title="复制为自定义副本" width="460px" :close-on-click-modal="false">
      <el-form label-width="80px" label-position="left">
        <el-form-item label="新 slug" required>
          <el-input v-model="forkForm.new_slug" placeholder="唯一标识" />
        </el-form-item>
        <el-form-item label="名称" required>
          <el-input v-model="forkForm.name" placeholder="显示名称" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="forkDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="forking" @click="doFork">复制</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Refresh, Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { agentApi, type AgentListItem, type AgentSpecDto } from '@/api/workflows'
import { toolsApi } from '@/api/tools'
import type { UnifiedTool, ToolKind } from '@/types/tools'
import ToolSelector, { type ToolOption } from '@/components/Settings/ToolSelector.vue'

/** 编辑模型：AgentSpecDto 摊平 + 库层元数据（phase/builtin/引用） */
interface EditForm {
  slug: string
  name: string
  description: string
  roleDefinition: string
  phase: number
  default_selected: boolean
  data_tools: string[]
  mcp_tools: string[] | null
  skills: string[] | null
  template_inputs: { slot: string; required_sources?: string[] }[]
  builtin: boolean
  isNew: boolean
  referenced_by: string[]
}

const loading = ref(false)
const saving = ref(false)
const deleting = ref(false)
const forking = ref(false)
const filterPhase = ref(0)
const items = ref<AgentListItem[]>([])
const activeSlug = ref('')
const dirty = ref(false)
const activeToolTab = ref('datasource')

const forkDialogVisible = ref(false)
const forkForm = reactive({ new_slug: '', name: '' })

const editForm = ref<EditForm | null>(null)

const readonly = computed(() => editForm.value?.builtin === true && !editForm.value.isNew)
const visibleItems = computed(() =>
  filterPhase.value ? items.value.filter((i) => i.phase === filterPhase.value) : items.value,
)

// ── 工具清单 ──
const toolOptions = ref<ToolOption[]>([])
const toolsLoading = ref(false)

const toolsByKind = computed<Record<ToolKind, ToolOption[]>>(() => {
  const grouped: Record<ToolKind, ToolOption[]> = { datasource: [], builtin: [], skill: [], mcp: [] }
  for (const tool of toolOptions.value) {
    if (tool.kind) grouped[tool.kind].push(tool)
  }
  return grouped
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

// 「限制」开关：字段为 null = 不限制（默认全部可用）
const mcpRestricted = computed({
  get: () => editForm.value?.mcp_tools != null,
  set: (on: boolean) => {
    if (editForm.value) {
      editForm.value.mcp_tools = on ? [...(editForm.value.mcp_tools || [])] : null
      markDirty()
    }
  },
})
const skillRestricted = computed({
  get: () => editForm.value?.skills != null,
  set: (on: boolean) => {
    if (editForm.value) {
      editForm.value.skills = on ? [...(editForm.value.skills || [])] : null
      markDirty()
    }
  },
})

const markDirty = () => {
  dirty.value = true
}

const setMcpTools = (v: string[]) => {
  if (!editForm.value) return
  editForm.value.mcp_tools = v
  markDirty()
}

const setSkills = (v: string[]) => {
  if (!editForm.value) return
  editForm.value.skills = v
  markDirty()
}

const toEditForm = (item: AgentListItem): EditForm => ({
  slug: item.slug,
  name: item.spec.name || '',
  description: item.spec.description || '',
  roleDefinition: item.spec.roleDefinition || '',
  phase: item.phase,
  default_selected: item.spec.default_selected === true,
  data_tools: Array.isArray(item.spec.data_tools) ? [...item.spec.data_tools] : [],
  mcp_tools: Array.isArray(item.spec.mcp_tools) ? [...item.spec.mcp_tools!] : null,
  skills: Array.isArray(item.spec.skills) ? [...item.spec.skills!] : null,
  template_inputs: (item.spec.template_inputs || []).map((t) => ({
    slot: t.slot,
    required_sources: t.required_sources ? [...t.required_sources] : [],
  })),
  builtin: item.builtin,
  isNew: false,
  referenced_by: item.referenced_by || [],
})

const fetchList = async () => {
  loading.value = true
  try {
    const res = await agentApi.list(filterPhase.value || undefined)
    items.value = res.data?.agents || []
    // 当前选中条目刷新元数据（引用计数等）
    if (activeSlug.value) {
      const fresh = items.value.find((i) => i.slug === activeSlug.value)
      if (fresh && editForm.value && !editForm.value.isNew && !dirty.value) {
        editForm.value = toEditForm(fresh)
      }
    }
  } catch (error) {
    console.error('获取智能体列表失败', error)
    ElMessage.error('获取智能体列表失败')
  } finally {
    loading.value = false
  }
}

const confirmDiscard = async (): Promise<boolean> => {
  if (!dirty.value) return true
  try {
    await ElMessageBox.confirm('当前编辑内容尚未保存，切换将丢失。确定切换吗？', '未保存的修改', {
      confirmButtonText: '丢弃并切换',
      cancelButtonText: '继续编辑',
      type: 'warning',
    })
    return true
  } catch {
    return false
  }
}

const selectAgent = async (slug: string) => {
  if (slug === activeSlug.value) return
  if (!(await confirmDiscard())) return
  const item = items.value.find((i) => i.slug === slug)
  if (!item) return
  activeSlug.value = slug
  editForm.value = toEditForm(item)
  dirty.value = false
  activeToolTab.value = 'datasource'
}

const addAgent = async () => {
  if (!(await confirmDiscard())) return
  activeSlug.value = ''
  editForm.value = {
    slug: '',
    name: '',
    description: '',
    roleDefinition: '',
    phase: filterPhase.value || 1,
    default_selected: false,
    data_tools: [],
    mcp_tools: null,
    skills: null,
    template_inputs: [],
    builtin: false,
    isNew: true,
    referenced_by: [],
  }
  dirty.value = true
  activeToolTab.value = 'datasource'
}

const validateForm = (): boolean => {
  const form = editForm.value
  if (!form) return false
  if (!form.slug.trim()) {
    ElMessage.error('slug 为必填')
    return false
  }
  if (!/^[a-z0-9][a-z0-9-_]*$/.test(form.slug.trim())) {
    ElMessage.error('slug 仅限小写字母、数字、-、_')
    return false
  }
  if (!form.name.trim()) {
    ElMessage.error('名称为必填')
    return false
  }
  if (!form.roleDefinition.trim()) {
    ElMessage.error('roleDefinition 为必填')
    return false
  }
  return true
}

const buildSpecPayload = (): AgentSpecDto & { phase: number } => {
  const form = editForm.value!
  const payload: AgentSpecDto & { phase: number } = {
    slug: form.slug.trim(),
    name: form.name.trim(),
    description: form.description || form.slug.trim(),
    roleDefinition: form.roleDefinition,
    phase: form.phase,
  }
  if (form.phase === 1) {
    payload.data_tools = form.data_tools?.length ? Array.from(new Set(form.data_tools)) : []
    payload.default_selected = form.default_selected === true
    if (form.mcp_tools != null && form.mcp_tools.length) {
      payload.mcp_tools = Array.from(new Set(form.mcp_tools))
    }
    if (form.skills != null && form.skills.length) {
      payload.skills = Array.from(new Set(form.skills))
    }
  }
  return payload
}

const saveAgent = async () => {
  if (!validateForm()) return
  const form = editForm.value!
  saving.value = true
  try {
    if (form.isNew) {
      await agentApi.create(buildSpecPayload())
      ElMessage.success('智能体已创建')
    } else {
      await agentApi.update(form.slug, buildSpecPayload())
      ElMessage.success('智能体已保存')
    }
    activeSlug.value = form.slug.trim()
    dirty.value = false
    await fetchList()
    const fresh = items.value.find((i) => i.slug === activeSlug.value)
    if (fresh) editForm.value = toEditForm(fresh)
  } catch (error) {
    console.error('保存智能体失败', error)
  } finally {
    saving.value = false
  }
}

/** 409 被引用时的 detail.referenced_by（FastAPI HTTPException detail 经 axios response 透传） */
const extractReferencedBy = (error: unknown): string[] => {
  const detail = (error as { response?: { data?: { detail?: { referenced_by?: string[] } } } })?.response?.data?.detail
  return detail?.referenced_by || []
}

const removeAgent = async () => {
  const form = editForm.value
  if (!form || form.isNew) {
    editForm.value = null
    return
  }
  deleting.value = true
  try {
    await agentApi.remove(form.slug)
    ElMessage.success('智能体已删除')
    activeSlug.value = ''
    editForm.value = null
    dirty.value = false
    await fetchList()
  } catch (error) {
    const refs = extractReferencedBy(error)
    if (refs.length) {
      ElMessageBox.alert(
        `该智能体正被以下工作流引用，无法删除：${refs.join('、')}。请先在对应工作流中移除引用。`,
        '删除被拒绝',
        { type: 'warning' },
      ).catch(() => undefined)
    }
    console.error('删除智能体失败', error)
  } finally {
    deleting.value = false
  }
}

const openForkDialog = () => {
  const form = editForm.value
  if (!form) return
  forkForm.new_slug = `${form.slug}-copy`
  forkForm.name = `${form.name || form.slug}（副本）`
  forkDialogVisible.value = true
}

const doFork = async () => {
  const form = editForm.value
  if (!form) return
  const newSlug = forkForm.new_slug.trim()
  if (!newSlug || !forkForm.name.trim()) {
    ElMessage.warning('新 slug 与名称为必填')
    return
  }
  if (!/^[a-z0-9][a-z0-9-_]*$/.test(newSlug)) {
    ElMessage.warning('slug 仅限小写字母、数字、-、_')
    return
  }
  forking.value = true
  try {
    await agentApi.fork(form.slug, { new_slug: newSlug, name: forkForm.name.trim() })
    ElMessage.success('副本已创建')
    forkDialogVisible.value = false
    activeSlug.value = newSlug
    dirty.value = false
    await fetchList()
    const fresh = items.value.find((i) => i.slug === newSlug)
    if (fresh) editForm.value = toEditForm(fresh)
  } catch (error) {
    console.error('复制智能体失败', error)
  } finally {
    forking.value = false
  }
}

onMounted(() => {
  fetchToolOptions()
  fetchList().then(() => {
    if (items.value.length && !activeSlug.value) {
      selectAgent(items.value[0].slug)
    }
  })
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
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}

.title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.subtitle {
  color: var(--el-text-color-secondary);
  font-size: 12px;
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
  margin-bottom: 12px;
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

  &.is-new {
    border: 1px dashed var(--el-color-primary);
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

.card-head-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-title {
  font-size: 13px;
  font-weight: 600;
}

.ref-list {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.src-tag {
  margin-right: 4px;
}

.no-src {
  color: var(--el-text-color-secondary);
}

.readonly-tools {
  &__row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 4px;
    margin-bottom: 8px;
  }

  &__label {
    width: 110px;
    flex-shrink: 0;
    color: var(--el-text-color-regular);
    font-size: 13px;
  }
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
