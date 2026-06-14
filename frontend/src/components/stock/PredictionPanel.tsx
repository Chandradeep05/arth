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

  const generateForecast = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.post<PredictionData>(
        `/api/v1/prediction/${encodeURIComponent(symbol)}/forecast`,
        {}
      );
      setData(res);
    } catch (err: any) {
      setError(err?.message || 'Failed to generate prediction');
    } finally {
      setLoading(false);
    }
  };

  const directionIcon = (dir: string) => {
    if (dir === 'bullish') return <TrendingUp className="w-5 h-5 text-[var(--green)]" />;
    if (dir === 'bearish') return <TrendingDown className="w-5 h-5 text-[var(--red)]" />;
    return <Minus className="w-5 h-5 text-[var(--text-muted)]" />;
  };

  const directionColor = (dir: string) => {
    if (dir === 'bullish') return 'var(--green)';
    if (dir === 'bearish') return 'var(--red)';
    return 'var(--text-muted)';
  };

  const confidenceColor = (conf: string) => {
    if (conf === 'high') return 'var(--green)';
    if (conf === 'medium') return 'var(--gold, #f5c842)';
    return 'var(--text-dim)';
  };

  const regimeIcon = (regime: string) => {
    if (regime === 'trending') return <TrendingUp className="w-3.5 h-3.5" />;
    if (regime === 'reverting') return <Activity className="w-3.5 h-3.5" />;
    return <Minus className="w-3.5 h-3.5" />;
  };

  return (
    <div className="card">
      <div className="p-4 border-b border-[var(--border)] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Brain className="w-4 h-4 text-[var(--accent)]" />
          <h3 className="font-heading text-sm font-bold text-[var(--text)]">
            AI Forecast
          </h3>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--accent)]/10 text-[var(--accent)] font-mono">
            XGBoost + SHAP
          </span>
        </div>

        {!loading && (
          <button
            onClick={generateForecast}
            className="text-xs px-3 py-1.5 rounded bg-[var(--accent)]/10 text-[var(--accent)] hover:bg-[var(--accent)]/20 transition-colors cursor-pointer font-medium"
          >
            {data ? 'Regenerate' : 'Generate Forecast'}
          </button>
        )}
      </div>

      <div className="p-4">
        {/* Not yet generated */}
        {!data && !loading && !error && (
          <div className="text-center py-8">
            <Brain className="w-8 h-8 text-[var(--text-dim)] mx-auto mb-3" />
            <p className="text-sm text-[var(--text-muted)] mb-1">
              5-day probabilistic forecast
            </p>
            <p className="text-xs text-[var(--text-dim)]">
              XGBoost model trained on 2 years of data with SHAP explanations
            </p>
            <button
              onClick={generateForecast}
              className="mt-4 px-4 py-2 rounded bg-[var(--accent)] text-[var(--bg)] text-xs font-bold hover:opacity-90 transition-opacity cursor-pointer"
            >
              <Zap className="w-3 h-3 inline mr-1" />
              Generate Prediction
            </button>
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div className="text-center py-8">
            <Loader2 className="w-6 h-6 text-[var(--accent)] mx-auto mb-3 animate-spin" />
            <p className="text-sm text-[var(--text-muted)]">Training model...</p>
            <p className="text-xs text-[var(--text-dim)] mt-1">
              First run takes 5-10 seconds (building feature matrix + training XGBoost)
            </p>
          </div>
        )}

        {/* Error — either local fetch error or API-returned error */}
        {(error || (data && data.error)) && !loading && (
          <div className="text-center py-6">
            <AlertTriangle className="w-5 h-5 text-[var(--red)] mx-auto mb-2" />
            <p className="text-xs text-[var(--red)]">{error || data?.message || 'Prediction failed'}</p>
            <button
              onClick={generateForecast}
              className="mt-3 px-3 py-1.5 rounded bg-[var(--accent)]/10 text-[var(--accent)] text-xs hover:bg-[var(--accent)]/20 transition-colors cursor-pointer"
            >
              Retry
            </button>
          </div>
        )}

        {/* Results */}
        <AnimatePresence>
          {data && data.prediction && !loading && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="space-y-4"
            >
              {/* Direction + Return */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div
                    className="w-10 h-10 rounded-lg flex items-center justify-center"
                    style={{ background: `${directionColor(data.prediction.direction)}15` }}
                  >
                    {directionIcon(data.prediction.direction)}
                  </div>
                  <div>
                    <div
                      className="text-lg font-heading font-extrabold"
                      style={{ color: directionColor(data.prediction.direction) }}
                    >
                      {data.prediction.predicted_return_pct > 0 ? '+' : ''}
                      {data.prediction.predicted_return_pct}%
                    </div>
                    <div className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">
                      {data.prediction.horizon_days}-day outlook · {data.prediction.direction}
                    </div>
                  </div>
                </div>

                {/* Confidence */}
                <div className="text-right">
                  <div
                    className="text-xs font-bold uppercase"
                    style={{ color: confidenceColor(data.prediction.confidence) }}
                  >
                    {data.prediction.confidence} confidence
                  </div>
                  <div className="w-20 h-1.5 bg-[var(--surface-2)] rounded-full mt-1">
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
                <div className="flex items-center gap-2 px-2.5 py-1.5 rounded bg-[var(--surface-2)] w-fit">
                  {regimeIcon(data.regime.current)}
                  <span className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
                    Market regime:
                  </span>
                  <span className="text-xs font-mono text-[var(--text)]">
                    {data.regime.current}
                  </span>
                  <span className="text-[10px] text-[var(--text-dim)]">
                    — {data.regime.description}
                  </span>
                </div>
              )}

              {/* SHAP Factors (Waterfall) */}
              {data.factors && data.factors.length > 0 && (
                <div>
                  <div className="flex items-center gap-1.5 mb-2">
                    <BarChart3 className="w-3 h-3 text-[var(--text-dim)]" />
                    <span className="text-[10px] uppercase tracking-wider text-[var(--text-dim)]">
                      Top Contributing Factors (SHAP)
                    </span>
                  </div>
                  <div className="space-y-1.5">
                    {data.factors.slice(0, 5).map((factor, i) => {
                      const maxImportance = data.factors![0].importance;
                      const barWidth = maxImportance > 0
                        ? (factor.importance / maxImportance) * 100
                        : 0;
                      const isPositive = factor.direction === 'positive';

                      return (
                        <div key={i} className="flex items-center gap-2">
                          <span className="text-[10px] text-[var(--text-muted)] w-28 truncate text-right">
                            {factor.name}
                          </span>
                          <div className="flex-1 h-4 bg-[var(--surface-2)] rounded-sm overflow-hidden relative">
                            <motion.div
                              initial={{ width: 0 }}
                              animate={{ width: `${Math.min(barWidth, 100)}%` }}
                              transition={{ delay: i * 0.1, duration: 0.5 }}
                              className="h-full rounded-sm"
                              style={{
                                background: isPositive
                                  ? 'var(--green)'
                                  : factor.direction === 'negative'
                                  ? 'var(--red)'
                                  : 'var(--text-dim)',
                                opacity: 0.6,
                              }}
                            />
                          </div>
                          <span className="text-[10px] font-mono w-12 text-right" style={{
                            color: isPositive ? 'var(--green)' : 'var(--red)',
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
                <div className="flex gap-4 text-[10px] font-mono text-[var(--text-dim)] pt-2 border-t border-[var(--border)]">
                  <span>{data.model_info.training_samples} training samples</span>
                  <span>R² = {data.model_info.r2_score}</span>
                  <span>{data.model_info.features_used} features</span>
                </div>
              )}

              {/* Disclaimer */}
              {data.disclaimer && (
                <div className="text-[10px] text-[var(--text-dim)] leading-relaxed px-2 py-1.5 rounded bg-[var(--surface-2)]">
                  {data.disclaimer}
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
