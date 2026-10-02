<template>
  <div v-if="plan" class="run-plan">
    <span class="rp-summary">
      将执行 <strong>{{ plan.stages.length }}</strong> 组 · <strong>{{ plan.total_units }}</strong> 个执行单元
    </span>
    <template v-if="skipped.length">
      <span class="rp-skips">
        <el-tag v-for="s in skipped" :key="s.id" size="small" type="warning" effect="plain">跳过 · {{ stageLabel(s) }}</el-tag>
      </span>
      <span class="rp-note">被跳过的组不产出报告，下游引用处自动降级；必需输入缺失会被校验拦截</span>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { StageSpecDto, ValidateRunResult } from '@/api/workflows'

/** validate-run 执行计划摘要：展示裁剪后的实际执行规模与被跳过的组。
 * 跳过 = 编译期裁剪（不在 plan.stages 中），确定性推导，无需连线解析。 */

const props = defineProps<{
  plan?: ValidateRunResult['plan']
  specStages: StageSpecDto[]
}>()

const skipped = computed(() =>
  props.specStages.filter((s) => !props.plan?.stages.some((p) => p.stage_id === s.id)),
)

const MODE_LABEL: Record<string, string> = {
  parallel_batch: '并行批',
  debate: '辩论',
  single: '单智能体',
}

const stageLabel = (stage: StageSpecDto) =>
  stage.id === 'research_debate'
    ? '研究辩论'
    : stage.id === 'risk_debate'
      ? '风险管理辩论'
      : `${stage.id}（${MODE_LABEL[stage.mode] || stage.mode}）`
</script>

<style lang="scss" scoped>
.run-plan {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 12px;
  border: 1px dashed var(--el-border-color-lighter);
  border-radius: 8px;
  font-size: 12px;
  color: var(--el-text-color-regular);
}

.rp-summary {
  flex-shrink: 0;
}

.rp-skips {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 4px;
}

.rp-note {
  color: var(--el-text-color-secondary);
  font-size: 11px;
}
</style>
