<template>
  <div class="workflow-page">
    <!-- 顶栏 -->
    <div class="page-header">
      <div class="page-title">
        <h2 class="title">工作流管理</h2>
        <span class="subtitle">任务缺省使用默认工作流；内置工作流只读，定制从复制开始</span>
      </div>
      <div class="page-actions">
        <el-button size="small" :loading="loading" @click="fetchList">
          <el-icon><Refresh /></el-icon>&nbsp;刷新
        </el-button>
        <el-button size="small" type="primary" :disabled="!builtinSlugs.length" @click="dialogVisible = true">
          <el-icon><Plus /></el-icon>&nbsp;新建工作流
        </el-button>
      </div>
    </div>

    <!-- 列表 -->
    <div v-loading="loading" class="workflow-grid">
      <el-empty v-if="!loading && !items.length" description="暂无工作流" class="page-empty" />
      <el-card
        v-for="item in items"
        :key="item.slug"
        shadow="never"
        class="workflow-card"
        :class="{ 'is-invalid': !item.valid }"
      >
        <template #header>
          <div class="card-head">
            <div class="card-title-wrap">
              <span class="card-title" :title="item.slug">{{ item.name || item.slug }}</span>
              <div class="card-badges">
                <el-tag v-if="item.builtin" size="small" type="info" effect="plain">内置</el-tag>
                <el-tag v-if="item.is_default" size="small" type="success" effect="plain">默认</el-tag>
                <el-tag v-if="!item.valid" size="small" type="danger" effect="plain">校验失败</el-tag>
                <el-tag v-if="!item.enabled" size="small" type="warning" effect="plain">已停用</el-tag>
              </div>
            </div>
            <span class="card-slug">{{ item.slug }}</span>
          </div>
        </template>

        <p class="card-desc" :title="item.description">{{ item.description || '暂无描述' }}</p>

        <div class="card-stages">
          <span v-for="(stage, idx) in item.stages" :key="stage.id" class="stage-chip">
            <span class="stage-idx">{{ idx + 1 }}</span>{{ stage.id }}
            <span class="stage-mode">{{ MODE_LABEL[stage.mode] || stage.mode }}</span>
          </span>
        </div>

        <div v-if="!item.valid" class="card-errors">
          <div v-for="err in item.validation_errors.slice(0, 2)" :key="err" class="err-line">⚠ {{ err }}</div>
          <div v-if="item.validation_errors.length > 2" class="err-more">
            …共 {{ item.validation_errors.length }} 条，进入编辑器查看
          </div>
        </div>

        <div class="card-footer">
          <span class="card-meta">更新于 {{ formatTime(item.updated_at) }}</span>
          <div class="card-ops">
            <el-button
              v-if="!item.builtin && item.valid"
              size="small"
              text
              type="primary"
              @click="goEdit(item.slug)"
            >
              编辑
            </el-button>
            <el-button v-else size="small" text type="primary" @click="goView(item.slug)">查看</el-button>
            <el-button
              v-if="!item.is_default && item.valid"
              size="small"
              text
              :loading="defaultPending === item.slug"
              @click="setDefault(item.slug)"
            >
              设为默认
            </el-button>
            <el-button size="small" text @click="openCopy(item)">复制</el-button>
            <el-button
              v-if="!item.builtin"
              size="small"
              text
              type="danger"
              :loading="deletePending === item.slug"
              @click="removeWorkflow(item)"
            >
              删除
            </el-button>
          </div>
        </div>
      </el-card>
    </div>

    <!-- 新建对话框：从内置复制（默认，可跑示例）或空白画布（自由搭建） -->
    <el-dialog v-model="dialogVisible" title="新建工作流" width="520px" :close-on-click-modal="false">
      <el-form label-width="90px" label-position="left">
        <el-form-item label="来源">
          <el-radio-group v-model="createForm.source">
            <el-radio value="copy">复制现有工作流</el-radio>
            <el-radio value="blank">空白画布</el-radio>
          </el-radio-group>
          <div v-if="createForm.source === 'blank'" class="blank-hint">
            空画布自由搭建：预置 trader / 风控裁决（终点）/ 总结 三个节点定义与终端契约，画布为空，可随时保存
          </div>
        </el-form-item>
        <el-form-item v-if="createForm.source === 'copy'" label="复制自">
          <el-select v-model="createForm.fromSlug" style="width: 100%">
            <el-option
              v-for="item in copyableItems"
              :key="item.slug"
              :value="item.slug"
              :label="`${item.name}（${item.slug}）`"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="slug" required>
          <el-input v-model="createForm.slug" placeholder="唯一标识，如 my-workflow" />
        </el-form-item>
        <el-form-item label="名称" required>
          <el-input v-model="createForm.name" placeholder="显示名称" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="createWorkflow">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Plus } from '@element-plus/icons-vue'
