
export interface PhaseConfig {
  id: number
  name: string
  title: string
  description: string
  agents: string[]
  defaultRounds: number
  minRounds: number
  maxRounds: number
  estimatedTimePerRound: number  // 分钟
}

export const PHASES: PhaseConfig[] = [
  {
    id: 2,
    name: 'phase2',
    title: '第二阶段 - 双向辩论与裁决',
    description: '看涨分析师与看跌分析师进行对抗性辩论，最后由研究部主管进行最终裁决',
    agents: ['看涨分析师', '看跌分析师', '研究部主管'],
    defaultRounds: 2,
    minRounds: 1,
    maxRounds: 5,
    estimatedTimePerRound: 3
  },
  {
    id: 3,
    name: 'phase3',
    title: '第三阶段 - 风险管理与对冲',
    description: '保守/中性/激进三类风险分析师与风险经理协同评估，制定风控方案',
    agents: ['保守风险分析师', '中性风险分析师', '激进风险分析师', '风险经理'],
    defaultRounds: 1,
    minRounds: 0,
    maxRounds: 3,
    estimatedTimePerRound: 3
  },
  {
    id: 4,
    name: 'phase4',
    title: '第四阶段 - 交易执行与总结',
    description: '综合研究裁决与风控建议，由专业交易员制定执行计划，并生成最终总结',
    agents: ['专业交易员', '总结智能体'],
    defaultRounds: 1,
    minRounds: 0,
    maxRounds: 1,
    estimatedTimePerRound: 2
  }
]

// 估算总耗时（分钟）
export function estimateTotalTime(phases: Record<string, { enabled: boolean, debateRounds: number }>): number {
  let total = 5  // 第一阶段基础时间
  
  PHASES.forEach(phase => {
    const phaseKey = phase.name as keyof typeof phases
    if (phases[phaseKey]?.enabled) {
      total += phase.estimatedTimePerRound * phases[phaseKey].debateRounds
    }
  })
  
  return total
}
