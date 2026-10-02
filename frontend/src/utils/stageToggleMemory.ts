/**
 * 阶段开关记忆（localStorage，按用户 × 工作流 slug 隔离）：
 * 记住用户在分析页对各 optional 阶段的开/关与辩论轮次，刷新/再次进入时恢复。
 * 单股/批量两页同 slug 共享（有意设计——同一工作流的偏好一致）。
 * 读取时按当前 spec 的有效 stageId 过滤，免疫工作流编辑后的脏数据。
 */

import { useAuthStore } from '@/stores/auth'

export interface RememberedStageToggle {
  enabled: boolean
  rounds: number
}

function storageKey(): string {
  // 与任务缓存同款用户隔离（useAuthStore().user?.id；未登录回落 guest 桶）
  const userId = useAuthStore().user?.id
  return `workflow_stage_toggles:${userId || 'guest'}`
}

type MemoryShape = Record<string, Record<string, RememberedStageToggle>>

function readAll(): MemoryShape {
  try {
    const raw = localStorage.getItem(storageKey())
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? (parsed as MemoryShape) : {}
  } catch {
    try {
      localStorage.removeItem(storageKey())
    } catch {
      // localStorage 不可用（隐私模式等）时静默降级为无记忆
    }
    return {}
  }
}

/** 读取某工作流的记忆开关（损坏/缺失返回空对象） */
export function loadStageToggles(slug: string): Record<string, RememberedStageToggle> {
  return readAll()[slug] || {}
}

/** 写入某工作流的记忆开关；validStageIds 之外的条目丢弃（防工作流编辑后 stageId 残留膨胀） */
export function saveStageToggles(
  slug: string,
  states: Record<string, RememberedStageToggle>,
  validStageIds: string[],
): void {
  const valid = new Set(validStageIds)
  const all = readAll()
  all[slug] = Object.fromEntries(Object.entries(states).filter(([id]) => valid.has(id)))
  try {
    localStorage.setItem(storageKey(), JSON.stringify(all))
  } catch {
    // 写失败静默（无记忆不影响功能）
  }
}