import { workflowApi, type WorkflowListItem, type WorkflowSpecDto } from '@/api/workflows'

const MODE_LABEL: Record<string, string> = {
  parallel_batch: '并行批',
  debate: '辩论',
  single: '单智能体',
}

const router = useRouter()
const loading = ref(false)
const items = ref<WorkflowListItem[]>([])
const defaultPending = ref('')
const deletePending = ref('')

const dialogVisible = ref(false)
const creating = ref(false)
const createForm = reactive({ source: 'copy' as 'copy' | 'blank', fromSlug: '', slug: '', name: '' })

const builtinSlugs = computed(() => items.value.filter((i) => i.valid).map((i) => i.slug))
const copyableItems = computed(() => items.value.filter((i) => i.valid))

const formatTime = (t?: string) => {
  if (!t) return '—'
  const d = new Date(t)
  return Number.isNaN(d.getTime()) ? t : d.toLocaleString('zh-CN', { hour12: false })
}

const fetchList = async () => {
  loading.value = true
  try {
    const res = await workflowApi.list()
    items.value = res.data?.workflows || []
    if (!createForm.fromSlug && copyableItems.value.length) {
      createForm.fromSlug = copyableItems.value[0].slug
    }
  } catch (error) {
    console.error('获取工作流列表失败', error)
    ElMessage.error('获取工作流列表失败')
  } finally {
    loading.value = false
  }
}

const goEdit = (slug: string) => router.push(`/settings/workflows/${slug}/edit`)
const goView = (slug: string) => router.push(`/settings/workflows/${slug}/edit`)

const setDefault = async (slug: string) => {
  defaultPending.value = slug
  try {
    await workflowApi.setDefault(slug)
    ElMessage.success(`已设为默认工作流：${slug}`)
    await fetchList()
  } catch (error) {
    console.error('设为默认失败', error)
  } finally {
    defaultPending.value = ''
  }
}

