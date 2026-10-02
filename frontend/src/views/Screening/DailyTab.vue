<template>
  <div class="daily-tab" v-loading="loading">
    <div class="daily-toolbar">
      <span v-if="tradeDate" class="trade-date">交易日 {{ tradeDate }}</span>
      <el-button link @click="load">
        <el-icon><Refresh /></el-icon>
        刷新
      </el-button>
    </div>

    <el-empty
      v-if="!loading && strategies.length === 0"
      :image-size="160"
    >
      <template #description>
        <p class="empty-title">暂无每日推荐</p>
        <p class="empty-desc">
          因子批算与推荐生成依赖财务/资金流等数据同步（每交易日 20:15 起自动执行），若持续为空请检查数据同步
        </p>
      </template>
      <el-button type="primary" @click="goDataCenter">前往数据中心</el-button>
    </el-empty>

    <el-collapse v-else v-model="activeNames">
      <el-collapse-item
        v-for="s in strategies"
        :key="s.strategy_id"
        :name="s.strategy_id"
      >
        <template #title>
          <div class="collapse-title">
            <span class="name">{{ s.strategy_name || s.strategy_id }}</span>
            <el-tag size="small" type="info" effect="plain">{{ s.total || 0 }} 只</el-tag>
            <el-tag
              v-if="s.insight_status === 'done'"
              size="small"
              type="success"
              effect="plain"
            >
              AI 已研判
            </el-tag>
            <el-tag
              v-else-if="s.insight_status === 'failed'"
              size="small"
              type="danger"
              effect="plain"
            >
              AI 研判失败
            </el-tag>
          </div>
        </template>

        <el-table :data="s.items" stripe size="small">
          <el-table-column prop="symbol" label="代码" width="100">
            <template #default="{ row }">
              <el-link type="primary" @click="viewDetail(row)">{{ row.symbol }}</el-link>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="名称" width="110" />
          <el-table-column prop="industry" label="行业" width="130">
            <template #default="{ row }">{{ row.industry || '-' }}</template>
          </el-table-column>
          <el-table-column prop="score" label="策略得分" width="100" align="right">
            <template #default="{ row }">
              <span v-if="row.score !== null && row.score !== undefined" class="score-value">
                {{ row.score.toFixed(1) }}
              </span>
              <span v-else class="text-gray-400">-</span>
            </template>
          </el-table-column>
          <el-table-column label="入选信号" min-width="220">
            <template #default="{ row }">
              <span class="signals-cell">{{ formatSignals(row.signal_items, row.signals) || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="AI 研判" min-width="260">
            <template #default="{ row }">
              <span v-if="row.insight" class="insight-cell">{{ row.insight }}</span>
              <span v-else class="text-gray-400">-</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="130" fixed="right">
            <template #default="{ row }">
              <el-button link size="small" type="primary" @click="analyze(row)">分析</el-button>
              <el-button link size="small" @click="viewDetail(row)">详情</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script setup lang="ts">
// 今日精选 Tab：读每日推荐落库结果（0 token，含可选的自动 AI 研判文本）
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { screeningApi, type DailyStrategyEntry, type StrategyRunItem } from '@/api/screening'
import { normalizeMarketForAnalysis } from '@/utils/market'
import { formatSignals } from '@/constants/screening'

defineOptions({ name: 'ScreeningDailyTab' })

const router = useRouter()

const loading = ref(false)
const tradeDate = ref<string | null>(null)
const strategies = ref<DailyStrategyEntry[]>([])
const activeNames = ref<string[]>([])

const load = async () => {
  loading.value = true
  try {
    const res = await screeningApi.getDaily()
    const data = (res as any)?.data || res
    tradeDate.value = data?.trade_date || null
    strategies.value = data?.strategies || []
    if (strategies.value.length && activeNames.value.length === 0) {
      activeNames.value = [strategies.value[0].strategy_id]
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '获取每日推荐失败')
  } finally {
    loading.value = false
  }
}

const analyze = (row: StrategyRunItem) => {
  router.push({
    name: 'SingleAnalysis',
    query: {
      stock: row.symbol,
      market: normalizeMarketForAnalysis('A股')
    }
  })
}

const viewDetail = (row: StrategyRunItem) => {
  router.push({ name: 'StockDetail', params: { code: row.symbol } })
}

/** 空态时引导去数据中心检查/补同步因子依赖的数据 */
const goDataCenter = () => {
  router.push('/data')
}

onMounted(load)
</script>

<style scoped>
.daily-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.trade-date {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.empty-title {
  margin: 0;
}

.empty-desc {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}

.collapse-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.collapse-title .name {
  font-weight: 600;
}

.score-value {
  font-weight: 600;
  color: var(--el-color-primary);
}

.signals-cell,
.insight-cell {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-size: 13px;
  line-height: 1.5;
}
</style>
