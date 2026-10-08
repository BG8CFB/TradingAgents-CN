import type { DailyResp, DailyStrategyEntry } from '../api/screening'

export interface DailyNotice {
  title: string
  description: string
  type: 'info' | 'warning'
}

/** Validate the response boundary; malformed responses are errors, not empty results. */
export function parseDailyResponse(response: unknown): DailyResp {
  if (!response || typeof response !== 'object') throw new Error('推荐接口返回格式异常')
  const envelope = response as Record<string, unknown>
  if (envelope.success === false) throw new Error('推荐接口返回失败，请稍后重试')
  const value = 'data' in envelope ? envelope.data : envelope
  if (!value || typeof value !== 'object') throw new Error('推荐接口返回格式异常')
  const data = value as Record<string, unknown>
  if (!Array.isArray(data.strategies) || data.strategies.some(entry =>
    !entry || typeof entry !== 'object' || typeof entry.strategy_id !== 'string' ||
    !Array.isArray(entry.items)
  )) throw new Error('推荐接口返回格式异常')
  return data as unknown as DailyResp
}

export function dailyEmptyNotice(data: DailyResp): DailyNotice {
  if (data.status === 'no_factor_data') {
    return {
      title: '暂无可用因子数据', type: 'warning',
      description: '推荐所需的因子数据尚未就绪。请在数据中心检查行情、财务与资金流同步及因子计算状态。'
    }
  }
  if (data.status === 'not_generated') {
    return {
      title: '推荐尚未生成', type: 'info',
      description: '已有因子数据，但尚无对应推荐结果。这不表示没有股票符合条件；请检查推荐生成任务是否启用及执行成功。'
    }
  }
  return {
    title: '暂无可展示的推荐结果', type: 'info',
    description: '接口未提供明确的空结果原因，无法判断是尚未生成还是没有匹配股票。请检查推荐任务及数据状态。'
  }
}

export function dailyFreshnessNotice(data: DailyResp): DailyNotice | null {
  if (data.recommendation_needs_refresh === true) {
    return {
      title: '推荐结果待重新生成', type: 'warning',
      description: '当前因子批次已变化，以下仍是旧批次的推荐结果。请检查推荐生成任务；刷新页面仅重新查询，不会重新计算推荐。'
    }
  }
  if (data.is_stale === true) {
    const asOf = data.trade_date || data.factor_trade_date
    if (asOf && data.expected_trade_date && asOf > data.expected_trade_date) {
      return {
        title: '推荐数据日期异常', type: 'warning',
        description: `数据日期 ${asOf} 晚于已完成交易日 ${data.expected_trade_date}，不能视为有效的当前推荐。请检查数据日期与因子计算。`
      }
    }
    return {
      title: '推荐数据已过期', type: 'warning',
      description: `当前可用数据早于应有交易日${data.expected_trade_date ? `（${data.expected_trade_date}）` : ''}，不能视为当前交易日推荐。请检查数据同步及推荐生成任务。`
    }
  }
  if (data.is_stale !== false) {
    return {
      title: '数据时效未确认', type: 'info',
      description: '接口尚未提供完整的交易日校验信息；不能仅凭生成时间判断行情与因子是最新的。'
    }
  }
  return null
}

/** A zero count means no match only when the evaluated universe is complete. */
export function strategyEmptyText(entry: DailyStrategyEntry): string {
  if (entry.data_quality?.status === 'complete') return '本策略已完成筛选，没有符合条件的股票。'
  if (entry.data_quality?.status === 'partial') return '已覆盖的数据中暂无匹配股票；部分数据缺失，不能代表完整股票池的筛选结果。'
  if (entry.data_quality?.status === 'insufficient') return '本策略所需数据不足，暂时无法给出可靠的筛选结果。'
  return '暂无入选股票；数据覆盖情况未知，不能判断是零匹配还是数据不足。'
}
