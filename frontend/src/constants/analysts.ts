/**
 * 分析师配置常量
 */

// 规范化分析师标识符（确保返回英文ID或 slug 简化 ID）
export const normalizeAnalystId = (input: string): string => {
  if (typeof input !== 'string') return ''
  const trimmed = input.trim()
  // 如果是完整的 slug 格式（如 "market-analyst"），转换为简短 ID
  if (trimmed.endsWith('-analyst')) {
    return trimmed.replace('-analyst', '').replace(/-/g, '_')
  }
  return trimmed
}

// 规范化分析师列表（确保所有元素都是英文ID，并去重）
export const normalizeAnalystIds = (inputs: string[]): string[] => {
  const normalized = inputs.map(normalizeAnalystId).filter(Boolean)
  // 使用 Set 去重，保持原始顺序
  return [...new Set(normalized)]
}
