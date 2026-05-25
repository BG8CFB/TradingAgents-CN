/**
 * 模型能力等级与角色判断的工具函数
 * 提取自 DeepModelSelector.vue 和 ModelConfig.vue，避免重复定义
 */

/**
 * 获取能力等级文本
 */
export const getCapabilityText = (level: number): string => {
  const texts: Record<number, string> = {
    1: '⚡基础',
    2: '📊标准',
    3: '🎯高级',
    4: '🔥专业',
    5: '👑旗舰'
  }
  return texts[level] || '📊标准'
}

/**
 * 获取能力等级标签类型
 */
export const getCapabilityTagType = (level: number): 'success' | 'info' | 'warning' | 'danger' => {
  if (level >= 4) return 'danger'
  if (level >= 3) return 'warning'
  if (level >= 2) return 'success'
  return 'info'
}

/**
 * 判断是否适合一阶段分析
 */
export const isAnalystRole = (roles: string[] | undefined): boolean => {
  if (!roles || !Array.isArray(roles)) return false
  return roles.includes('analyst') || roles.includes('both')
}

/**
 * 判断是否适合辩论推理
 */
export const isDebateRole = (roles: string[] | undefined): boolean => {
  if (!roles || !Array.isArray(roles)) return false
  return roles.includes('debate') || roles.includes('both')
}
