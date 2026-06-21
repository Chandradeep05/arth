/**
 * Application Constants
 * Central configuration for the ARTH platform
 */

// In production, use relative URLs so requests go through Next.js rewrites
// (same-origin, no CORS). In dev, hit the backend directly.
export const API_BASE_URL =
  typeof window !== 'undefined' && window.location.hostname !== 'localhost'
    ? ''  // Production: relative URL → Next.js rewrites → backend
    : (process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000');

// SSE/streaming endpoints bypass Next.js rewrites (Vercel may buffer SSE responses).
// In production, connect directly to the Render backend URL.
// In dev, use localhost (no rewrite needed for direct connections).
export const STREAMING_API_URL =
  process.env.NEXT_PUBLIC_API_URL
    ? (process.env.NEXT_PUBLIC_API_URL.startsWith('http') ? process.env.NEXT_PUBLIC_API_URL : `https://${process.env.NEXT_PUBLIC_API_URL}`)
    : (typeof window !== 'undefined' && window.location.hostname !== 'localhost'
        ? ''  // Fallback: use rewrite if no env var set
        : 'http://localhost:8000');

// WebSocket URL: ONLY enabled when explicitly configured via NEXT_PUBLIC_WS_URL.
// Render free tier doesn't support persistent WebSocket connections — they get
// rejected with 403 by Starlette's CORSMiddleware. HTTP polling handles real-time data.
export const WS_BASE_URL = (() => {
  // Explicit WS URL configured — use it
  if (process.env.NEXT_PUBLIC_WS_URL) return process.env.NEXT_PUBLIC_WS_URL;
  // Local development — connect to local backend
  if (typeof window !== 'undefined' && window.location.hostname === 'localhost') {
    return 'ws://localhost:8000';
  }
  // Production without explicit WS config — disabled
  return '';
})();

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
  tick: 60_000,         // Price tick data (was 15s — too aggressive for free tier)
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
  { href: '/financials', label: 'Financials', icon: 'BarChart3' },
  { href: '/risk', label: 'Risk', icon: 'ShieldAlert' },
  { href: '/watchlist', label: 'Watchlist', icon: 'Star' },
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

/** WebSocket configuration */
export const WS_RECONNECT_MAX_DELAY = 30_000;
export const WS_RECONNECT_BASE_DELAY = 1_000;
export const WS_PRICE_UPDATE_INTERVAL = 5_000;
export const WS_MAX_SYMBOLS = 10;
