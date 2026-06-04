'use client';

import { useState } from 'react';
import { motion } from 'framer-motion';
import {
  ArrowRight,
  BarChart3,
  FileSpreadsheet,
  Wallet,
  DollarSign,
  Percent,
  HeartPulse,
} from 'lucide-react';
import { apiClient } from '@/lib/api';
import Disclaimer from '@/components/shared/Disclaimer';
import LoadingSkeleton from '@/components/shared/LoadingSkeleton';
import StatementTable, { type StatementPeriod } from '@/components/financials/StatementTable';
import HealthScoreCard, { type HealthScoreData } from '@/components/financials/HealthScoreCard';

/* ── Tab Definitions ── */
type TabKey = 'income' | 'balance' | 'cashflow' | 'ratios' | 'health';

const TABS: { key: TabKey; label: string; icon: React.ElementType }[] = [
  { key: 'income', label: 'Income Statement', icon: FileSpreadsheet },
  { key: 'balance', label: 'Balance Sheet', icon: Wallet },
  { key: 'cashflow', label: 'Cash Flow', icon: DollarSign },
  { key: 'ratios', label: 'Ratios', icon: Percent },
  { key: 'health', label: 'Health Score', icon: HeartPulse },
];

type Period = 'annual' | 'quarterly';

/* ── Interfaces ── */
interface StatementsResponse {
  symbol: string;
  income_statement: StatementPeriod[];
  balance_sheet: StatementPeriod[];
  cash_flow: StatementPeriod[];
}

interface RatiosResponse {
  symbol: string;
  ratios: StatementPeriod[];
}

interface HealthResponse {
  symbol: string;
  overall_score: number;
  categories: { name: string; score: number }[];
  summary?: string;
}

