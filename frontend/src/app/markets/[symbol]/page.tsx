'use client';

import { useState, useEffect, useCallback } from 'react';
import { useParams } from 'next/navigation';
import { motion } from 'framer-motion';
import {
  TrendingUp,
  TrendingDown,
  Building2,
  Globe,
  ArrowLeft,
  RefreshCw,
} from 'lucide-react';
import Link from 'next/link';
import { apiClient } from '@/lib/api';
import { REFRESH_INTERVALS } from '@/lib/constants';
import PriceChart from '@/components/charts/PriceChart';
import TechnicalPanel from '@/components/stock/TechnicalPanel';
import ResearchReport from '@/components/stock/ResearchReport';
import SentimentGauge from '@/components/stock/SentimentGauge';
import RiskScore from '@/components/stock/RiskScore';
import DataFreshness from '@/components/shared/DataFreshness';
import Disclaimer from '@/components/shared/Disclaimer';
import LoadingSkeleton from '@/components/shared/LoadingSkeleton';
import PredictionPanel from '@/components/stock/PredictionPanel';
import type { StockQuote, OHLCVBar, TechnicalIndicators } from '@/types/market';

function formatNumber(n: number | null | undefined): string {
  if (n == null || isNaN(n)) return '—';
  return new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(n);
}

