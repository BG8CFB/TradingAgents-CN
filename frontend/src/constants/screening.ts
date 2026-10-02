// 策略选股/每日推荐共享的因子与信号中文映射。
// FACTOR_LABELS 键集与后端 app/data/schema/domains/factor_scores.py 的
// FACTOR_FIELDS 对齐（19 因子），后端增删因子时需同步此表。

export const FACTOR_LABELS: Record<string, string> = {
  // 动量
  ret_5d: '5日涨幅%',
  ret_20d: '20日涨幅%',
  ret_60d: '60日涨幅%',
  dist_to_60d_high: '距60日高点%',
  // 趋势
  bias_ma20: 'MA20乖离率%',
  ma20_slope: 'MA20斜率%',
  macd_golden_days: 'MACD金叉天数',
  // 量能
  turnover_amp: '量能放大倍数',
  consecutive_vol_up_days: '连续放量天数',
  volume_ratio: '量比',
  // 资金
  main_inflow_5d: '5日主力净流入(元)',
  main_inflow_5d_pct: '5日主力净流入占比%',
  // 估值
  pe_ttm_percentile: 'PE历史分位',
  pb_percentile: 'PB历史分位',
  dividend_yield: '股息率%',
  // 质量
  roe: 'ROE%',
  gross_margin: '毛利率%',
  net_profit_yoy: '净利同比%',
  debt_ratio: '资产负债率%'
}

export const OP_LABELS: Record<string, string> = {
  '>': '高于',
  '<': '低于',
  '>=': '不低于',
  '<=': '不高于',
  between: '介于',
  '==': '等于',
  '!=': '不等于'
}

/** 结构化入选信号（后端 strategy/daily 响应的 signal_items） */
export interface SignalItem {
  field: string
  op: string
  value: number | [number, number]
}

const factorLabel = (field: string): string => FACTOR_LABELS[field] || field
const opLabel = (op: string): string => OP_LABELS[op] || op

const formatValue = (value: number | [number, number]): string =>
  Array.isArray(value) ? `${value[0]} ~ ${value[1]}` : String(value)

/** 单条结构化信号 → 中文，如「ROE% 高于 15」「PE历史分位 介于 0 ~ 30」 */
const formatItem = (item: SignalItem): string =>
  `${factorLabel(item.field)} ${opLabel(item.op)} ${formatValue(item.value)}`

/** 英文串 value 段解析：number 或 [a, b]；不匹配返回 null */
const parseRawValue = (s: string): number | [number, number] | null => {
  const range = s.match(/^\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]$/)
  if (range) return [Number(range[1]), Number(range[2])]
  const n = Number(s)
  return Number.isFinite(n) ? n : null
}

/**
 * 单条英文信号串（`field op value`）→ 中文；解析失败原样返回。
 * 兼容旧版后端只返回 signals 英文数组、无 signal_items 的过渡期。
 */
const parseRawSignal = (raw: string): string => {
  // 长操作符在前，避免 `>=` 被 `>` 抢先匹配
  const m = raw.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(>=|<=|between|==|!=|>|<)\s*(.+?)\s*$/)
  if (!m) return raw
  const value = parseRawValue(m[3])
  if (value === null) return raw
  return `${factorLabel(m[1])} ${opLabel(m[2])} ${formatValue(value)}`
}

/**
 * 入选信号中文化：优先消费结构化 signal_items；无 items 时回退
 * 正则解析英文 signals 数组。多条以「；」分隔，均缺失返回空串。
 */
export function formatSignal(items?: SignalItem[] | null, raws?: string[] | null): string {
  if (items && items.length) return items.map(formatItem).join('；')
  if (raws && raws.length) return raws.map(parseRawSignal).join('；')
  return ''
}

/** 组件侧便捷入口，等价 formatSignal（表格/展开行直接调用） */
export function formatSignals(items?: SignalItem[] | null, raws?: string[] | null): string {
  return formatSignal(items, raws)
}
