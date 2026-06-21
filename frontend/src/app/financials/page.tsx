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

/* ── Interfaces matching actual backend response ── */
// Backend returns: { success: true, data: { income_statement: { annual: [...], quarterly: [...] }, ... } }
interface StatementData {
  annual: StatementPeriod[];
  quarterly: StatementPeriod[];
}

interface StatementsData {
  symbol: string;
  income_statement: StatementData;
  balance_sheet: StatementData;
  cash_flow: StatementData;
}

interface StatementsApiResponse {
  success: boolean;
  data: StatementsData;
}

interface RatiosApiResponse {
  success: boolean;
  data: {
    symbol: string;
    ratios: Record<string, { value: number | null; previous: number | null; change: number | null; direction: string }>;
    periods_compared: { current: string | null; previous: string | null };
  };
}

interface HealthApiResponse {
  success: boolean;
  data: {
    symbol: string;
    total_score: number;
    label: string;
    breakdown: Record<string, { score: number; factors: string[] }>;
  };
}

/* ── Helper: convert backend statement periods to table-friendly format ── */
function statementsToTable(periods: StatementPeriod[] | undefined): StatementPeriod[] {
  if (!periods || !Array.isArray(periods)) return [];
  // Each period has { period: "2024-03-31", items: { "Total Revenue": 123, ... } }
  // StatementTable expects StatementPeriod[] with { period, ...lineItems }
  return periods.map((p) => {
    const row: StatementPeriod = { period: p.period };
    const items = (p as Record<string, unknown>).items;
    if (items && typeof items === 'object') {
      for (const [key, val] of Object.entries(items as Record<string, unknown>)) {
        row[key] = val as string | number | null;
      }
    }
    return row;
  });
}

/* ── Helper: convert ratios dict to table-friendly format ── */
function ratiosToTable(ratios: Record<string, unknown> | undefined): StatementPeriod[] {
  if (!ratios || typeof ratios !== 'object') return [];
  const row: StatementPeriod = { period: 'Current' };
  const prevRow: StatementPeriod = { period: 'Previous' };
  let hasPrev = false;
  for (const [key, val] of Object.entries(ratios)) {
    const trend = val as { value?: number | null; previous?: number | null; direction?: string } | null;
    if (trend && typeof trend === 'object') {
      const label = key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
      row[label] = trend.value ?? null;
      if (trend.previous !== null && trend.previous !== undefined) {
        prevRow[label] = trend.previous;
        hasPrev = true;
      }
    }
  }
  return hasPrev ? [row, prevRow] : [row];
}

/* ── Page Component ── */
export default function FinancialsPage() {
  const [symbol, setSymbol] = useState('');
  const [activeSymbol, setActiveSymbol] = useState('');
  const [activeTab, setActiveTab] = useState<TabKey>('income');
  const [period, setPeriod] = useState<Period>('annual');

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const [statementsData, setStatementsData] = useState<StatementsData | null>(null);
  const [ratiosData, setRatiosData] = useState<RatiosApiResponse['data'] | null>(null);
  const [healthData, setHealthData] = useState<HealthApiResponse['data'] | null>(null);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    const sym = symbol.trim().toUpperCase();
    if (!sym) return;

    setLoading(true);
    setError('');
    setStatementsData(null);
    setRatiosData(null);
    setHealthData(null);
    setActiveSymbol(sym);

    try {
      // Fetch all three in parallel
      const [stmtRes, ratiosRes, healthRes] = await Promise.allSettled([
        apiClient.get<StatementsApiResponse>(
          `/api/v1/financials/${encodeURIComponent(sym)}/statements`,
          { period }
        ),
        apiClient.get<RatiosApiResponse>(
          `/api/v1/financials/${encodeURIComponent(sym)}/ratios`,
          { period }
        ),
        apiClient.get<HealthApiResponse>(
          `/api/v1/financials/${encodeURIComponent(sym)}/health-score`
        ),
      ]);

      if (stmtRes.status === 'fulfilled' && stmtRes.value?.data) {
        setStatementsData(stmtRes.value.data);
      }
      if (ratiosRes.status === 'fulfilled' && ratiosRes.value?.data) {
        setRatiosData(ratiosRes.value.data);
      }
      if (healthRes.status === 'fulfilled' && healthRes.value?.data) {
        setHealthData(healthRes.value.data);
      }

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
        apiClient.get<StatementsApiResponse>(
          `/api/v1/financials/${encodeURIComponent(activeSymbol)}/statements`,
          { period: newPeriod }
        ),
        apiClient.get<RatiosApiResponse>(
          `/api/v1/financials/${encodeURIComponent(activeSymbol)}/ratios`,
          { period: newPeriod }
        ),
      ]);

      if (stmtRes.status === 'fulfilled' && stmtRes.value?.data) {
        setStatementsData(stmtRes.value.data);
      }
      if (ratiosRes.status === 'fulfilled' && ratiosRes.value?.data) {
        setRatiosData(ratiosRes.value.data);
      }
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

    // Get the correct period data (annual or quarterly)
    const incomeData = statementsData?.income_statement?.[period];
    const balanceData = statementsData?.balance_sheet?.[period];
    const cashflowData = statementsData?.cash_flow?.[period];

    switch (activeTab) {
      case 'income': {
        const rows = statementsToTable(incomeData);
        return rows.length > 0 ? (
          <StatementTable data={rows} title="Income Statement" />
        ) : (
          <EmptyTab />
        );
      }
      case 'balance': {
        const rows = statementsToTable(balanceData);
        return rows.length > 0 ? (
          <StatementTable data={rows} title="Balance Sheet" />
        ) : (
          <EmptyTab />
        );
      }
      case 'cashflow': {
        const rows = statementsToTable(cashflowData);
        return rows.length > 0 ? (
          <StatementTable data={rows} title="Cash Flow Statement" />
        ) : (
          <EmptyTab />
        );
      }
      case 'ratios': {
        const rows = ratiosToTable(ratiosData?.ratios as Record<string, unknown> | undefined);
        return rows.length > 0 ? (
          <StatementTable data={rows} title="Financial Ratios" />
        ) : (
          <EmptyTab />
        );
      }
      case 'health':
        return healthData ? (
          <HealthScoreCard
            data={{
              overall_score: healthData.total_score,
              categories: Object.entries(healthData.breakdown).map(([name, d]) => ({
                name: name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
                score: d.score,
              })),
              symbol: healthData.symbol,
              summary: healthData.label,
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