function formatMarketCap(n: number | null, currencySymbol = '$'): string {
  if (!n) return 'N/A';
  if (n >= 1e12) return `${currencySymbol}${(n / 1e12).toFixed(2)}T`;
  if (n >= 1e9) return `${currencySymbol}${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e7) return `${currencySymbol}${(n / 1e7).toFixed(2)}Cr`;
  return `${currencySymbol}${formatNumber(n)}`;
}

export default function StockDetailPage() {
  const params = useParams();
  // Dynamic route [symbol]: params.symbol is a string
  const rawSymbol = Array.isArray(params.symbol)
    ? params.symbol[0]
    : (params.symbol as string);
  const symbol = decodeURIComponent(rawSymbol);

  const [quote, setQuote] = useState<StockQuote | null>(null);
  const [ohlcv, setOhlcv] = useState<OHLCVBar[]>([]);
  const [indicators, setIndicators] = useState<TechnicalIndicators | null>(null);
  const [sentiment, setSentiment] = useState<any>(null);
  const [risk, setRisk] = useState<any>(null);
  const [company, setCompany] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());

  const fetchAll = useCallback(async () => {
    try {
      // Phase 1: Fetch quote (via batch for speed) + OHLCV in parallel
      // Using batch endpoint even for 1 stock — it uses yf.download which is lighter than ticker.info
      const [batchRes, ohlcvRes] = await Promise.allSettled([
        apiClient.post<{ success: boolean; data: any[] }>(
          '/api/v1/market/batch-quotes',
          { symbols: [symbol] }
        ),
        apiClient.get<{ data: OHLCVBar[] }>(`/api/v1/market/ohlcv/${encodeURIComponent(symbol)}?period=3mo&interval=1d`),
      ]);

      if (batchRes.status === 'fulfilled' && batchRes.value.data?.[0]) {
        setQuote(batchRes.value.data[0]);
      } else {
        // Fallback: try individual quote endpoint (uses fast_info/ticker.info)
        try {
          const quoteRes = await apiClient.get<{ data: StockQuote }>(
            `/api/v1/market/quote/${encodeURIComponent(symbol)}`
          );
          if (quoteRes.data) setQuote(quoteRes.data);
        } catch {
          // Both batch and individual failed — quote stays null
        }
      }
      if (ohlcvRes.status === 'fulfilled') {
        const d = ohlcvRes.value.data;
        setOhlcv(Array.isArray(d) ? d : []);
      }

      // Show chart + price ASAP
      setLoading(false);

      // Phase 2: Fetch company + sentiment + risk + indicators (deferred — lower priority)
      const [companyRes, sentRes, riskRes, indRes] = await Promise.allSettled([
        apiClient.get<{ data: any }>(`/api/v1/market/company/${encodeURIComponent(symbol)}`),
        apiClient.get<{ data: any }>(`/api/v1/sentiment/${encodeURIComponent(symbol)}`),
        apiClient.get<{ data: any }>(`/api/v1/risk/${encodeURIComponent(symbol)}`),
        apiClient.get<{ data: any }>(`/api/v1/market/indicators/${encodeURIComponent(symbol)}`),
      ]);

      if (companyRes.status === 'fulfilled') setCompany(companyRes.value.data);
      if (sentRes.status === 'fulfilled') setSentiment(sentRes.value.data);
      if (riskRes.status === 'fulfilled') setRisk(riskRes.value.data);
      if (indRes.status === 'fulfilled') setIndicators(indRes.value.data);
    } catch {
      // Graceful degradation — show what we have
    } finally {
      setLoading(false);
      setLastUpdated(new Date());
    }
  }, [symbol]);

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, REFRESH_INTERVALS.tick);
    return () => clearInterval(interval);
  }, [fetchAll]);

  const isPositive = (quote?.change ?? 0) >= 0;
  const currency = quote?.currency === 'INR' ? '₹' : '$';

  return (
    <div className="space-y-5 animate-fadeIn pb-10">
      {/* Disclaimer */}
      <Disclaimer />

      {/* Back + Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-4">
          <Link
            href="/markets"
            className="mt-1 p-2 rounded-xl bg-white/[0.03] border border-white/[0.06] text-[var(--text-muted)] hover:text-white hover:bg-white/[0.08] transition-all"
          >
            <ArrowLeft className="w-4 h-4" />
          </Link>

          <div>
            <div className="flex items-center gap-3">
              <h1 className="font-heading text-2xl font-bold tracking-tight text-white">
                {symbol}
              </h1>
              <span className="badge badge-neutral">
                {quote?.exchange ?? 'NSE'}
              </span>
            </div>
            <p className="text-xs font-mono text-[var(--text-dim)] mt-1">
              {quote?.name ?? company?.name ?? 'Market Instrument'}
              {company?.sector && (
                <span className="text-[var(--text-dim)]"> · {company.sector}</span>
              )}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <DataFreshness timestamp={lastUpdated} thresholdMs={60000} />
          <button
            onClick={fetchAll}
            className="p-2 rounded-xl bg-white/[0.03] border border-white/[0.06] text-[var(--text-muted)] hover:text-white hover:bg-white/[0.08] transition-all cursor-pointer"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Price Hero (Matching Reference Panel 02) */}
      {loading ? (
        <LoadingSkeleton variant="card" />
      ) : quote ? (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="card p-6"
        >
          <div className="flex items-start justify-between gap-6 flex-wrap">
            {/* Price & Change */}
            <div>
              <div className="text-[11px] font-mono text-[var(--text-dim)] uppercase tracking-wider mb-1">
                Last Traded Price
              </div>
              <div className="font-heading text-4xl sm:text-5xl font-bold tracking-tight text-white">
                {currency}{formatNumber(quote.price)}
              </div>
              <div className="flex items-center gap-2 mt-2">
                <span className={`inline-flex items-center gap-1.5 text-sm font-mono font-medium px-2.5 py-1 rounded-lg ${
                  isPositive
                    ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                    : 'bg-red-500/10 text-red-400 border border-red-500/20'
                }`}>
                  {isPositive ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
                  {isPositive ? '+' : ''}{formatNumber(quote.change)} ({isPositive ? '+' : ''}{quote.change_percent.toFixed(2)}%)
                </span>
              </div>
            </div>

            {/* Quick Stats Grid */}
            <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-4 text-xs font-mono pt-2">
              <div className="p-2 rounded-lg bg-white/[0.02] border border-white/[0.04]">
                <span className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider block">Open</span>
                <span className="text-white font-medium">{currency}{formatNumber(quote.open)}</span>
              </div>
              <div className="p-2 rounded-lg bg-white/[0.02] border border-white/[0.04]">
                <span className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider block">High</span>
                <span className="text-white font-medium">{currency}{formatNumber(quote.high)}</span>
              </div>
              <div className="p-2 rounded-lg bg-white/[0.02] border border-white/[0.04]">
                <span className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider block">Low</span>
                <span className="text-white font-medium">{currency}{formatNumber(quote.low)}</span>
              </div>
              <div className="p-2 rounded-lg bg-white/[0.02] border border-white/[0.04]">
                <span className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider block">Prev Close</span>
                <span className="text-white font-medium">{currency}{formatNumber(quote.previous_close)}</span>
              </div>
              <div className="p-2 rounded-lg bg-white/[0.02] border border-white/[0.04]">
                <span className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider block">Volume</span>
                <span className="text-white font-medium">{(quote.volume / 1e6).toFixed(1)}M</span>
              </div>
              <div className="p-2 rounded-lg bg-white/[0.02] border border-white/[0.04]">
                <span className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider block">Mkt Cap</span>
                <span className="text-white font-medium">{formatMarketCap(quote.market_cap, currency)}</span>
              </div>
              <div className="p-2 rounded-lg bg-white/[0.02] border border-white/[0.04]">
                <span className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider block">P/E</span>
                <span className="text-white font-medium">{quote.pe_ratio?.toFixed(2) ?? 'N/A'}</span>
              </div>
            </div>
          </div>
        </motion.div>
      ) : (
        <div className="card p-8 text-center text-[var(--text-dim)] font-mono text-xs">
          <p>Could not load quote for {symbol}. Ensure the backend is running.</p>
        </div>
      )}

      {/* Chart */}
      <PriceChart data={ohlcv} symbol={symbol} />

      {/* AI Forecast */}
      <PredictionPanel symbol={symbol} />

      {/* Two-column: Technicals + Sentiment/Risk */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Left: Technical Indicators */}
        <div className="lg:col-span-1">
          <TechnicalPanel indicators={indicators} loading={loading} />
        </div>

        {/* Right: Sentiment + Risk stacked */}
        <div className="lg:col-span-2 space-y-5">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {sentiment ? (
              <SentimentGauge
                score={sentiment.overall_score}
                label={sentiment.overall_label}
                confidence={sentiment.confidence}
                bullishPct={sentiment.bullish_pct}
                bearishPct={sentiment.bearish_pct}
                neutralPct={sentiment.neutral_pct}
                totalSources={sentiment.total_sources}
              />
            ) : (
              <SentimentGauge
                score={0}
                label="Neutral"
                confidence={0}
                bullishPct={33}
                bearishPct={33}
                neutralPct={34}
                totalSources={0}
                loading={loading}
              />
            )}

            {risk ? (
              <RiskScore
                compositeScore={risk.composite_score}
                compositeLabel={risk.composite_label}
                dimensions={risk.dimensions}
                confidence={risk.confidence}
                disclaimer={risk.disclaimer}
              />
            ) : (
              <RiskScore
                compositeScore={50}
                compositeLabel="Medium Risk"
                dimensions={[]}
                confidence={0}
                disclaimer=""
                loading={loading}
              />
            )}
          </div>
        </div>
      </div>

      {/* AI Research Report */}
      <ResearchReport symbol={symbol} />
    </div>
  );
}
