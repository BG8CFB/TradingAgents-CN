import { Segmented } from 'antd'
import { MarketList } from '@/constants/markets'

interface MarketSelectorProps {
  value: string
  onChange: (value: string) => void
  disabled?: boolean
}

export default function MarketSelector({ value, onChange, disabled }: MarketSelectorProps) {
  return (
    <Segmented
      value={value}
      onChange={onChange}
      disabled={disabled}
      options={MarketList.map((m) => ({ value: m.value, label: m.label }))}
      block
    />
  )
}
