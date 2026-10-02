<template>
  <aside class="agent-palette" :class="{ disabled }">
    <div class="palette-head">
      <span class="palette-title">智能体库</span>
      <el-input
        v-model="keyword"
        size="small"
        clearable
        placeholder="搜索名称 / slug / 类型"
        :prefix-icon="Search"
      />
    </div>

    <el-scrollbar class="palette-body">
      <!-- 策略模块：拖出到画布建空区域（成员再拖进去）。单智能体无模块——智能体拖空白即自动建组 -->
      <div v-if="draggable" class="palette-group">
        <div class="palette-group-title">策略模块<span class="palette-count">2</span></div>
        <div
          v-for="mod in MODULES"
          :key="mod.mode"
          class="palette-item module-item"
          :title="mod.hint"
          draggable="true"
          @dragstart="onModuleDragStart($event, mod.mode)"
          @click="emit('module-select', mod.mode)"
        >
          <span class="palette-icon">{{ mod.icon }}</span>
          <span class="palette-main">
            <span class="palette-name">{{ mod.label }}</span>
            <span class="palette-slug">{{ mod.hint }}</span>
          </span>
        </div>
      </div>

      <div v-for="group in groups" :key="group.label" class="palette-group">
        <div class="palette-group-title">{{ group.label }}<span class="palette-count">{{ group.items.length }}</span></div>
        <div
          v-for="agent in group.items"
          :key="agent.slug"
          class="palette-item"
          :class="{ used: usedSet.has(agent.slug), 'is-draggable': draggable }"
          :draggable="draggable"
          :title="itemTitle(agent)"
          :data-slug="agent.slug"
          @dragstart="onDragStart($event, agent)"
          @click="onSelect(agent)"
        >
          <span class="palette-icon">{{ KIND_ICONS[agent.kind] || '🤖' }}</span>
          <span class="palette-main">
            <span class="palette-name">{{ agent.name }}</span>
            <span class="palette-slug">{{ agent.slug }}</span>
          </span>
          <span class="palette-meta">
            <el-tag v-if="usedSet.has(agent.slug)" size="small" type="info" effect="plain">已在流</el-tag>
            <el-tag v-else-if="librarySet.has(agent.slug)" size="small" type="info" effect="plain">已入库</el-tag>
            <el-tag v-else size="small" effect="plain">{{ KIND_LABELS[agent.kind] || agent.kind }}</el-tag>
          </span>
        </div>
      </div>
      <el-empty v-if="!groups.length" description="库中无匹配智能体" :image-size="64" />
    </el-scrollbar>

    <div v-if="draggable" class="palette-foot">先拖出策略模块搭区域，再把智能体拖进去；智能体拖到空白处自动建组</div>
    <div v-else class="palette-foot">点击智能体加入节点库</div>
  </aside>
</template>

<script lang="ts">
/** 拖拽 payload 自定义 mime（画布 drop 以此识别智能体拖拽源，不影响其他拖拽） */
export const PALETTE_MIME = 'application/x-ta-agent'
</script>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Search } from '@element-plus/icons-vue'
import type { AgentMeta } from './edgeRules'

/**
 * 侧边智能体库面板（设计文档 §5.3 行业标准交互）：
 * 拖拽（dataTransfer 自定义 mime）到画布落点 / 点击选择（select 事件由父级
 * 决定目标段）；表单视图在 dialog 内以纯点击模式复用（draggable=false）。
 */

const props = withDefaults(
  defineProps<{
    agents: AgentMeta[]
    /** 已进入当前工作流的 slug（画布上可见成员，显示「已在流」标记） */
    usedSlugs?: string[]
    /** 已入节点库但不在画布上的 slug（显示「已入库」灰标，仍可拖入） */
    librarySlugs?: string[]
    disabled?: boolean
    /** 点击模式（dialog 场景）隐藏拖拽提示 */
    draggable?: boolean
  }>(),
  { usedSlugs: () => [], librarySlugs: () => [], disabled: false, draggable: true },
)

const emit = defineEmits<{
  (e: 'select', agent: AgentMeta): void
  (e: 'dragstart', agent: AgentMeta): void
  /** 点击策略模块（画布末尾建空组；拖拽则按落点插入） */
  (e: 'module-select', mode: 'parallel_batch' | 'debate'): void
}>()

/** 策略模块（拖出空区域 → 拖智能体进去；组内行为由模块决定） */
const MODULES = [
  { mode: 'parallel_batch' as const, icon: '⛓', label: '并行模块', hint: '组内智能体同时执行' },
  { mode: 'debate' as const, icon: '⚖️', label: '公平辩论模块', hint: '多智能体轮流辩论 + 裁决收束' },
]

