
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
    title: '第二阶段 - 双向辩论与交易计划',
    description: '看涨分析师与看跌分析师进行对抗性辩论，由研究部主管裁决，最后由专业交易员制定交易计划',
    agents: ['看涨分析师', '看跌分析师', '研究部主管', '专业交易员'],
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
    title: '第四阶段 - 最终总结',
    description: '综合所有分析结果，由总结智能体生成最终分析报告',
    agents: ['总结智能体'],
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
