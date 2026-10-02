<template>
  <div class="node-select-grid">
    <!-- 裁剪校验反馈（validate-run 拒绝时红色提示，提交按钮由父级禁用） -->
    <el-alert
      v-if="(validationErrors || []).length"
      type="error"
      :closable="false"
      show-icon
      class="grid-alert"
      title="当前选择不满足工作流依赖"
    >
      <div v-for="err in validationErrors" :key="err" class="err-line">{{ err }}</div>
    </el-alert>

    <!-- 按 spec 阶段顺序分段 -->
    <div
      v-for="(stage, idx) in spec.stages"
      :key="stage.id"
      class="stage-section"
      :class="{ skipped: isStageSkipped(stage) }"
    >
      <div class="stage-bar">
        <span class="stage-no">{{ idx + 1 }}</span>
        <span class="stage-name">{{ stage.id }}</span>
        <el-tag size="small" effect="plain">{{ MODE_LABEL[stage.mode] || stage.mode }}</el-tag>
        <el-tag v-if="isStageSkipped(stage)" size="small" type="info" effect="plain">已跳过</el-tag>
      </div>

      <!-- 并行批：可裁剪成员（勾选态） -->
      <div v-if="stage.mode === 'parallel_batch'" class="node-grid">
        <div
          v-for="node in batchMembers(stage)"
          :key="node.slug"
          class="node-card"
          :class="{ active: selected.includes(node.slug) }"
          @click="toggleNode(node.slug, stage)"
        >
          <div class="node-avatar">
            <el-icon><component :is="resolveIcon(node.icon)" /></el-icon>
          </div>
          <div class="node-content">
            <div class="node-name">{{ node.name }}</div>
            <div class="node-desc">{{ node.description }}</div>
          </div>
          <div class="node-check">
            <el-icon v-if="selected.includes(node.slug)" class="check-icon"><Check /></el-icon>
          </div>
        </div>
        <el-empty
          v-if="!batchMembers(stage).length"
          description="该阶段无可选节点（智能体库为空）"
          :image-size="48"
        />
      </div>

      <!-- 辩论：成员锁定态展示 -->
      <div v-else-if="stage.mode === 'debate'" class="locked-row">
        <el-tooltip
          v-for="slug in [...(stage.sides || []), stage.judge].filter((s): s is string => Boolean(s))"
          :key="slug"
          content="该工作流必选，不可取消"
          placement="top"
        >
          <div class="locked-chip">
            <el-icon class="lock-icon"><Lock /></el-icon>
            <span>{{ displayNames[slug] ?? slug }}</span>
            <el-tag v-if="slug === stage.judge" size="small" type="warning" effect="plain">裁决</el-tag>
          </div>
        </el-tooltip>
      </div>

      <!-- 单智能体：锁定态展示 -->
      <div v-else class="locked-row">
        <el-tooltip v-if="stage.node" content="该工作流必选，不可取消" placement="top">
          <div class="locked-chip">
            <el-icon class="lock-icon"><Lock /></el-icon>
            <span>{{ displayNames[stage.node] ?? spec.nodes.find((n) => n.slug === stage.node)?.node_name ?? stage.node }}</span>
          </div>
        </el-tooltip>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import {
  Check,
  Lock,
  Document,
  TrendCharts,
  Histogram,
  ChatDotRound,
  DataAnalysis,
  Wallet,
  InfoFilled,
} from '@element-plus/icons-vue'
import type { StageSpecDto, WorkflowSpecDto } from '@/api/workflows'

/**
 * 阶段分组节点选择网格（§5.2③）：
 * - parallel_batch 成员 → 勾选可选（承接默认勾选机制，selected 由父级持有）
 * - 辩论 sides/judge、single 节点 → 锁定态（🔒 + tooltip）
 * - optional 阶段开关与轮数由 StageSwitches 承载（父级渲染），本组件只管节点选择
 */

interface BatchNode {
  slug: string
  name: string
  description: string
  icon: string
}