/* ── Page Component ── */
export default function FinancialsPage() {
  const [symbol, setSymbol] = useState('');
  const [activeSymbol, setActiveSymbol] = useState('');
  const [activeTab, setActiveTab] = useState<TabKey>('income');
  const [period, setPeriod] = useState<Period>('annual');

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const [statements, setStatements] = useState<StatementsResponse | null>(null);
  const [ratios, setRatios] = useState<RatiosResponse | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    const sym = symbol.trim().toUpperCase();
    if (!sym) return;

    setLoading(true);
    setError('');
    setStatements(null);
    setRatios(null);
    setHealth(null);
    setActiveSymbol(sym);

    try {
      // Fetch all three in parallel
      const [stmtRes, ratiosRes, healthRes] = await Promise.allSettled([
        apiClient.get<StatementsResponse>(
          `/api/v1/financials/${encodeURIComponent(sym)}/statements`,
          { period }
        ),
        apiClient.get<RatiosResponse>(
          `/api/v1/financials/${encodeURIComponent(sym)}/ratios`,
          { period }
        ),
        apiClient.get<HealthResponse>(
          `/api/v1/financials/${encodeURIComponent(sym)}/health-score`
        ),
      ]);

      if (stmtRes.status === 'fulfilled') setStatements(stmtRes.value);
      if (ratiosRes.status === 'fulfilled') setRatios(ratiosRes.value);
      if (healthRes.status === 'fulfilled') setHealth(healthRes.value);

      // If all failed, show error
      if (
        stmtRes.status === 'rejected' &&
        ratiosRes.status === 'rejected' &&
        healthRes.status === 'rejected'
      ) {
        setError(`Could not fetch financial data for ${sym}`);
      }
    } catch {
      setError(`Could not fetch financial data for ${sym}`);
    } finally {
      setLoading(false);
    }
  };

  // Refetch when period toggles (only if we have an active symbol)
  const handlePeriodChange = async (newPeriod: Period) => {
    setPeriod(newPeriod);
    if (!activeSymbol) return;

    setLoading(true);
    setError('');
    try {
      const [stmtRes, ratiosRes] = await Promise.allSettled([
        apiClient.get<StatementsResponse>(
          `/api/v1/financials/${encodeURIComponent(activeSymbol)}/statements`,
          { period: newPeriod }
        ),
        apiClient.get<RatiosResponse>(
          `/api/v1/financials/${encodeURIComponent(activeSymbol)}/ratios`,
          { period: newPeriod }
        ),
      ]);

      if (stmtRes.status === 'fulfilled') setStatements(stmtRes.value);
      if (ratiosRes.status === 'fulfilled') setRatios(ratiosRes.value);
    } catch {
      // keep existing data
    } finally {
      setLoading(false);
    }
  };

  /* ── Get data for the active tab ── */
  const getTabContent = () => {
    if (loading) {
      return (
        <div className="space-y-3">
          <LoadingSkeleton variant="table" lines={8} />
          <LoadingSkeleton variant="table" lines={8} />
        </div>
      );
    }

    switch (activeTab) {
      case 'income':
        return statements?.income_statement ? (
          <StatementTable data={statements.income_statement} title="Income Statement" />
        ) : (
          <EmptyTab />
        );
      case 'balance':
        return statements?.balance_sheet ? (
          <StatementTable data={statements.balance_sheet} title="Balance Sheet" />
        ) : (
          <EmptyTab />
        );
      case 'cashflow':
        return statements?.cash_flow ? (
          <StatementTable data={statements.cash_flow} title="Cash Flow Statement" />
        ) : (
          <EmptyTab />
        );
      case 'ratios':
        return ratios?.ratios ? (
          <StatementTable data={ratios.ratios} title="Financial Ratios" />
        ) : (
          <EmptyTab />
        );
      case 'health':
        return health ? (
          <HealthScoreCard
            data={{
              overall_score: health.overall_score,
              categories: health.categories,
              symbol: health.symbol,
              summary: health.summary,
            }}
          />
        ) : (
          <EmptyTab />
        );
      default:
        return null;
    }
  };

  return (
    <div className="space-y-8 animate-fadeIn">
      <Disclaimer />

      <div>
        <h1 className="font-heading text-xl font-extrabold tracking-tight text-[var(--text)]">
          Financial Statements
        </h1>
        <p className="text-sm text-[var(--text-muted)] mt-1 font-mono">
          Income statement · Balance sheet · Cash flow · Ratios · Health score
        </p>
      </div>

      {/* Search Input */}
      <form onSubmit={handleSearch} className="flex gap-3 max-w-xl">
        <input
          type="text"
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          placeholder="Enter stock symbol (e.g., RELIANCE.NS, AAPL)"
          className="flex-1 px-4 py-3 rounded-lg bg-[var(--surface)] border border-[var(--border)]
                     text-[var(--text)] font-mono text-sm placeholder:text-[var(--text-dim)]
                     focus:outline-none focus:border-[var(--accent)] focus:shadow-[0_0_0_3px_rgba(0,212,255,0.1)]
                     transition-all"
        />
        <button
          type="submit"
          disabled={loading}
          className="px-6 py-3 rounded-lg bg-[var(--accent)] text-[var(--bg)] text-sm font-bold
                     uppercase tracking-wider hover:brightness-110 transition-all cursor-pointer
                     disabled:opacity-50 flex items-center gap-2"
        >
          {loading ? 'Loading...' : 'Analyze'} <ArrowRight className="w-4 h-4" />
        </button>
      </form>

      {/* Error */}
      {error && (
        <div className="card p-6 max-w-xl border-[var(--red)]/30">
          <p className="text-sm text-[var(--red)]">{error}</p>
        </div>
      )}

      {/* Results */}
      {activeSymbol && !error && (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-4"
        >
          {/* Controls: Tabs + Period Toggle */}
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            {/* Tabs */}
            <div className="flex gap-1 overflow-x-auto">
              {TABS.map(({ key, label, icon: Icon }) => (
                <button
                  key={key}
                  onClick={() => setActiveTab(key)}
                  className={`flex items-center gap-1.5 px-3 py-2 rounded-md text-xs font-mono
                             whitespace-nowrap transition-colors cursor-pointer
                             ${
                               activeTab === key
                                 ? 'bg-[var(--accent)]/10 text-[var(--accent)] border border-[var(--accent)]/30'
                                 : 'text-[var(--text-muted)] hover:bg-[var(--surface-2)] hover:text-[var(--text)] border border-transparent'
                             }`}
                >
                  <Icon className="w-3.5 h-3.5" />
                  {label}
                </button>
              ))}
            </div>

            {/* Period Toggle */}
            {activeTab !== 'health' && (
              <div className="flex items-center gap-1 bg-[var(--surface)] border border-[var(--border)] rounded-md p-0.5">
                {(['annual', 'quarterly'] as Period[]).map((p) => (
                  <button
                    key={p}
                    onClick={() => handlePeriodChange(p)}
                    className={`px-3 py-1.5 rounded text-xs font-mono capitalize transition-colors cursor-pointer
                               ${
                                 period === p
                                   ? 'bg-[var(--accent)]/15 text-[var(--accent)]'
                                   : 'text-[var(--text-muted)] hover:text-[var(--text)]'
                               }`}
                  >
                    {p}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Tab Content */}
          <div className="max-w-5xl">{getTabContent()}</div>
        </motion.div>
      )}

      {/* Explainer cards (shown when no analysis yet) */}
      {!activeSymbol && !loading && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 max-w-3xl">
          {[
            {
              icon: FileSpreadsheet,
              title: 'Financial Statements',
              desc: 'View income statements, balance sheets, and cash flow statements with multi-period comparison',
              color: 'var(--accent)',
            },
            {
              icon: BarChart3,
              title: 'Key Ratios',
              desc: 'Profitability, liquidity, and efficiency ratios with year-over-year change tracking',
              color: 'var(--accent-green)',
            },
            {
              icon: HeartPulse,
              title: 'Health Score',
              desc: 'Composite financial health score (0–100) across profitability, solvency, efficiency, and growth',
              color: 'var(--accent-orange)',
            },
          ].map((item, i) => (
            <motion.div
              key={item.title}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 + i * 0.1 }}
              className="card p-5"
            >
              <item.icon className="w-5 h-5 mb-3" style={{ color: item.color }} />
              <h3 className="font-heading text-sm font-bold text-[var(--text)] mb-1">
                {item.title}
              </h3>
              <p className="text-xs text-[var(--text-dim)] font-mono leading-relaxed">
                {item.desc}
              </p>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}

function EmptyTab() {
  return (
    <div className="card p-8 text-center">
      <p className="text-sm text-[var(--text-dim)] font-mono">
        No data available for this section.
      </p>
    </div>
  );
}
