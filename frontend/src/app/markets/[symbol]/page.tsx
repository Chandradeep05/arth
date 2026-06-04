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
import { API_BASE_URL, REFRESH_INTERVALS } from '@/lib/constants';
import PriceChart from '@/components/charts/PriceChart';
import TechnicalPanel from '@/components/stock/TechnicalPanel';
import ResearchReport from '@/components/stock/ResearchReport';
import SentimentGauge from '@/components/stock/SentimentGauge';
import RiskScore from '@/components/stock/RiskScore';
import DataFreshness from '@/components/shared/DataFreshness';
import Disclaimer from '@/components/shared/Disclaimer';
import LoadingSkeleton from '@/components/shared/LoadingSkeleton';
import type { StockQuote, OHLCVBar, TechnicalIndicators } from '@/types/market';

function formatNumber(n: number): string {
  return new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(n);
}

function formatMarketCap(n: number | null): string {
  if (!n) return 'N/A';
  if (n >= 1e12) return `₹${(n / 1e12).toFixed(2)}T`;
  if (n >= 1e9) return `₹${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)}Cr`;
  return `₹${formatNumber(n)}`;
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
            href="/"
            className="mt-1 p-2 rounded hover:bg-[var(--surface-2)] text-[var(--text-muted)] hover:text-[var(--accent)] transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
          </Link>

          <div>
            <div className="flex items-center gap-3">
              <h1 className="font-heading text-xl font-extrabold tracking-tight text-[var(--text)]">
                {symbol}
              </h1>
              <span className="badge badge-cyan">
                {quote?.exchange ?? '...'}
              </span>
            </div>
            <p className="text-sm text-[var(--text-muted)] mt-0.5">
              {quote?.name ?? company?.name ?? 'Loading...'}
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
            className="p-2 rounded hover:bg-[var(--surface-2)] text-[var(--text-muted)] hover:text-[var(--accent)] transition-colors cursor-pointer"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Price Hero */}
      {loading ? (
        <LoadingSkeleton variant="card" />
      ) : quote ? (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="card p-6"
        >
          <div className="flex items-end gap-6 flex-wrap">
            {/* Price */}
            <div>
              <div className="font-heading text-4xl font-extrabold tracking-tight text-[var(--text)]">
                {currency}{formatNumber(quote.price)}
              </div>
              <div className="flex items-center gap-2 mt-1">
                {isPositive ? (
                  <TrendingUp className="w-4 h-4 text-[var(--green)]" />
                ) : (
                  <TrendingDown className="w-4 h-4 text-[var(--red)]" />
                )}
                <span className={`text-sm font-mono font-medium ${isPositive ? 'text-[var(--green)]' : 'text-[var(--red)]'}`}>
                  {isPositive ? '+' : ''}{formatNumber(quote.change)} ({isPositive ? '+' : ''}{quote.change_percent.toFixed(2)}%)
                </span>
              </div>
            </div>

            {/* Quick Stats */}
            <div className="flex gap-6 text-xs font-mono">
              <div>
                <span className="text-[var(--text-dim)] block">Open</span>
                <span className="text-[var(--text)]">{currency}{formatNumber(quote.open)}</span>
              </div>
              <div>
                <span className="text-[var(--text-dim)] block">High</span>
                <span className="text-[var(--text)]">{currency}{formatNumber(quote.high)}</span>
              </div>
              <div>
                <span className="text-[var(--text-dim)] block">Low</span>
                <span className="text-[var(--text)]">{currency}{formatNumber(quote.low)}</span>
              </div>
              <div>
                <span className="text-[var(--text-dim)] block">Prev Close</span>
                <span className="text-[var(--text)]">{currency}{formatNumber(quote.previous_close)}</span>
              </div>
              <div>
                <span className="text-[var(--text-dim)] block">Volume</span>
                <span className="text-[var(--text)]">{(quote.volume / 1e6).toFixed(1)}M</span>
              </div>
              <div>
                <span className="text-[var(--text-dim)] block">Mkt Cap</span>
                <span className="text-[var(--text)]">{formatMarketCap(quote.market_cap)}</span>
              </div>
              <div>
                <span className="text-[var(--text-dim)] block">P/E</span>
                <span className="text-[var(--text)]">{quote.pe_ratio?.toFixed(2) ?? 'N/A'}</span>
              </div>
            </div>
          </div>
        </motion.div>
      ) : (
        <div className="card p-8 text-center text-[var(--text-dim)]">
          <p>Could not load quote for {symbol}. Ensure the backend is running.</p>
        </div>
      )}

      {/* Chart */}
      <PriceChart data={ohlcv} symbol={symbol} />

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