const KIND_ICONS: Record<string, string> = {
  analyst: '📊',
  debater: '🗣',
  judge: '⚖',
  trader: '💰',
  summarizer: '📝',
  terminal: '🏁',
}
const KIND_LABELS: Record<string, string> = {
  analyst: '分析师',
  debater: '辩手',
  judge: '裁决',
  trader: '交易',
  summarizer: '总结',
  terminal: '终端',
}
const GROUP_LABELS: Record<string, string> = {
  debater: '辩手',
  analyst: '分析师',
  judge: '裁决',
  trader: '交易 · 总结',
  summarizer: '交易 · 总结',
  terminal: '交易 · 总结',
}
/** 分组展示顺序（辩手在前：辩论是搭建频次最高的策略） */
const GROUP_ORDER = ['辩手', '分析师', '裁决', '交易 · 总结', '其他']

const keyword = ref('')
const usedSet = computed(() => new Set(props.usedSlugs))
const librarySet = computed(() => new Set(props.librarySlugs))

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return props.agents
  return props.agents.filter(
    (a) =>
      a.name.toLowerCase().includes(kw) ||
      a.slug.toLowerCase().includes(kw) ||
      (KIND_LABELS[a.kind] || a.kind).toLowerCase().includes(kw),
  )
})

/** 按智能体类型分组（不按 phase——用户任意组合策略，不被旧阶段框架束缚） */
const groups = computed(() => {
  const byLabel = new Map<string, AgentMeta[]>()
  for (const a of filtered.value) {
    const label = GROUP_LABELS[a.kind] || '其他'
    if (byLabel.has(label)) byLabel.get(label)!.push(a)
    else byLabel.set(label, [a])
  }
  return [...byLabel.entries()]
    .sort((x, y) => GROUP_ORDER.indexOf(x[0]) - GROUP_ORDER.indexOf(y[0]))
    .map(([label, items]) => ({ label, items }))
})

function itemTitle(agent: AgentMeta): string {
  const keys = agent.report_keys.length ? agent.report_keys.join('、') : '无报告键'
  return `${agent.slug} · ${KIND_LABELS[agent.kind] || agent.kind} · 报告键: ${keys}`
}

function onDragStart(event: DragEvent, agent: AgentMeta) {
  if (props.disabled || !event.dataTransfer) return
  event.dataTransfer.setData(PALETTE_MIME, JSON.stringify({ slug: agent.slug }))
  event.dataTransfer.setData('text/plain', agent.slug)
  event.dataTransfer.effectAllowed = 'copy'
  emit('dragstart', agent)
}

function onSelect(agent: AgentMeta) {
  if (props.disabled) return
  emit('select', agent)
}

function onModuleDragStart(event: DragEvent, mode: 'parallel_batch' | 'debate') {
  if (props.disabled || !event.dataTransfer) return
  event.dataTransfer.setData(PALETTE_MIME, JSON.stringify({ module: mode }))
  event.dataTransfer.setData('text/plain', mode)
  event.dataTransfer.effectAllowed = 'copy'
}
</script>

<style lang="scss" scoped>
.agent-palette {
  display: flex;
  flex-direction: column;
  width: 240px;
  flex-shrink: 0;
  height: 100%;
  border-right: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
  overflow: hidden;

  &.disabled {
    opacity: 0.55;
    pointer-events: none;
  }
}

.palette-head {
  padding: 8px 10px 6px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.palette-title {
  display: block;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 6px;
}

.palette-body {
  flex: 1;
}

.palette-group {
  padding: 6px 6px 2px;
}

.palette-group-title {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  padding: 2px 6px 4px;
  display: flex;
  justify-content: space-between;
}

.palette-count {
  font-variant-numeric: tabular-nums;
}

.palette-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  cursor: pointer;
  border: 1px solid transparent;

  &.is-draggable {
    cursor: grab;
  }

  &:hover {
    background: var(--el-fill-color-light);
  }

  &.used {
    background: var(--el-fill-color);
  }

  &.module-item {
    cursor: grab;
    border: 1px dashed var(--el-border-color);
    background: var(--el-color-primary-light-9);

    &:hover {
      border-color: var(--el-color-primary-light-5);
    }
  }
}

.palette-icon {
  font-size: 16px;
  flex-shrink: 0;
}

.palette-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.palette-name {
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.palette-slug {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.palette-meta {
  flex-shrink: 0;
}

.palette-foot {
  padding: 6px 10px;
  font-size: 11px;
  color: var(--el-text-color-secondary);
  border-top: 1px solid var(--el-border-color-lighter);
  line-height: 1.5;
}
</style>
