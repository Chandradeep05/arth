'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  TrendingUp,
  TrendingDown,
  Minus,
  Brain,
  BarChart3,
  AlertTriangle,
  Loader2,
  Activity,
  Zap,
} from 'lucide-react';
import { apiClient } from '@/lib/api';
import { useAuthenticatedApi } from '@/lib/auth/useAuthenticatedApi';

interface SHAPFactor {
  name: string;
  feature_key: string;
  importance: number;
  shap_value: number | null;
  value: number;
  direction: 'positive' | 'negative' | 'unknown';
}

interface PredictionData {
  symbol: string;
  prediction?: {
    direction: 'bullish' | 'bearish' | 'neutral';
    predicted_return_pct: number;
    confidence: 'high' | 'medium' | 'low';
    confidence_score: number;
    horizon_days: number;
  };
  factors?: SHAPFactor[];
  regime?: {
    current: 'trending' | 'ranging' | 'reverting';
    description: string;
    strength?: number;
  };
  model_info?: {
    features_used: number;
    training_samples: number;
    r2_score: number;
  };
  disclaimer?: string;
  error?: boolean;
  message?: string;
}

export default function PredictionPanel({ symbol }: { symbol: string }) {
  const [data, setData] = useState<PredictionData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const authApi = useAuthenticatedApi();

  const generateForecast = async () => {
    setLoading(true);
    setError(null);
    try {
      if (!authApi.isAuthenticated) {
        setError('Sign in to generate predictions.');
        setLoading(false);
        return;
      }
      const res = await authApi.post<PredictionData>(
        `/api/v1/prediction/${encodeURIComponent(symbol)}/forecast`,
        {}
      );
      setData(res);
    } catch (err: any) {
      if (err?.status === 401) {
        setError('Sign in to generate predictions.');
      } else {
        setError(err?.message || 'Failed to generate prediction');
      }
    } finally {
      setLoading(false);
    }
  };

  const directionIcon = (dir: string) => {
    if (dir === 'bullish') return <TrendingUp className="w-5 h-5 text-emerald-400" />;
    if (dir === 'bearish') return <TrendingDown className="w-5 h-5 text-red-400" />;
    return <Minus className="w-5 h-5 text-[var(--text-muted)]" />;
  };

  const directionColor = (dir: string) => {
    if (dir === 'bullish') return '#10b981';
    if (dir === 'bearish') return '#ef4444';
    return 'var(--text-muted)';
  };

  const confidenceColor = (conf: string) => {
    if (conf === 'high') return '#10b981';
    if (conf === 'medium') return '#f59e0b';
    return 'var(--text-dim)';
  };

  const regimeIcon = (regime: string) => {
    if (regime === 'trending') return <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />;
    if (regime === 'reverting') return <Activity className="w-3.5 h-3.5 text-amber-400" />;
    return <Minus className="w-3.5 h-3.5" />;
  };

  return (
    <div className="card overflow-hidden relative">
      <div className="card-atmosphere card-atmosphere-intelligence" style={{ opacity: 0.05 }} aria-hidden="true" />
      <div className="relative z-10">
        <div className="px-5 py-3.5 border-b border-white/[0.06] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-white/[0.04] border border-white/[0.08] flex items-center justify-center">
            <Brain className="w-3.5 h-3.5 text-emerald-400" />
          </div>
          <h3 className="font-heading text-xs font-bold uppercase tracking-wider text-white">
            AI Market Outlook
          </h3>
          <span className="badge badge-neutral">
            XGBoost + SHAP
          </span>
        </div>

        {!loading && (
          <button
            onClick={generateForecast}
            className="text-xs px-3 py-1.5 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.08] text-white transition-all cursor-pointer font-medium"
          >
            {data ? 'Regenerate' : 'Generate Forecast'}
          </button>
        )}
      </div>

      <div className="p-5">
        {/* Not yet generated */}
        {!data && !loading && !error && (
          <div className="text-center py-8">
            <div className="w-10 h-10 rounded-xl bg-white/[0.03] border border-white/[0.06] flex items-center justify-center mx-auto mb-3">
              <Brain className="w-5 h-5 text-[var(--text-dim)]" />
            </div>
            <p className="text-xs text-[var(--text-muted)] mb-1 font-medium">
              5-Day Probabilistic Quantitative Forecast
            </p>
            <p className="text-[11px] text-[var(--text-dim)] font-mono max-w-sm mx-auto">
              Trained on 2 years of market history with SHAP feature interpretability
            </p>
            <button
              onClick={generateForecast}
              className="mt-4 px-4 py-2 rounded-xl bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/25 text-xs font-semibold tracking-wide transition-all cursor-pointer"
            >
              <Zap className="w-3.5 h-3.5 inline mr-1" />
              Generate Prediction
            </button>
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div className="text-center py-8">
            <Loader2 className="w-6 h-6 text-emerald-400 mx-auto mb-3 animate-spin" />
            <p className="text-xs text-[var(--text-muted)] font-medium">Calculating feature matrix &amp; probabilities...</p>
            <p className="text-[11px] text-[var(--text-dim)] font-mono mt-1">
              Evaluating multi-factor SHAP values
            </p>
          </div>
        )}

        {/* Error */}
        {(error || (data && data.error)) && !loading && (
          <div className="text-center py-6">
            <AlertTriangle className="w-5 h-5 text-red-400 mx-auto mb-2" />
            <p className="text-xs text-red-400 font-mono">{error || data?.message || 'Prediction failed'}</p>
            <button
              onClick={generateForecast}
              className="mt-3 px-3 py-1.5 rounded-lg bg-white/[0.04] text-white border border-white/[0.08] text-xs hover:bg-white/[0.08] transition-colors cursor-pointer"
            >
              Retry
            </button>
          </div>
        )}

        {/* Results */}
        <AnimatePresence>
          {data && data.prediction && !loading && (
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              className="space-y-4"
            >
              {/* Direction + Return */}
              <div className="flex items-center justify-between p-4 rounded-xl bg-white/[0.02] border border-white/[0.04]">
                <div className="flex items-center gap-3.5">
                  <div
                    className="w-10 h-10 rounded-xl flex items-center justify-center border"
                    style={{
                      background: `${directionColor(data.prediction.direction)}15`,
                      borderColor: `${directionColor(data.prediction.direction)}30`,
                    }}
                  >
                    {directionIcon(data.prediction.direction)}
                  </div>
                  <div>
                    <div
                      className="text-2xl font-heading font-bold"
                      style={{ color: directionColor(data.prediction.direction) }}
                    >
                      {data.prediction.predicted_return_pct > 0 ? '+' : ''}
                      {data.prediction.predicted_return_pct}%
                    </div>
                    <div className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider font-mono">
                      {data.prediction.horizon_days}-day outlook · <span className="capitalize">{data.prediction.direction}</span>
                    </div>
                  </div>
                </div>

                {/* Confidence */}
                <div className="text-right">
                  <div
                    className="text-xs font-mono font-bold uppercase tracking-wider"
                    style={{ color: confidenceColor(data.prediction.confidence) }}
                  >
                    {data.prediction.confidence} confidence
                  </div>
                  <div className="w-24 h-1.5 bg-white/[0.06] rounded-full mt-1.5 overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all"
                      style={{
                        width: `${data.prediction.confidence_score * 100}%`,
                        background: confidenceColor(data.prediction.confidence),
                      }}
                    />
                  </div>
                </div>
              </div>

              {/* Regime Badge */}
              {data.regime && (
                <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-white/[0.02] border border-white/[0.04]">
                  {regimeIcon(data.regime.current)}
                  <span className="text-[10px] uppercase tracking-wider text-[var(--text-dim)] font-mono">
                    Market Regime:
                  </span>
                  <span className="text-xs font-semibold text-white capitalize">
                    {data.regime.current}
                  </span>
                  <span className="text-[11px] text-[var(--text-muted)] truncate">
                    — {data.regime.description}
                  </span>
                </div>
              )}

              {/* SHAP Factors */}
              {data.factors && data.factors.length > 0 && (
                <div>
                  <div className="flex items-center gap-1.5 mb-2.5">
                    <BarChart3 className="w-3.5 h-3.5 text-[var(--text-dim)]" />
                    <span className="text-[10px] uppercase tracking-wider text-[var(--text-dim)] font-mono">
                      Top Contributing Factors (SHAP Explanations)
                    </span>
                  </div>
                  <div className="space-y-2">
                    {data.factors.slice(0, 5).map((factor, i) => {
                      const maxImportance = data.factors![0].importance;
                      const barWidth = maxImportance > 0
                        ? (factor.importance / maxImportance) * 100
                        : 0;
                      const isPositive = factor.direction === 'positive';

                      return (
                        <div key={i} className="flex items-center gap-3 text-xs">
                          <span className="text-[11px] text-[var(--text-muted)] w-32 truncate text-right">
                            {factor.name}
                          </span>
                          <div className="flex-1 h-3.5 bg-white/[0.04] rounded-md overflow-hidden relative border border-white/[0.03]">
                            <motion.div
                              initial={{ width: 0 }}
                              animate={{ width: `${Math.min(barWidth, 100)}%` }}
                              transition={{ delay: i * 0.08, duration: 0.4 }}
                              className="h-full rounded-sm"
                              style={{
                                background: isPositive
                                  ? '#10b981'
                                  : factor.direction === 'negative'
                                  ? '#ef4444'
                                  : 'var(--text-dim)',
                                opacity: 0.5,
                              }}
                            />
                          </div>
                          <span className="text-[11px] font-mono w-14 text-right font-medium" style={{
                            color: isPositive ? '#10b981' : '#ef4444',
                          }}>
                            {isPositive ? '+' : ''}{(factor.shap_value ?? factor.importance * (isPositive ? 1 : -1)).toFixed(4)}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Model Info */}
              {data.model_info && (
                <div className="flex gap-4 text-[10px] font-mono text-[var(--text-dim)] pt-3 border-t border-white/[0.06]">
                  <span>{data.model_info.training_samples} training samples</span>
                  <span>•</span>
                  <span>R² = {data.model_info.r2_score}</span>
                  <span>•</span>
                  <span>{data.model_info.features_used} features</span>
                </div>
              )}

              {/* Disclaimer */}
              {data.disclaimer && (
                <div className="text-[10px] text-[var(--text-dim)] leading-relaxed px-3 py-2 rounded-xl bg-white/[0.02] border border-white/[0.04] font-mono">
                  {data.disclaimer}
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
      </div>
    </div>
  );
}
