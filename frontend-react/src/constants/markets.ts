/** 市场类型常量 */
export const MarketTypes = {
  CN: 'CN',
  HK: 'HK',
  US: 'US',
} as const

export const MarketList = [
  { value: 'CN', label: 'A股' },
  { value: 'HK', label: '港股' },
  { value: 'US', label: '美股' },
] as const

export const MarketColors = {
  CN: { up: 'var(--accent-error)', down: 'var(--accent-success)' },
  HK: { up: 'var(--accent-success)', down: 'var(--accent-error)' },
  US: { up: 'var(--accent-success)', down: 'var(--accent-error)' },
} as const
