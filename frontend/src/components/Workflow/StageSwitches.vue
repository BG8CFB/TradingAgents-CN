<template>
  <div class="stage-switches">
    <div
      v-for="(stage, idx) in specStages"
      :key="stage.id"
      class="stage-card"
      :class="{ enabled: states[stage.id]?.enabled, locked: !stage.optional }"
    >
      <div class="stage-head">
        <div class="stage-title">
          <span class="stage-no">{{ idx + 1 }}</span>
          {{ stageLabel(stage) }}
          <el-tag v-if="hasTerminalMember(stage)" size="small" type="warning" effect="plain">含终点</el-tag>
        </div>
        <el-tooltip v-if="!stage.optional" :content="lockReason(stage)" placement="top">
          <span class="stage-lock" :aria-label="lockReason(stage)">🔒</span>
        </el-tooltip>
        <el-switch
          :model-value="stage.optional ? states[stage.id]?.enabled : false"
          :disabled="!stage.optional"
          :aria-label="`开关阶段 ${stage.id}`"
          @update:model-value="(v) => toggle(stage.id, v)"
        />
      </div>
      <div class="stage-desc">{{ stageDesc(stage) }}</div>
      <div v-if="stage.mode === 'debate' && states[stage.id]?.enabled" class="stage-rounds">
        <span class="label">辩论轮次:</span>
        <el-input-number
          :model-value="states[stage.id]?.rounds ?? stage.rounds ?? 1"
          :min="0"
          :max="10"
          size="small"
          controls-position="right"
          @update:model-value="(v) => setRounds(stage.id, v)"
        />
        <span class="rounds-hint">总发言轮 = 轮次 + 1</span>
      </div>
    </div>
    <el-alert
      class="stage-behavior-note"
      type="info"
      :closable="false"
      title="跳过行为说明"
      description="跳过的组不产生任何报告（报告页不会出现该组内容）；下游引用该组产出时自动降级（如缺少研究辩论裁决时，交易员输入显示「暂无研究部主管裁决」）；必需输入缺失会被提交前校验拦截。并行批中取消勾选某智能体 = 本次分析不运行该智能体。"
    />
  </div>
</template>

<script setup lang="ts">
import type { NodeSpecDto, StageSpecDto } from '@/api/workflows'

/** spec 驱动的阶段开关（承接旧 phase2/3 交互；阶段元数据不再硬编码）：
 * 全部阶段列表——optional 可开关；非 optional 灰显锁定并给出原因；
 * states 只持有 optional 阶段条目（非 optional 永不发 enabled:false，防后端编译拒绝）。 */

export interface StageState {
  enabled: boolean
  rounds: number
}

const props = defineProps<{
  specStages: StageSpecDto[]
  states: Record<string, StageState>
  /** 节点定义（终点检测：含 terminal 成员的组锁定原因/跳过警示） */
  specNodes?: NodeSpecDto[]
}>()

const emit = defineEmits<{
  (e: 'update:states', states: Record<string, StageState>): void
}>()

const MODE_LABEL: Record<string, string> = {
  parallel_batch: '并行批',
  debate: '辩论',
  single: '单智能体',
}

const stageLabel = (stage: StageSpecDto) =>
  stage.id === 'research_debate'
    ? '研究辩论（多空对抗）'
    : stage.id === 'risk_debate'
      ? '风险管理辩论'
      : `${stage.id}（${MODE_LABEL[stage.mode] || stage.mode}）`

/** 组成员 slug（终点检测用；pool 动态成员不含 terminal 节点，跳过不误判） */
const memberSlugsOf = (stage: StageSpecDto): string[] => {
  if (stage.mode === 'debate') {
    return [...(stage.sides || []), stage.judge].filter((s): s is string => Boolean(s))
  }
  if (stage.mode === 'single' && stage.node) return [stage.node]
  return (stage.nodes || []).map((n) => n.ref)
}

const hasTerminalMember = (stage: StageSpecDto) =>
  memberSlugsOf(stage).some((slug) => props.specNodes?.find((n) => n.slug === slug)?.terminal === true)

const lockReason = (stage: StageSpecDto): string => {
  const stageIndex = props.specStages.findIndex((s) => s.id === stage.id)
  if (stageIndex === 0) return '起点组：为下游提供基础产出，不可跳过'
  if (hasTerminalMember(stage)) return '含终点节点（最终决策写入者），不可跳过'
  return '工作流编辑器未将该组标记为可选（可在编辑器组属性中开启）'
}

const stageDesc = (stage: StageSpecDto) => {
  if (stage.mode === 'debate') {
    const members = memberSlugsOf(stage).join('、')
    const base = `辩手 ${members || '（待补）'} 轮次公平发言后裁决；关闭则跳过该阶段`
    return hasTerminalMember(stage) ? `${base}；跳过后最终报告将缺少该组决策字段` : base
  }
  if (!stage.optional) return '固定执行阶段'
  return '可选阶段：关闭后本次分析跳过'
}

const patch = (stageId: string, update: Partial<StageState>) => {
  const base = props.states[stageId] || { enabled: false, rounds: 1 }
  emit('update:states', { ...props.states, [stageId]: { ...base, ...update } })
}

const toggle = (stageId: string, on: string | number | boolean) => {
  patch(stageId, { enabled: on === true })
}

const setRounds = (stageId: string, v: number | undefined) => {
  patch(stageId, { rounds: typeof v === 'number' ? v : 1 })
}
</script>

<style lang="scss" scoped>
.stage-switches {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}

.stage-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  padding: 12px 14px;
  transition: border-color 0.15s ease;

  &.enabled {
    border-color: var(--el-color-success-light-5);
    background-color: var(--el-color-success-light-9);
  }

  &.locked {
    opacity: 0.62;
  }
}

.stage-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.stage-title {
  font-size: 14px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex-wrap: wrap;
}

.stage-no {
  flex-shrink: 0;
  min-width: 18px;
  height: 18px;
  line-height: 18px;
  text-align: center;
  border-radius: 9px;
  font-size: 11px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color);
}

.stage-lock {
  flex-shrink: 0;
  font-size: 12px;
  cursor: help;
}

.stage-desc {
  margin-top: 6px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.6;
  word-break: break-all;
}

.stage-rounds {
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 8px;

  .label {
    font-size: 13px;
  }
}

.rounds-hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.stage-behavior-note {
  grid-column: 1 / -1;
}

@media (max-width: 768px) {
  .stage-switches {
    grid-template-columns: 1fr;
  }
}
</style>
