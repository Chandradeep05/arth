/**
 * Application Constants
 * Central configuration for the ARTH platform
 */

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export const WS_BASE_URL =
  process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000';

/** Market indices tracked by the dashboard */
export const MARKET_INDICES = [
  { symbol: '^NSEI', name: 'NIFTY 50', exchange: 'NSE' },
  { symbol: '^BSESN', name: 'SENSEX', exchange: 'BSE' },
  { symbol: '^GSPC', name: 'S&P 500', exchange: 'NYSE' },
  { symbol: '^IXIC', name: 'NASDAQ', exchange: 'NASDAQ' },
] as const;

/** Data freshness configuration */
export const DATA_DELAY_MS = 15_000;
export const DATA_DELAY_LABEL = '~15s delayed';

/** Auto-refresh intervals in milliseconds */
export const REFRESH_INTERVALS = {
  tick: 15_000,         // Price tick data
  indicators: 60_000,  // Technical indicators
  sentiment: 300_000,  // Sentiment scores
  research: 3_600_000, // Research reports
  fundamentals: 86_400_000, // Fundamental data (daily)
} as const;

/** Risk scoring thresholds */
export const RISK_THRESHOLDS = {
  low: { min: 0, max: 25 },
  medium: { min: 25, max: 50 },
  high: { min: 50, max: 75 },
  critical: { min: 75, max: 100 },
} as const;

/** Confidence scoring thresholds */
export const CONFIDENCE_THRESHOLDS = {
  low: { min: 0, max: 40, color: 'var(--red)', label: 'Low' },
  moderate: { min: 40, max: 60, color: 'var(--accent-orange)', label: 'Moderate' },
  good: { min: 60, max: 80, color: 'var(--gold)', label: 'Good' },
  high: { min: 80, max: 100, color: 'var(--accent-green)', label: 'High' },
} as const;

/** Navigation items for the sidebar */
export const NAV_ITEMS = [
  { href: '/', label: 'Dashboard', icon: 'LayoutDashboard' },
  { href: '/markets', label: 'Markets', icon: 'TrendingUp' },
  { href: '/research', label: 'Research', icon: 'FileText' },
  { href: '/risk', label: 'Risk', icon: 'ShieldAlert' },
  { href: '/assistant', label: 'Assistant', icon: 'Bot' },
  { href: '/system', label: 'System', icon: 'Activity' },
] as const;

/** AI Disclaimer text (non-dismissible) */
export const AI_DISCLAIMER =
  '⚠ This is AI-generated analysis for informational purposes only. This is NOT financial advice. All data is delayed ~15s. Always consult a qualified financial advisor.';

/** Market hours (IST for Indian markets) */
export const MARKET_HOURS = {
  NSE: { open: { hour: 9, minute: 15 }, close: { hour: 15, minute: 30 }, timezone: 'Asia/Kolkata' },
  BSE: { open: { hour: 9, minute: 15 }, close: { hour: 15, minute: 30 }, timezone: 'Asia/Kolkata' },
  NYSE: { open: { hour: 9, minute: 30 }, close: { hour: 16, minute: 0 }, timezone: 'America/New_York' },
  NASDAQ: { open: { hour: 9, minute: 30 }, close: { hour: 16, minute: 0 }, timezone: 'America/New_York' },
} as const;
