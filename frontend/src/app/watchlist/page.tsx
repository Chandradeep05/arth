'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { motion } from 'framer-motion';
import { Star, Plus, Search, RefreshCw, Wifi, WifiOff } from 'lucide-react';
import { apiClient } from '@/lib/api';
import { useWebSocket } from '@/lib/useWebSocket';
import Disclaimer from '@/components/shared/Disclaimer';
import LoadingSkeleton from '@/components/shared/LoadingSkeleton';
import WatchlistTable, {
  type WatchlistItem,
  type SortField,
  type SortDir,
} from '@/components/watchlist/WatchlistTable';

/* ── Constants ── */
const LS_KEY = 'arth_watchlist';
const DEFAULT_SYMBOLS = ['RELIANCE.NS', 'TCS.NS', 'INFY.NS'];
const REFRESH_INTERVAL = 30_000; // 30 seconds

/* ── LocalStorage helpers ── */
function loadWatchlist(): string[] {
  if (typeof window === 'undefined') return DEFAULT_SYMBOLS;
  try {
    const stored = localStorage.getItem(LS_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);
      if (Array.isArray(parsed) && parsed.length > 0) return parsed;
    }
  } catch {
    // Ignore parse errors
  }
  // First visit: set defaults
  localStorage.setItem(LS_KEY, JSON.stringify(DEFAULT_SYMBOLS));
  return DEFAULT_SYMBOLS;
}

function saveWatchlist(symbols: string[]) {
  if (typeof window !== 'undefined') {
    localStorage.setItem(LS_KEY, JSON.stringify(symbols));
  }
}

/* ── Sorting ── */
function sortItems(items: WatchlistItem[], field: SortField, dir: SortDir): WatchlistItem[] {
  return [...items].sort((a, b) => {
    let cmp = 0;
    switch (field) {
      case 'symbol':
        cmp = a.symbol.localeCompare(b.symbol);
        break;
      case 'name':
        cmp = (a.name || '').localeCompare(b.name || '');
        break;
      case 'price':
        cmp = (a.price ?? 0) - (b.price ?? 0);
        break;
      case 'change_percent':
        cmp = (a.change_percent ?? 0) - (b.change_percent ?? 0);
        break;
      case 'risk_score':
        cmp = (a.risk_score ?? 0) - (b.risk_score ?? 0);
        break;
      case 'sentiment': {
        const order: Record<string, number> = { bullish: 3, neutral: 2, bearish: 1 };
        cmp = (order[a.sentiment ?? ''] ?? 0) - (order[b.sentiment ?? ''] ?? 0);
        break;
      }
    }
    return dir === 'asc' ? cmp : -cmp;
  });
}

