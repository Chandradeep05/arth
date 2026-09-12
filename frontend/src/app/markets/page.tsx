'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { Search, TrendingUp, Globe } from 'lucide-react';
import { useStockAtmosphere } from '@/lib/atmosphere';

const POPULAR_STOCKS = {
  india: [
    { symbol: 'NIFTY', name: 'NIFTY 50 Benchmark' },
    { symbol: 'RELIANCE.NS', name: 'Reliance Industries' },
    { symbol: 'TCS.NS', name: 'Tata Consultancy Services' },
    { symbol: 'HDFCBANK.NS', name: 'HDFC Bank' },
    { symbol: 'INFY.NS', name: 'Infosys' },
    { symbol: 'ICICIBANK.NS', name: 'ICICI Bank' },
    { symbol: 'SBIN.NS', name: 'State Bank of India' },
    { symbol: 'BAJFINANCE.NS', name: 'Bajaj Finance' },
  ],
  us: [
    { symbol: 'AAPL', name: 'Apple Inc.' },
    { symbol: 'NVDA', name: 'NVIDIA Corporation' },
    { symbol: 'MSFT', name: 'Microsoft Corporation' },
    { symbol: 'GOOGL', name: 'Alphabet (Google)' },
    { symbol: 'AMZN', name: 'Amazon.com Inc.' },
    { symbol: 'TSLA', name: 'Tesla, Inc.' },
    { symbol: 'META', name: 'Meta Platforms' },
    { symbol: 'NFLX', name: 'Netflix Inc.' },
  ],
};

function AtmosphericMarketCard({
  symbol,
  name,
  index,
}: {
  symbol: string;
  name: string;
  index: number;
}) {
  const atmosphere = useStockAtmosphere(symbol);
  const tickerClean = symbol.replace('.NS', '').replace('.BO', '');
  const initials = tickerClean.slice(0, 2).toUpperCase();

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.04 }}
    >
      <Link
        href={`/markets/${encodeURIComponent(symbol)}`}
        className="card p-4 block group hover:border-white/[0.14] transition-all relative overflow-hidden"
      >
        <div className={`card-atmosphere ${atmosphere}`} aria-hidden="true" />
        <div className="relative z-10">
          <div className="flex items-center gap-2.5 mb-2">
            <div className="w-7 h-7 rounded-full bg-white/[0.04] border border-white/[0.08] flex items-center justify-center shrink-0 group-hover:border-emerald-500/30 transition-colors">
              <span className="font-mono text-[10px] font-bold text-[var(--text-muted)] group-hover:text-emerald-400">
                {initials}
              </span>
            </div>
            <div className="font-mono text-xs font-bold text-white group-hover:text-white transition-colors">
              {tickerClean}
            </div>
          </div>
          <div className="text-[11px] text-[var(--text-dim)] truncate font-mono">
            {name}
          </div>
        </div>
      </Link>
    </motion.div>
  );
}

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
    <div className="space-y-6 animate-fadeIn pb-8">
      <div>
        <h1 className="font-heading text-xl font-bold tracking-tight text-white">
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
          className="w-full pl-11 pr-24 py-3 rounded-full bg-[rgba(12,18,15,0.72)] border border-white/[0.07]
                     text-white font-mono text-xs placeholder:text-[var(--text-dim)]
                     focus:outline-none focus:border-emerald-500/50 focus:ring-1 focus:ring-emerald-500/30
                     transition-all shadow-inner"
        />
        <button
          type="submit"
          className="absolute right-1.5 top-1/2 -translate-y-1/2 px-4 py-1.5 rounded-full
                     bg-emerald-400 text-black text-xs font-bold uppercase tracking-wider
                     hover:bg-emerald-300 transition-all cursor-pointer shadow-sm"
        >
          Explore
        </button>
      </form>

      {/* Indian Stocks */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          <TrendingUp className="w-4 h-4 text-emerald-400" />
          <h2 className="font-heading text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">
            Indian Markets · NSE Top Equities & Indices
          </h2>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
          {POPULAR_STOCKS.india.map((stock, i) => (
            <AtmosphericMarketCard
              key={stock.symbol}
              symbol={stock.symbol}
              name={stock.name}
              index={i}
            />
          ))}
        </div>
      </div>

      {/* US Stocks */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          <Globe className="w-4 h-4 text-[var(--text-muted)]" />
          <h2 className="font-heading text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">
            US Markets · NYSE / NASDAQ
          </h2>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
          {POPULAR_STOCKS.us.map((stock, i) => (
            <AtmosphericMarketCard
              key={stock.symbol}
              symbol={stock.symbol}
              name={stock.name}
              index={i + 4}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
