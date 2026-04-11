/** 分析深度选项 */
export const AnalysisDepths = [
  { value: 'quick', label: '快速分析', desc: '1-2分钟，基础观点' },
  { value: 'basic', label: '基础分析', desc: '3-5分钟，常规框架' },
  { value: 'standard', label: '标准分析', desc: '5-8分钟，多维度评估' },
  { value: 'deep', label: '深度分析', desc: '10-15分钟，全面研判' },
  { value: 'comprehensive', label: '全面分析', desc: '15-30分钟，全景报告' },
] as const

/** 分析阶段配置 */
export const AnalysisPhases = {
  PHASE1: { key: 'phase1', label: '多分析师研判' },
  PHASE2: { key: 'phase2', label: '多空辩论' },
  PHASE3: { key: 'phase3', label: '风险评估' },
  PHASE4: { key: 'phase4', label: '交易决策' },
} as const
