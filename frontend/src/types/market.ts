/**
 * Market Data Type Definitions
 * Matches backend Pydantic schemas exactly (snake_case from API)
 */

export interface FreshnessMetadata {
  source: string;
  timestamp: string;
  is_stale: boolean;
  delay_label: string;
  cache_hit: boolean;
}

export interface StockQuote {
  symbol: string;
  name: string;
  price: number;
  change: number;
  change_percent: number;
  volume: number;
  high: number;
  low: number;
  open: number;
  previous_close: number;
  market_cap: number | null;
  pe_ratio: number | null;
  timestamp: string;
  exchange: string;
  market: string;
  currency: string;
}

export interface OHLCVBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  adj_close: number | null;
}

export interface MarketIndex {
  symbol: string;
  name: string;
  value: number;
  change: number;
  change_percent: number;
  timestamp: string;
}

export interface SectorPerformance {
  sector: string;
  change_percent: number;
  top_gainer: string | null;
  top_loser: string | null;
  volume: number | null;
}

export interface StockMover {
  symbol: string;
  name: string;
  price: number;
  change: number;
  change_percent: number;
  volume: number;
}

export interface SearchResult {
  symbol: string;
  name: string;
  exchange: string;
  market: string;
  sector: string | null;
}

export interface TechnicalIndicators {
  symbol: string;
  timestamp: string;
  rsi_14: number | null;
  macd: { value: number; signal: number; histogram: number } | null;
  bollinger_bands: { upper: number; middle: number; lower: number } | null;
  vwap: number | null;
  sma_20: number | null;
  sma_50: number | null;
  rsi_signal: string | null;
  macd_signal_type: string | null;
  bb_position: string | null;
}

/* ── API Response Wrappers ── */

export interface APIResponse<T> {
  success: boolean;
  data: T;
  freshness: FreshnessMetadata;
  trace_id: string | null;
}

export interface MarketOverviewResponse {
  success: boolean;
  indices: MarketIndex[];
  freshness: FreshnessMetadata;
}

export interface TopMoversResponse {
  success: boolean;
  gainers: StockMover[];
  losers: StockMover[];
  freshness: FreshnessMetadata;
}
