/** 股票实时行情 */
export interface StockQuote {
  code: string
  name?: string
  market?: string
  price?: number
  change_percent?: number
  amount?: number
  volume?: number
  open?: number
  high?: number
  low?: number
  prev_close?: number
  turnover_rate?: number
  amplitude?: number
  trade_date?: string
  updated_at?: string
}

/** 基本面数据 */
export interface StockFundamentals {
  code: string
  name?: string
  industry?: string
  market?: string
  sector?: string
  pe?: number
  pb?: number
  pe_ttm?: number
  pb_mrq?: number
  ps?: number
  ps_ttm?: number
  roe?: number
  debt_ratio?: number
  total_mv?: number
  circ_mv?: number
  turnover_rate?: number
  volume_ratio?: number
  pe_source?: string
  pe_is_realtime?: boolean
  pe_updated_at?: string
  mv_is_realtime?: boolean
  updated_at?: string
}

/** K线数据项 */
export interface KlineItem {
  time: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  amount?: number
}

/** K线响应 */
export interface KlineData {
  code: string
  period: string
  limit: number
  adj: string
  source?: string
  items: KlineItem[]
}

/** 新闻项 */
export interface NewsItem {
  title: string
  source?: string
  time?: string
  url?: string
  type?: string
  content?: string
  summary?: string
}

/** 新闻响应 */
export interface StockNews {
  code: string
  days: number
  limit: number
  source?: string
  items: NewsItem[]
}

/** 股票基础信息 */
export interface StockBasicInfo {
  symbol: string
  name: string
  market?: string
  industry?: string
  sector?: string
  list_date?: string
  total_mv?: number
  circ_mv?: number
  pe?: number
  pb?: number
  turnover_rate?: number
  updated_at?: string
}

/** 市场行情数据 */
export interface MarketQuotes {
  symbol: string
  close?: number
  open?: number
  high?: number
  low?: number
  pct_chg?: number
  volume?: number
  amount?: number
  turnover_rate?: number
  trade_date?: string
  updated_at?: string
}

/** 股票列表项 */
export interface StockListItem {
  symbol: string
  name: string
  market?: string
  industry?: string
  pe?: number
  pb?: number
  total_mv?: number
  close?: number
  pct_chg?: number
}

/** 综合股票数据 */
export interface CombinedStockData {
  symbol: string
  timestamp?: string
  basic_info?: StockBasicInfo | null
  quotes?: MarketQuotes | null
}

/** 搜索结果 */
export interface SearchStockResult {
  symbol: string
  name: string
  market?: string
  industry?: string
}

/** 市场统计 */
export interface MarketSummary {
  total_stocks: number
  market_breakdown: Array<{ _id: string; count: number }>
  supported_markets: string[]
  last_updated?: string
}

/** 行情同步状态 */
export interface QuotesSyncStatus {
  last_sync_time?: string
  last_sync_time_iso?: string
  interval_seconds?: number
  interval_minutes?: number
  data_source?: string
  success?: boolean
  records_count?: number
  error_message?: string | null
}

/** 市场信息 */
export interface MarketInfo {
  code: string
  name: string
  name_en?: string
  currency?: string
  timezone?: string
  trading_hours?: string
}

/** 多市场股票信息 */
export interface MultiMarketStockInfo {
  code: string
  name: string
  name_en?: string
  market: string
  source?: string
  total_mv?: number
  pe?: number
  pb?: number
  lot_size?: number
  currency?: string
}

/** 多市场实时行情 */
export interface MultiMarketQuote {
  code: string
  close?: number
  pct_chg?: number
  open?: number
  high?: number
  low?: number
  volume?: number
  amount?: number
  trade_date?: string
  currency?: string
}
