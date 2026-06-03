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
        <p className="text-sm text-[var(--text-muted)] mt-1 font-mono">
          Search any stock · NSE/BSE + NYSE/NASDAQ
        </p>
      </div>

      {/* Search */}
      <form onSubmit={handleSearch} className="relative max-w-xl">
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-[var(--text-dim)]" />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search stocks... (e.g., RELIANCE.NS, AAPL, TCS.NS)"
          className="w-full pl-12 pr-4 py-3 rounded-lg bg-[var(--surface)] border border-[var(--border)]
                     text-[var(--text)] font-mono text-sm placeholder:text-[var(--text-dim)]
                     focus:outline-none focus:border-[var(--accent)] focus:shadow-[0_0_0_3px_rgba(0,212,255,0.1)]
                     transition-all"
        />
        <button
          type="submit"
          className="absolute right-2 top-1/2 -translate-y-1/2 px-4 py-1.5 rounded-md
                     bg-[var(--accent)] text-[var(--bg)] text-xs font-bold uppercase tracking-wider
                     hover:brightness-110 transition-all cursor-pointer"
        >
          Go
        </button>
      </form>

      {/* Indian Stocks */}
      <div>
        <div className="flex items-center gap-2 mb-4">
          <TrendingUp className="w-4 h-4 text-[var(--accent-orange)]" />
          <h2 className="font-heading text-sm font-bold uppercase tracking-wider text-[var(--text-muted)]">
            Indian Markets · NSE
          </h2>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
          {POPULAR_STOCKS.india.map((stock, i) => (
            <motion.div
              key={stock.symbol}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05 }}
            >
              <Link
                href={`/markets/${encodeURIComponent(stock.symbol)}`}
                className="card p-4 block group hover:border-[var(--accent)] transition-colors"
              >
                <div className="font-mono text-sm font-medium text-[var(--accent)] group-hover:text-[var(--text)]">
                  {stock.symbol.replace('.NS', '')}
                </div>
                <div className="text-[11px] text-[var(--text-dim)] mt-0.5 truncate">
                  {stock.name}
                </div>
              </Link>
            </motion.div>
          ))}
        </div>
      </div>

      {/* US Stocks */}
      <div>
        <div className="flex items-center gap-2 mb-4">
          <Globe className="w-4 h-4 text-[var(--accent-purple)]" />
          <h2 className="font-heading text-sm font-bold uppercase tracking-wider text-[var(--text-muted)]">
            US Markets · NYSE/NASDAQ
          </h2>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
          {POPULAR_STOCKS.us.map((stock, i) => (
            <motion.div
              key={stock.symbol}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.4 + i * 0.05 }}
            >
              <Link
                href={`/markets/${encodeURIComponent(stock.symbol)}`}
                className="card p-4 block group hover:border-[var(--accent)] transition-colors"
              >
                <div className="font-mono text-sm font-medium text-[var(--accent)] group-hover:text-[var(--text)]">
                  {stock.symbol}
                </div>
                <div className="text-[11px] text-[var(--text-dim)] mt-0.5 truncate">
                  {stock.name}
                </div>
              </Link>
            </motion.div>
          ))}
        </div>
      </div>
    </div>
  );
}
