<template>
  <el-tooltip v-if="record" placement="top">
    <template #content>
      <template v-if="record.status === 'settled'">
        <div>入场：{{ dateText(record.entry_date) }} · {{ numText(record.entry_price) }}</div>
        <div>出场：{{ dateText(record.exit_date) }} · {{ numText(record.exit_price) }}</div>
        <div v-if="record.signal === 'Hold'">持有期口径：Hold 按持有期收益结算，不计入方向命中</div>
        <div v-else>方向判定：{{ record.direction_hit === true ? '对' : record.direction_hit === false ? '错' : '—' }}</div>
      </template>
      <div v-else-if="record.status === 'unfillable'">{{ record.failure_reason || '无法成交' }}</div>
      <div v-else>决策日 {{ dateText(record.decision_date) }} · 持有期 {{ record.horizon_days }} 个交易日</div>
    </template>
    <el-tag :type="tagType" size="small" effect="plain" :style="tagStyle">
      {{ tagText }}
    </el-tag>
  </el-tooltip>
</template>

<script setup lang="ts">
/**
 * 决策结算徽章：按任务 ID 查询单条结算记录并展示紧凑状态。
 *
 * 无记录（data=null）或请求失败时整组件不渲染；只在挂载时查询一次，不轮询。
 * 徽章属辅助信息，请求失败不弹全局错误（skipErrorHandler），静默隐藏。
 */
import { computed, onMounted, ref } from 'vue'
import { getSettlementByTask, type SettlementRecordWithDays } from '@/api/settlement'

const props = defineProps<{ taskId: string }>()

const record = ref<SettlementRecordWithDays | null>(null)

onMounted(async () => {
  if (!props.taskId) return
  try {
    const res = await getSettlementByTask(props.taskId, { skipErrorHandler: true })
    record.value = res.data ?? null
  } catch {
    // 结算信息缺失时保持隐藏，不打断宿主页面
  }
})

const tagType = computed((): 'success' | 'info' | 'warning' => {
  if (!record.value) return 'info'
  if (record.value.status === 'pending') return 'warning'
  return 'info'
})

const tagText = computed(() => {
  const r = record.value
  if (!r) return ''
  if (r.status === 'pending') {
    return r.days_remaining !== null && r.days_remaining !== undefined
      ? `待结算 · 约${r.days_remaining}天`
      : '待结算'
  }
  if (r.status === 'unfillable') return '无法成交'
  if (r.return_pct === null || r.return_pct === undefined) return '已结算'
  return `${r.return_pct > 0 ? '+' : ''}${r.return_pct.toFixed(2)}%`
})

/** 已结算非 Hold：正收益红、负收益绿（A 股红涨绿跌），其余走默认 tag 色 */
const tagStyle = computed<Record<string, string> | undefined>(() => {
  const r = record.value
  if (r?.status === 'settled' && r.signal !== 'Hold' && r.return_pct != null) {
    if (r.return_pct > 0) return { color: '#e53935', borderColor: '#e53935' }
    if (r.return_pct < 0) return { color: '#16a34a', borderColor: '#16a34a' }
  }
  return undefined
})

function dateText(d: string | null): string {
  return d ? d : '—'
}

function numText(v: number | null): string {
  return v === null ? '—' : v.toFixed(2)
}
</script>
