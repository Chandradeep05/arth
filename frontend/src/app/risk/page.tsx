'use client';

import { useState } from 'react';
import { motion } from 'framer-motion';
import { ShieldAlert, Activity, TrendingDown, BarChart3, ArrowRight } from 'lucide-react';
import { apiClient } from '@/lib/api';
import Disclaimer from '@/components/shared/Disclaimer';
import LoadingSkeleton from '@/components/shared/LoadingSkeleton';

function RiskBar({ label, score, color }: { label: string; score: number; color: string }) {
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs font-mono">
        <span className="text-[var(--text-muted)]">{label}</span>
        <span style={{ color }}>{score.toFixed(1)}/100</span>
      </div>
      <div className="h-2 rounded-full bg-[var(--surface-2)] overflow-hidden">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${score}%` }}
          transition={{ duration: 0.8, ease: 'easeOut' }}
          className="h-full rounded-full"
          style={{ background: color }}
        />
      </div>
    </div>
  );
}

export default function RiskPage() {
  const [symbol, setSymbol] = useState('');
  const [risk, setRisk] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleAnalyze = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!symbol.trim()) return;
    setLoading(true);
    setError('');
    setRisk(null);
    try {
      const res = await apiClient.get<{ data: any }>(`/api/v1/risk/${encodeURIComponent(symbol.trim().toUpperCase())}`);
      setRisk(res.data);
    } catch {
      setError(`Could not fetch risk data for ${symbol.toUpperCase()}`);
    } finally {
      setLoading(false);
    }
  };

  const getRiskColor = (score: number) => {
    if (score < 25) return 'var(--green)';
    if (score < 50) return 'var(--gold)';
    if (score < 75) return 'var(--accent-orange)';
    return 'var(--red)';
  };

  return (
    <div className="space-y-8 animate-fadeIn">
      <Disclaimer />

      <div>
        <h1 className="font-heading text-xl font-extrabold tracking-tight text-[var(--text)]">
          Risk Intelligence
        </h1>
        <p className="text-xs text-[var(--text-muted)] mt-1 font-mono">
          Multi-dimensional risk scoring · Volatility · Liquidity · Balance sheet health
        </p>
      </div>

      {/* Input */}
      <form onSubmit={handleAnalyze} className="flex gap-2 max-w-xl relative">
        <input
          type="text"
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          placeholder="Enter stock symbol (e.g., RELIANCE.NS, AAPL, TCS.NS)..."
          className="flex-1 px-4 py-3 rounded-full bg-[var(--surface-2)] border border-[var(--border)]
                     text-[var(--text)] font-mono text-xs placeholder:text-[var(--text-dim)]
                     focus:outline-none focus:border-[var(--green)]/50 focus:ring-1 focus:ring-[var(--green)]/30
                     transition-all"
        />
        <button
          type="submit"
          disabled={loading}
          className="px-5 py-2.5 rounded-full bg-[var(--green)] text-black text-xs font-bold
                     uppercase tracking-wider hover:bg-[var(--green-hover)] transition-all cursor-pointer
                     disabled:opacity-40 flex items-center gap-2 shadow-sm"
        >
          {loading ? 'Scanning...' : 'Scan'} <ArrowRight className="w-3.5 h-3.5" />
        </button>
      </form>

      {/* Results */}
      {loading && (
        <div className="max-w-2xl space-y-3">
          <LoadingSkeleton variant="card" />
          <LoadingSkeleton variant="card" />
        </div>
      )}

      {error && (
        <div className="card p-5 max-w-xl border-[var(--red)]/30">
          <p className="text-xs font-mono text-[var(--red)]">{error}</p>
        </div>
      )}

      {risk && (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          className="max-w-2xl space-y-4"
        >
          {/* Composite Score */}
          <div className="card p-6">
            <div className="flex items-center justify-between mb-4 pb-4 border-b border-[var(--border)]">
              <div>
                <h2 className="font-heading text-lg font-bold text-[var(--text)]">
                  {risk.symbol}
                </h2>
                <p className="text-xs text-[var(--text-dim)] font-mono">Composite Risk Assessment</p>
              </div>
              <div className="text-right">
                <div className="font-heading text-3xl font-extrabold" style={{ color: getRiskColor(risk.composite_score) }}>
                  {risk.composite_score?.toFixed(1)}
                </div>
                <div className="text-xs font-mono font-medium" style={{ color: getRiskColor(risk.composite_score) }}>
                  {risk.composite_label}
                </div>
              </div>
            </div>

            {/* Dimensions */}
            <div className="space-y-4 mt-4">
              {risk.dimensions?.map((dim: any) => (
                <RiskBar
                  key={dim.dimension}
                  label={(dim.dimension || '').replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase())}
                  score={dim.score}
                  color={getRiskColor(dim.score)}
                />
              ))}
            </div>
          </div>

          {risk.disclaimer && (
            <p className="text-[11px] text-[var(--text-dim)] font-mono px-1">{risk.disclaimer}</p>
          )}
        </motion.div>
      )}

      {/* Explainer cards (shown when no analysis yet) */}
      {!risk && !loading && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 max-w-3xl">
          {[
            { icon: Activity, title: 'Volatility Risk', desc: 'Measures price stability using standard deviation of returns over 30/90 day windows', color: 'var(--gold)' },
            { icon: BarChart3, title: 'Liquidity Risk', desc: 'Evaluates trading volume patterns to assess ease of entering/exiting positions', color: 'var(--green)' },
            { icon: TrendingDown, title: 'Financial Health', desc: 'Scores balance sheet strength: debt ratios, margins, ROE, current ratio', color: 'var(--green)' },
          ].map((item, i) => (
            <motion.div
              key={item.title}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 + i * 0.1 }}
              className="card p-5"
            >
              <item.icon className="w-4 h-4 mb-3" style={{ color: item.color }} />
              <h3 className="font-heading text-xs font-bold text-[var(--text)] mb-1">{item.title}</h3>
              <p className="text-[11px] text-[var(--text-dim)] font-mono leading-relaxed">{item.desc}</p>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}
