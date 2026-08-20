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
            <el-descriptions :column="1" size="small" border class="config-desc">
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
          <el-empty v-else description="暂无配置信息" :image-size="48" />
        </template>
      </el-skeleton>
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
import { computed, onMounted, ref } from 'vue'
import type { TaskOverview } from '@/api/analysis'
import { loadAgentDisplayNames } from '@/utils/agentDisplayNames'

const props = defineProps<{
  overview: TaskOverview | null
  loading: boolean
}>()

// 智能体中文显示名：一律来自后端 agent 配置（loadAgentDisplayNames），
// 加载完成前先显示 slug，映射到达后自动替换
const displayNames = ref<Record<string, string>>({})
onMounted(async () => {
  try {
    displayNames.value = await loadAgentDisplayNames()
  } catch {
    // 映射加载失败时保留 slug 展示，不阻断侧栏
  }
})

const parameters = computed<Record<string, unknown>>(() => props.overview?.task.parameters ?? {})

const analystChips = computed(() => {
  const slugs = Array.isArray(parameters.value.selected_analysts)
    ? (parameters.value.selected_analysts as unknown[]).filter((s): s is string => typeof s === 'string')
    : []
  return slugs.map((slug) => ({ slug, label: displayNames.value[slug] ?? slug }))
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

// 辩论轮次：phase2/3/4 各阶段一行，仅在启用时展示
const debateRounds = computed(() => {
  const phases: Array<[string, string]> = [
    ['phase2_enabled', 'phase2_debate_rounds'],
    ['phase3_enabled', 'phase3_debate_rounds'],
    ['phase4_enabled', 'phase4_debate_rounds'],
  ]
  const lines: string[] = []
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
</style>
