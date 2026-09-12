'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { Search, TrendingUp, Globe } from 'lucide-react';

const POPULAR_STOCKS = {
  india: [
    { symbol: 'RELIANCE.NS', name: 'Reliance Industries' },
    { symbol: 'TCS.NS', name: 'Tata Consultancy Services' },
    { symbol: 'HDFCBANK.NS', name: 'HDFC Bank' },
    { symbol: 'INFY.NS', name: 'Infosys' },
    { symbol: 'ICICIBANK.NS', name: 'ICICI Bank' },
    { symbol: 'SBIN.NS', name: 'State Bank of India' },
    { symbol: 'BAJFINANCE.NS', name: 'Bajaj Finance' },
    { symbol: 'WIPRO.NS', name: 'Wipro' },
  ],
  us: [
    { symbol: 'AAPL', name: 'Apple Inc.' },
    { symbol: 'MSFT', name: 'Microsoft' },
    { symbol: 'GOOGL', name: 'Alphabet (Google)' },
    { symbol: 'AMZN', name: 'Amazon' },
    { symbol: 'TSLA', name: 'Tesla' },
    { symbol: 'NVDA', name: 'NVIDIA' },
    { symbol: 'META', name: 'Meta Platforms' },
    { symbol: 'NFLX', name: 'Netflix' },
  ],
};

export default function MarketsPage() {
  const [query, setQuery] = useState('');
  const router = useRouter();

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim()) {
      router.push(`/markets/${encodeURIComponent(query.trim().toUpperCase())}`);
    }
  };

  return (
    <div className="space-y-8 animate-fadeIn">
      <div>
        <h1 className="font-heading text-xl font-extrabold tracking-tight text-[var(--text)]">
          Markets Explorer
        </h1>
        <p className="text-xs text-[var(--text-muted)] mt-1 font-mono">
          Search equities & indices across NSE/BSE and NYSE/NASDAQ with real-time analytics
        </p>
      </div>

      {/* Search */}
      <form onSubmit={handleSearch} className="relative max-w-xl">
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-dim)]" />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search ticker or company (e.g., RELIANCE.NS, AAPL, TCS.NS)..."
          className="w-full pl-11 pr-24 py-3 rounded-full bg-[var(--surface)] border border-[var(--border)]
                     text-[var(--text)] font-mono text-xs placeholder:text-[var(--text-dim)]
                     focus:outline-none focus:border-[var(--green)]/50 focus:ring-1 focus:ring-[var(--green)]/30
                     transition-all shadow-inner"
        />
        <button
          type="submit"
          className="absolute right-1.5 top-1/2 -translate-y-1/2 px-4 py-1.5 rounded-full
                     bg-[var(--green)] text-black text-xs font-bold uppercase tracking-wider
                     hover:bg-[var(--green-hover)] transition-all cursor-pointer shadow-sm"
        >
          Explore
        </button>
      </form>

      {/* Indian Stocks */}
      <div>
        <div className="flex items-center gap-2 mb-4">
          <TrendingUp className="w-4 h-4 text-[var(--green)]" />
          <h2 className="font-heading text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">
            Indian Markets · NSE Top Equities
          </h2>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
          {POPULAR_STOCKS.india.map((stock, i) => {
            const tickerClean = stock.symbol.replace('.NS', '');
            const initials = tickerClean.slice(0, 2).toUpperCase();
            return (
              <motion.div
                key={stock.symbol}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.04 }}
              >
                <Link
                  href={`/markets/${encodeURIComponent(stock.symbol)}`}
                  className="card p-4 block group hover:border-[var(--green)]/40 transition-all"
                >
                  <div className="flex items-center gap-2.5 mb-2">
                    <div className="w-7 h-7 rounded-full bg-[rgba(255,255,255,0.04)] border border-[rgba(255,255,255,0.08)] flex items-center justify-center shrink-0 group-hover:border-[var(--green)]/30 transition-colors">
                      <span className="font-mono text-[10px] font-bold text-[var(--text-muted)] group-hover:text-[var(--green)]">
                        {initials}
                      </span>
                    </div>
                    <div className="font-mono text-xs font-bold text-[var(--text)] group-hover:text-white transition-colors">
                      {tickerClean}
                    </div>
                  </div>
                  <div className="text-[11px] text-[var(--text-dim)] truncate">
                    {stock.name}
                  </div>
                </Link>
              </motion.div>
            );
          })}
        </div>
      </div>

      {/* US Stocks */}
      <div>
        <div className="flex items-center gap-2 mb-4">
          <Globe className="w-4 h-4 text-[var(--text-muted)]" />
          <h2 className="font-heading text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">
            US Markets · NYSE / NASDAQ
          </h2>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
          {POPULAR_STOCKS.us.map((stock, i) => {
            const initials = stock.symbol.slice(0, 2).toUpperCase();
            return (
              <motion.div
                key={stock.symbol}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.3 + i * 0.04 }}
              >
                <Link
                  href={`/markets/${encodeURIComponent(stock.symbol)}`}
                  className="card p-4 block group hover:border-[var(--green)]/40 transition-all"
                >
                  <div className="flex items-center gap-2.5 mb-2">
                    <div className="w-7 h-7 rounded-full bg-[rgba(255,255,255,0.04)] border border-[rgba(255,255,255,0.08)] flex items-center justify-center shrink-0 group-hover:border-[var(--green)]/30 transition-colors">
                      <span className="font-mono text-[10px] font-bold text-[var(--text-muted)] group-hover:text-[var(--green)]">
                        {initials}
                      </span>
                    </div>
                    <div className="font-mono text-xs font-bold text-[var(--text)] group-hover:text-white transition-colors">
                      {stock.symbol}
                    </div>
                  </div>
                  <div className="text-[11px] text-[var(--text-dim)] truncate">
                    {stock.name}
                  </div>
                </Link>
              </motion.div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
