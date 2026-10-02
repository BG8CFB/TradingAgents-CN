<template>
  <div class="task-sidebar">
    <!-- 分析配置 -->
    <el-card shadow="never" class="sidebar-card">
      <template #header>
        <span class="card-title">分析配置</span>
      </template>
      <el-skeleton :loading="loading" :rows="4" animated>
        <template #default>
          <div v-if="hasConfig" class="config-body">
            <div v-if="analystChips.length" class="config-row">
              <div class="row-label">分析师</div>
              <div class="chips">
                <el-tag
                  v-for="chip in analystChips"
                  :key="chip.slug"
                  size="small"
                  type="info"
                  class="analyst-chip"
                >
                  {{ chip.label }}
                </el-tag>
              </div>
            </div>
            <div v-if="phaseChips.length" class="config-row">
              <div class="row-label">启用阶段</div>
              <div class="chips">
                <el-tag
                  v-for="chip in phaseChips"
                  :key="chip.label"
                  size="small"
                  :type="chip.rounds > 0 ? 'success' : 'info'"
                  effect="plain"
                >
                  {{ chip.label }}{{ chip.rounds > 0 ? ` · ${chip.rounds} 轮` : '' }}
                </el-tag>
              </div>
            </div>
            <el-descriptions :column="1" size="small" border class="config-desc">
              <el-descriptions-item label="工作流">
                {{ workflowLabel }}
              </el-descriptions-item>
              <el-descriptions-item v-if="analysisDate" label="分析日期">
                {{ analysisDate }}
              </el-descriptions-item>
              <el-descriptions-item v-if="marketType" label="市场">
                {{ marketType }}
              </el-descriptions-item>
              <el-descriptions-item v-if="analystModel" label="分析师模型">
                {{ analystModel }}
              </el-descriptions-item>
              <el-descriptions-item v-if="debateModel" label="辩论模型">
                {{ debateModel }}
              </el-descriptions-item>
              <el-descriptions-item
                v-if="debateRounds.length"
                label="辩论轮次"
              >
                <span class="rounds-line">{{ debateRounds.join('\n') }}</span>
              </el-descriptions-item>
              <el-descriptions-item v-if="language" label="语言">
                {{ language }}
              </el-descriptions-item>
            </el-descriptions>
          </div>
          <el-empty v-else description="未记录（旧任务可能未保存参数）" :image-size="48" />
        </template>
      </el-skeleton>
    </el-card>

    <!-- 执行计划（按任务提交参数与当前工作流定义推导） -->
    <el-card v-if="workflowSlugParam" shadow="never" class="sidebar-card">
      <template #header>
        <span class="card-title">执行计划</span>
      </template>
      <el-skeleton v-if="planLoading" :rows="3" animated />
      <div v-else-if="planRows.length" class="plan-body">
        <div
          v-for="row in planRows"
          :key="row.id"
          class="plan-row"
          :class="{ skipped: row.skipped }"
        >
          <el-tag :type="row.skipped ? 'info' : 'success'" size="small" effect="plain">
            {{ row.skipped ? '跳过' : '执行' }}
          </el-tag>
          <span class="plan-label">{{ row.label }}</span>
          <span v-if="row.batchInfo" class="plan-batch">{{ row.batchInfo }}</span>
        </div>
        <div class="plan-note">按任务提交参数与当前工作流定义推导</div>
      </div>
      <div v-else class="plan-muted">
        {{ planSpecFailed ? '工作流已删除或不可访问，以上为提交参数' : '暂无执行计划' }}
      </div>
    </el-card>

    <!-- 股票信息 -->
    <el-card shadow="never" class="sidebar-card">
      <template #header>
        <span class="card-title">股票信息</span>
      </template>
      <el-skeleton :loading="loading" :rows="3" animated>
        <template #default>
          <el-descriptions
            v-if="overview?.stock_info"
            :column="1"
            size="small"
            border
          >
            <el-descriptions-item label="名称">
              <span class="stock-value">{{ overview.stock_info.name || '—' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="市场">
              {{ marketLabel }}
            </el-descriptions-item>
            <el-descriptions-item label="行业">
              <span class="stock-value">{{ overview.stock_info.industry || '—' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="最新价">
              {{ latestPrice }}
            </el-descriptions-item>
          </el-descriptions>
          <el-empty
            v-else
            description="暂无股票信息"
            :image-size="48"
          />
        </template>
      </el-skeleton>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import type { TaskOverview } from '@/api/analysis'
import { workflowApi, type WorkflowSpecDto } from '@/api/workflows'
import { agentConfigApi } from '@/api/agentConfigs'
import { loadAgentDisplayNames } from '@/utils/agentDisplayNames'

const props = defineProps<{
  overview: TaskOverview | null
  loading: boolean
}>()

// 智能体中文显示名：一律来自后端 agent 配置（loadAgentDisplayNames），
// 加载完成前先显示 slug，映射到达后自动替换
const displayNames = ref<Record<string, string>>({})
onMounted(async () => {
  const [names, phase1] = await Promise.allSettled([
    loadAgentDisplayNames(),
    agentConfigApi.getPhase(1),
  ])
  // 任一失败都不阻断侧栏：显示名保留 slug，pool 分母缺省时隐藏
  if (names.status === 'fulfilled') displayNames.value = names.value
  if (phase1.status === 'fulfilled' && phase1.value.data?.customModes) {
    poolSlugs.value = phase1.value.data.customModes.map((m) => m.slug)
  }
})

const parameters = computed<Record<string, unknown>>(() => props.overview?.task.parameters ?? {})

const analystChips = computed(() => {
  const slugs = Array.isArray(parameters.value.selected_analysts)
    ? (parameters.value.selected_analysts as unknown[]).filter((s): s is string => typeof s === 'string')
    : []
  return slugs.map((slug) => ({ slug, label: displayNames.value[slug] ?? slug }))
})

// 工作流：任务参数携带 workflow_slug 时展示，旧任务缺省 = 默认工作流
const workflowLabel = computed(() => strParam('workflow_slug') || '默认工作流')

/** stage_overrides（新契约）里的启用条目：{stage_id: {enabled, rounds}} */
interface StageOverrideEntry {
  enabled?: boolean
  rounds?: number
}
const stageOverrides = computed<Record<string, StageOverrideEntry> | null>(() => {
  const raw = parameters.value.stage_overrides
  if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
    return raw as Record<string, StageOverrideEntry>
  }
  return null
})

// stage id → 侧栏展示名（自定义 stage id 原样展示）
const STAGE_LABELS: Record<string, string> = {
  research_debate: '研究辩论',
  risk_debate: '风险管理辩论',
  trader: '交易决策',
}

// ── 执行计划：按任务提交参数（stage_overrides / selected_nodes）与当前工作流定义推导 ──
const workflowSlugParam = computed(() => strParam('workflow_slug'))
const planSpec = ref<WorkflowSpecDto | null>(null)
const planSpecFailed = ref(false)
const planLoading = ref(false)
// pool 批成员全集（phase1 智能体库），执行计划的「已选 / 总数」分母
const poolSlugs = ref<string[]>([])

const PLAN_MODE_LABEL: Record<string, string> = {
  parallel_batch: '并行批',
  debate: '辩论',
  single: '单智能体',
}

interface PlanRow {
  id: string
  label: string
  skipped: boolean
  batchInfo?: string
}

const planRows = computed<PlanRow[]>(() => {
  const spec = planSpec.value
  if (!spec) return []
  const rawSelected = Array.isArray(parameters.value.selected_nodes)
    ? parameters.value.selected_nodes
    : parameters.value.selected_analysts
  const selected = new Set(
    (Array.isArray(rawSelected) ? rawSelected : []).filter((s): s is string => typeof s === 'string'),
  )
  return spec.stages.map((stage, idx) => {
    const members = stage.pool ? poolSlugs.value : (stage.nodes || []).map((n) => n.ref)
    const chosen = members.filter((s) => selected.has(s)).length
    return {
      id: stage.id,
      label: `${idx + 1}. ${STAGE_LABELS[stage.id] ?? `${stage.id}（${PLAN_MODE_LABEL[stage.mode] || stage.mode}）`}`,
      // 无 overrides 条目 / 旧任务 = 执行；仅显式 enabled:false 才是跳过
      skipped: stageOverrides.value?.[stage.id]?.enabled === false,
      batchInfo:
        stage.mode === 'parallel_batch' && members.length ? `${chosen} / ${members.length} 个分析师` : undefined,
    }
  })
})

// overview 异步到达后 slug 才可用：watch 而非 onMounted 一次性读取
watch(
  workflowSlugParam,
  async (slug) => {
    if (!slug) {
      planSpec.value = null
      planSpecFailed.value = false
      planLoading.value = false
      return
    }
    planLoading.value = true
    try {
      const res = await workflowApi.get(slug)
      planSpec.value = res.data.workflow
      planSpecFailed.value = false
    } catch {
      planSpec.value = null
      planSpecFailed.value = true
    } finally {
      planLoading.value = false
    }
  },
  { immediate: true },
)

// 已启用阶段 chips：优先 stage_overrides（stage_id 键），旧任务回落 phaseN_enabled
const phaseChips = computed(() => {
  if (stageOverrides.value) {
    return Object.entries(stageOverrides.value)
      .filter(([, entry]) => entry?.enabled === true)
      .map(([stageId, entry]) => ({
        label: STAGE_LABELS[stageId] ?? stageId,
        rounds: typeof entry?.rounds === 'number' ? entry.rounds : 0,
      }))
  }
  const phases: Array<{ enabledKey: string; label: string; roundsKey: string }> = [
    { enabledKey: 'phase2_enabled', label: '阶段2 · 研究辩论', roundsKey: 'phase2_debate_rounds' },
    { enabledKey: 'phase3_enabled', label: '阶段3 · 风险管理', roundsKey: 'phase3_debate_rounds' },
    { enabledKey: 'phase4_enabled', label: '阶段4 · 交易决策', roundsKey: 'phase4_debate_rounds' },
  ]
  return phases
    .filter(p => parameters.value[p.enabledKey] === true)
    .map(p => ({
      label: p.label,
      rounds: typeof parameters.value[p.roundsKey] === 'number' ? (parameters.value[p.roundsKey] as number) : 0,
    }))
})

function strParam(key: string): string {
  const v = parameters.value[key]
  if (typeof v === 'string' && v) return v
  if (typeof v === 'number') return String(v)
  return ''
}

const analysisDate = computed(() => strParam('analysis_date').slice(0, 10))
const marketType = computed(() => strParam('market_type'))
const analystModel = computed(() => strParam('analyst_model'))
const debateModel = computed(() => strParam('debate_model'))
const language = computed(() => strParam('language'))

// 辩论轮次：优先 stage_overrides 的 debate 阶段轮数，旧任务回落 phaseN_ 字段
const debateRounds = computed(() => {
  const lines: string[] = []
  if (stageOverrides.value) {
    for (const [stageId, entry] of Object.entries(stageOverrides.value)) {
      if (entry?.enabled !== true || typeof entry.rounds !== 'number') continue
      lines.push(`${STAGE_LABELS[stageId] ?? stageId}：${entry.rounds} 轮`)
    }
    return lines
  }
  const phases: Array<[string, string]> = [
    ['phase2_enabled', 'phase2_debate_rounds'],
    ['phase3_enabled', 'phase3_debate_rounds'],
    ['phase4_enabled', 'phase4_debate_rounds'],
  ]
  for (const [enabledKey, roundsKey] of phases) {
    if (parameters.value[enabledKey] === true) {
      const rounds = parameters.value[roundsKey]
      const n = typeof rounds === 'number' ? rounds : 0
      lines.push(`${enabledKey.replace(/_enabled$/, '').replace('phase', '阶段')}：${n} 轮`)
    }
  }
  return lines
})

const hasConfig = computed(() =>
  analystChips.value.length > 0 ||
  phaseChips.value.length > 0 ||
  Boolean(analysisDate.value || marketType.value || analystModel.value || debateModel.value || debateRounds.value.length)
)

const MARKET_LABELS: Record<string, string> = { CN: 'A股', HK: '港股', US: '美股' }
const marketLabel = computed(() => {
  const m = props.overview?.stock_info?.market
  return m ? (MARKET_LABELS[m] ?? m) : '—'
})

const latestPrice = computed(() => {
  const p = props.overview?.stock_info?.latest_price
  return typeof p === 'number' ? p.toFixed(2) : '—'
})
</script>

<style scoped>
.sidebar-card {
  margin-bottom: 12px;
}

.card-title {
  font-weight: 600;
  font-size: 14px;
}

.config-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.config-row .row-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 6px;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.analyst-chip {
  max-width: 100%;
}

.config-desc :deep(.el-descriptions__label) {
  width: 84px;
  min-width: 84px;
}

.rounds-line {
  white-space: pre-line;
}

.stock-value {
  word-break: break-all;
}

.plan-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.plan-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.plan-row.skipped {
  opacity: 0.55;
}

.plan-label {
  min-width: 0;
  word-break: break-all;
}

.plan-batch {
  margin-left: auto;
  flex-shrink: 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.plan-note,
.plan-muted {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