/* ── Page Component ── */
export default function WatchlistPage() {
  const [symbols, setSymbols] = useState<string[]>([]);
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [addInput, setAddInput] = useState('');
  const [sortBy, setSortBy] = useState<SortField>('symbol');
  const [sortDir, setSortDir] = useState<SortDir>('asc');

  const refreshTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // WebSocket for real-time updates
  const { status: wsStatus, prices, subscribe, unsubscribe } = useWebSocket();

  /* ── Load watchlist on mount ── */
  useEffect(() => {
    const loaded = loadWatchlist();
    setSymbols(loaded);
  }, []);

  /* ── Batch fetch data ── */
  const fetchBatchData = useCallback(
    async (syms: string[]) => {
      if (syms.length === 0) {
        setItems([]);
        setLoading(false);
        return;
      }

      try {
        const res = await apiClient.post<{ success: boolean; data: any[] }>(
          '/api/v1/watchlist/batch',
          { symbols: syms }
        );
        // Backend returns nested { quote: { price, name, ... }, risk_score, sentiment_label }
        // Map to flat WatchlistItem shape
        const mapped: WatchlistItem[] = (res.data ?? []).map((item: any) => ({
          symbol: item.symbol,
          name: item.quote?.name || item.symbol.replace('.NS', '').replace('.BO', ''),
          price: item.quote?.price ?? 0,
          change_percent: item.quote?.change_percent ?? 0,
          risk_score: item.risk_score,
          risk_label: item.risk_label,
          sentiment: item.sentiment_label,
        }));
        setItems(mapped);
        setError('');
      } catch {
        // If batch fails, create skeleton items from symbols
        setItems(
          syms.map((s) => ({
            symbol: s,
            name: '',
            price: 0,
            change_percent: 0,
          }))
        );
        setError('Could not fetch watchlist data. Showing symbols only.');
      } finally {
        setLoading(false);
      }
    },
    []
  );

  /* ── Fetch when symbols change ── */
  useEffect(() => {
    if (symbols.length > 0) {
      setLoading(true);
      fetchBatchData(symbols);
    } else {
      setItems([]);
      setLoading(false);
    }
  }, [symbols, fetchBatchData]);

  /* ── Subscribe to WebSocket for price updates ── */
  useEffect(() => {
    if (symbols.length > 0) {
      subscribe(symbols);
    }
    return () => {
      if (symbols.length > 0) {
        unsubscribe(symbols);
      }
    };
  }, [symbols, subscribe, unsubscribe]);

  /* ── Merge WS price updates into items ── */
  useEffect(() => {
    if (prices.size === 0) return;
    setItems((prev) =>
      prev.map((item) => {
        const update = prices.get(item.symbol);
        if (!update) return item;
        return {
          ...item,
          price: update.price,
          change_percent: update.change_percent,
        };
      })
    );
  }, [prices]);

  /* ── Auto-refresh every 30s ── */
  useEffect(() => {
    refreshTimerRef.current = setInterval(() => {
      if (symbols.length > 0) {
        fetchBatchData(symbols);
      }
    }, REFRESH_INTERVAL);

    return () => {
      if (refreshTimerRef.current) {
        clearInterval(refreshTimerRef.current);
      }
    };
  }, [symbols, fetchBatchData]);

  /* ── Add symbol ── */
  const handleAdd = (e: React.FormEvent) => {
    e.preventDefault();
    const sym = addInput.trim().toUpperCase();
    if (!sym) return;
    if (symbols.includes(sym)) {
      setAddInput('');
      return;
    }
    const updated = [...symbols, sym];
    setSymbols(updated);
    saveWatchlist(updated);
    setAddInput('');
  };

  /* ── Remove symbol ── */
  const handleRemove = (sym: string) => {
    const updated = symbols.filter((s) => s !== sym);
    setSymbols(updated);
    saveWatchlist(updated);
    setItems((prev) => prev.filter((i) => i.symbol !== sym));
  };

  /* ── Sort toggle ── */
  const handleSort = (field: SortField) => {
    if (sortBy === field) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortBy(field);
      setSortDir('asc');
    }
  };

  /* ── Manual refresh ── */
  const handleRefresh = () => {
    if (symbols.length > 0) {
      setLoading(true);
      fetchBatchData(symbols);
    }
  };

  const sortedItems = sortItems(items, sortBy, sortDir);

  return (
    <div className="space-y-8 animate-fadeIn">
      <Disclaimer />

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="font-heading text-xl font-extrabold tracking-tight text-[var(--text)]">
            Watchlist
          </h1>
          <p className="text-sm text-[var(--text-muted)] mt-1 font-mono">
            Track your portfolio · Real-time updates · {symbols.length} symbol
            {symbols.length !== 1 ? 's' : ''}
          </p>
        </div>

        <div className="flex items-center gap-2">
          {/* WS status indicator */}
          <div
            className="flex items-center gap-1 text-[10px] font-mono"
            title={`WebSocket: ${wsStatus}`}
          >
            {wsStatus === 'connected' ? (
              <>
                <Wifi className="w-3 h-3 text-[var(--green)]" />
                <span className="text-[var(--green)]">LIVE</span>
              </>
            ) : (
              <>
                <WifiOff className="w-3 h-3 text-[var(--text-dim)]" />
                <span className="text-[var(--text-dim)]">{wsStatus.toUpperCase()}</span>
              </>
            )}
          </div>

          {/* Refresh button */}
          <button
            onClick={handleRefresh}
            disabled={loading}
            className="p-2 rounded-md hover:bg-[var(--surface-2)] text-[var(--text-muted)]
                       hover:text-[var(--text)] transition-colors cursor-pointer disabled:opacity-50"
            aria-label="Refresh watchlist"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Quick Add Input */}
      <form onSubmit={handleAdd} className="flex gap-3 max-w-md">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-dim)]" />
          <input
            type="text"
            value={addInput}
            onChange={(e) => setAddInput(e.target.value)}
            placeholder="Add symbol (e.g., HDFC.NS, GOOGL)"
            className="w-full pl-10 pr-4 py-3 rounded-lg bg-[var(--surface)] border border-[var(--border)]
                       text-[var(--text)] font-mono text-sm placeholder:text-[var(--text-dim)]
                       focus:outline-none focus:border-[var(--accent)] focus:shadow-[0_0_0_3px_rgba(0,212,255,0.1)]
                       transition-all"
          />
        </div>
        <button
          type="submit"
          className="px-4 py-3 rounded-lg bg-[var(--accent)] text-[var(--bg)] text-sm font-bold
                     uppercase tracking-wider hover:brightness-110 transition-all cursor-pointer
                     flex items-center gap-1.5"
        >
          <Plus className="w-4 h-4" /> Add
        </button>
      </form>

      {/* Error */}
      {error && (
        <div className="card p-4 max-w-xl border-[var(--accent-orange)]/30">
          <p className="text-xs text-[var(--accent-orange)] font-mono">{error}</p>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="space-y-2">
          <LoadingSkeleton variant="table" lines={5} />
        </div>
      )}

      {/* Watchlist Table */}
      {!loading && sortedItems.length > 0 && (
        <WatchlistTable
          items={sortedItems}
          onRemove={handleRemove}
          sortBy={sortBy}
          sortDir={sortDir}
          onSort={handleSort}
        />
      )}

      {/* Empty State */}
      {!loading && symbols.length === 0 && (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          className="card p-12 text-center max-w-xl mx-auto"
        >
          <Star className="w-10 h-10 text-[var(--text-dim)] mx-auto mb-4" />
          <h3 className="font-heading text-lg font-bold text-[var(--text)] mb-2">
            Your watchlist is empty
          </h3>
          <p className="text-sm text-[var(--text-dim)] font-mono">
            Search for stocks to add them to your watchlist.
          </p>
        </motion.div>
      )}
    </div>
  );
}