const removeWorkflow = async (item: WorkflowListItem) => {
  try {
    await ElMessageBox.confirm(
      `确定删除工作流「${item.name || item.slug}」吗？删除为软删除，历史任务的回放不受影响。`,
      '删除确认',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
    deletePending.value = item.slug
    try {
      await workflowApi.remove(item.slug)
      ElMessage.success('工作流已删除')
      await fetchList()
    } finally {
      deletePending.value = ''
    }
  } catch (error) {
    if (error !== 'cancel') console.error('删除工作流失败', error)
  }
}

const openCopy = (item: WorkflowListItem) => {
  createForm.source = 'copy'
  createForm.fromSlug = item.slug
  createForm.slug = `${item.slug}-copy`
  createForm.name = `${item.name || item.slug}（副本）`
  dialogVisible.value = true
}

/** 空白画布：stages 为空（画布引导自由搭建），预置 trader/risk-manager/summary
 * 三个节点定义与终端契约——满足 validator 最小可保存结构（≥1 个 terminal:true 的
 * judge 节点 + summary_node 命中），任意时刻可直接保存。node_name/event_key 为
 * 英文执行锚点名（非显示名）；risk-manager 持 terminal:true（终点写入者），
 * 用户拖入裁决组即可引用。 */
const blankSpec = (slug: string, name: string): WorkflowSpecDto => ({
  slug,
  name,
  description: '',
  version: 1,
  enabled: true,
  nodes: [
    {
      slug: 'trader',
      type: 'trader',
      execution: 'single_turn',
      terminal: false,
      memory: 'trader',
      node_name: 'Trader',
      event_key: 'trader',
      report_keys: ['trader_investment_plan', 'investment_plan', 'final_trade_decision'],
    },
    {
      slug: 'risk-manager',
      type: 'judge',
      execution: 'single_turn',
      terminal: true,
      memory: 'risk_manager',
      node_name: 'Risk Judge',
      event_key: 'risk_manager',
      report_keys: ['risk_management_decision', 'risk_manager_decision'],
    },
    {
      slug: 'summary',
      type: 'summarizer',
      execution: 'single_turn',
      terminal: false,
      memory: null,
      node_name: 'Summary Agent',
      event_key: 'summary',
      report_keys: [],
    },
  ],
  stages: [],
  terminal: {
    decision_field: 'final_trade_decision',
    signal_fallback: ['final_trade_decision', 'investment_plan'],
    summary_node: 'summary',
  },
})

const createWorkflow = async () => {
  const slug = createForm.slug.trim()
  if (!slug || !createForm.name.trim()) {
    ElMessage.warning('slug 与名称为必填')
    return
  }
  creating.value = true
  try {
    let spec: WorkflowSpecDto
    if (createForm.source === 'copy' && createForm.fromSlug) {
      const res = await workflowApi.get(createForm.fromSlug)
      spec = { ...res.data.workflow, slug, name: createForm.name.trim(), builtin: false }
    } else {
      spec = blankSpec(slug, createForm.name.trim())
    }
    await workflowApi.create(spec)
    ElMessage.success('工作流已创建')
    dialogVisible.value = false
    createForm.slug = ''
    createForm.name = ''
    goEdit(slug)
  } catch (error) {
    console.error('创建工作流失败', error)
  } finally {
    creating.value = false
  }
}

onMounted(fetchList)
</script>

<style lang="scss" scoped>
.blank-hint {
  width: 100%;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}
.workflow-page {
  padding: 16px;
  height: 100%;
  box-sizing: border-box;
  overflow-y: auto;
}

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

  .title {
    margin: 0;
    font-size: 18px;
    font-weight: 600;
  }

  .subtitle {
    color: var(--el-text-color-secondary);
    font-size: 12px;
  }
}

.page-actions {
  display: flex;
  gap: 8px;
}

.workflow-grid {
  margin-top: 12px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 12px;
  align-items: start;
}

.page-empty {
  grid-column: 1 / -1;
}

.workflow-card {
  &.is-invalid {
    border-color: var(--el-color-danger-light-5);
  }

  :deep(.el-card__header) {
    padding: 10px 14px;
  }

  :deep(.el-card__body) {
    padding: 12px 14px;
  }
}

.card-head {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.card-title-wrap {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.card-title {
  font-size: 14px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-badges {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.card-slug {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-desc {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--el-text-color-regular);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 18px;
}

.card-stages {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 10px;
}

.stage-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 10px;
  background-color: var(--el-fill-color-light);
}

.stage-idx {
  color: var(--el-text-color-secondary);
}

.stage-mode {
  color: var(--el-color-primary);
  font-size: 11px;
}

.card-errors {
  margin-bottom: 10px;
  padding: 6px 8px;
  border-radius: 4px;
  background-color: var(--el-color-danger-light-9);

  .err-line {
    font-size: 12px;
    color: var(--el-color-danger);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .err-more {
    font-size: 12px;
    color: var(--el-text-color-secondary);
  }
}

.card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.card-meta {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  flex-shrink: 0;
}

.card-ops {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;

  .el-button {
    margin: 0 0 0 4px;
    padding: 4px 6px;
  }
}

@media (max-width: 768px) {
  .workflow-grid {
    grid-template-columns: 1fr;
  }
}
</style>