const props = defineProps<{
  spec: WorkflowSpecDto
  selected: string[]
  /** phase1 分析师元数据（pool 批阶段的成员来源），由父级从智能体库拉取 */
  agents: BatchNode[]
  /** slug → 显示名（锁定节点展示；缺省回退 node_name/slug） */
  displayNames?: Record<string, string>
  validationErrors?: string[]
  /** 已被阶段开关跳过的组 id：整组灰显禁点（已勾选保留不清除，裁剪由 stage_overrides 在编译期完成） */
  disabledStageIds?: string[]
}>()

const emit = defineEmits<{
  (e: 'update:selected', slugs: string[]): void
}>()

const MODE_LABEL: Record<string, string> = {
  parallel_batch: '并行批',
  debate: '辩论',
  single: '单智能体',
}

/** 批阶段成员：pool 模式取智能体库 phase1 全集；显式枚举按 NodeRef 顺序取元数据 */
const batchMembers = (stage: StageSpecDto): BatchNode[] => {
  if (stage.pool) return props.agents
  return (stage.nodes || []).map((ref) => {
    const meta = props.agents.find((a) => a.slug === ref.ref)
    const nodeDef = props.spec.nodes.find((n) => n.slug === ref.ref)
    return (
      meta || {
        slug: ref.ref,
        name: nodeDef?.node_name || ref.ref,
        description: '工作流显式枚举节点',
        icon: 'DataAnalysis',
      }
    )
  })
}

const isStageSkipped = (stage: StageSpecDto): boolean => (props.disabledStageIds || []).includes(stage.id)

const toggleNode = (slug: string, stage: StageSpecDto) => {
  // 组被阶段开关跳过时本次不执行，勾选无意义但保留原值（切回开启即恢复）
  if (isStageSkipped(stage)) return
  const next = props.selected.includes(slug)
    ? props.selected.filter((s) => s !== slug)
    : [...props.selected, slug]
  emit('update:selected', next)
}

const getAnalystIcon = (slug: string) => {
  if (slug.includes('news')) return 'Document'
  if (slug.includes('market')) return 'TrendCharts'
  if (slug.includes('social')) return 'ChatDotRound'
  if (slug.includes('fund')) return 'DataAnalysis'
  if (slug.includes('capital')) return 'Wallet'
  return 'Histogram'
}

const resolveIcon = (name: string) => {
  const icons: Record<string, unknown> = {
    Document,
    TrendCharts,
    Histogram,
    ChatDotRound,
    DataAnalysis,
    Wallet,
    InfoFilled,
  }
  return icons[name] || icons[getAnalystIcon(name)] || InfoFilled
}

const displayNames = computed(() => props.displayNames || {})
</script>

<style lang="scss" scoped>
.node-select-grid {
  width: 100%;
}

.grid-alert {
  margin-bottom: 12px;

  .err-line {
    font-size: 12px;
    line-height: 1.8;
  }
}

.stage-section {
  margin-bottom: 16px;

  &.skipped {
    .node-card,
    .locked-chip {
      opacity: 0.45;
    }

    .node-card {
      cursor: not-allowed;
    }
  }
}

.stage-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.stage-no {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background-color: var(--el-color-primary);
  color: #fff;
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stage-name {
  font-size: 13px;
  font-weight: 600;
}

.node-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 10px;
}

.node-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.15s ease;

  &:hover {
    border-color: var(--el-color-primary-light-5);
  }

  &.active {
    border-color: var(--el-color-primary);
    background-color: var(--el-color-primary-light-9);
  }
}

.node-avatar {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background-color: var(--el-fill-color-light);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  color: var(--el-color-primary);
  flex-shrink: 0;
}

.node-content {
  flex: 1;
  min-width: 0;
}

.node-name {
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.node-desc {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.node-check {
  flex-shrink: 0;

  .check-icon {
    color: var(--el-color-primary);
    font-size: 16px;
  }
}

.locked-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.locked-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 8px;
  border: 1px dashed var(--el-border-color);
  background-color: var(--el-fill-color-light);
  font-size: 13px;
  color: var(--el-text-color-regular);

  .lock-icon {
    color: var(--el-text-color-secondary);
    font-size: 12px;
  }
}

@media (max-width: 768px) {
  .node-grid {
    grid-template-columns: 1fr;
  }
}
</style>
