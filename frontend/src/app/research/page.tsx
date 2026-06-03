'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import { FileText, Sparkles, ArrowRight, Clock } from 'lucide-react';
import Disclaimer from '@/components/shared/Disclaimer';

export default function ResearchPage() {
  const [symbol, setSymbol] = useState('');
  const router = useRouter();

  const handleGenerate = (e: React.FormEvent) => {
    e.preventDefault();
    if (symbol.trim()) {
      router.push(`/markets/${encodeURIComponent(symbol.trim().toUpperCase())}`);
    }
  };

  return (
    <div className="space-y-8 animate-fadeIn">
      <Disclaimer />

      <div>
        <h1 className="font-heading text-xl font-extrabold tracking-tight text-[var(--text)]">
          AI Research Lab
        </h1>
        <p className="text-sm text-[var(--text-muted)] mt-1 font-mono">
          Generate institutional-grade AI research reports powered by Groq LLM
        </p>
      </div>

      {/* Generate Report */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="card p-6 max-w-2xl"
      >
        <div className="flex items-center gap-2 mb-4">
          <Sparkles className="w-5 h-5 text-[var(--accent)]" />
          <h2 className="font-heading text-sm font-bold uppercase tracking-wider text-[var(--text)]">
            Generate Report
          </h2>
        </div>

        <form onSubmit={handleGenerate} className="flex gap-3">
          <input
            type="text"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="Enter stock symbol (e.g., RELIANCE.NS, AAPL)"
            className="flex-1 px-4 py-3 rounded-lg bg-[var(--bg)] border border-[var(--border)]
                       text-[var(--text)] font-mono text-sm placeholder:text-[var(--text-dim)]
                       focus:outline-none focus:border-[var(--accent)] focus:shadow-[0_0_0_3px_rgba(0,212,255,0.1)]
                       transition-all"
          />
          <button
            type="submit"
            className="px-6 py-3 rounded-lg bg-[var(--accent)] text-[var(--bg)] text-sm font-bold
                       uppercase tracking-wider hover:brightness-110 transition-all cursor-pointer
                       flex items-center gap-2"
          >
            Analyze <ArrowRight className="w-4 h-4" />
          </button>
        </form>
        <p className="text-[11px] text-[var(--text-dim)] mt-3 font-mono">
          Uses Groq LLM (Llama 3.3 70B) · Data sourced from Yahoo Finance · ~15s delayed
        </p>
      </motion.div>

      {/* What&apos;s Included */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 max-w-3xl">
        {[
          { title: 'Company Analysis', desc: 'Business overview, sector positioning, competitive landscape', icon: FileText },
          { title: 'Technical Signals', desc: 'RSI, MACD, Bollinger Bands, VWAP with interpretive signals', icon: Sparkles },
          { title: 'Financial Health', desc: 'P/E, revenue growth, margins, debt ratios, ROE/ROA', icon: Clock },
        ].map((item, i) => (
          <motion.div
            key={item.title}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 + i * 0.1 }}
            className="card p-5"
          >
            <item.icon className="w-5 h-5 text-[var(--accent)] mb-3" />
            <h3 className="font-heading text-sm font-bold text-[var(--text)] mb-1">{item.title}</h3>
            <p className="text-xs text-[var(--text-dim)] font-mono leading-relaxed">{item.desc}</p>
          </motion.div>
        ))}
      </div>

      {/* Recent Reports placeholder */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.5 }}
        className="card p-8 text-center max-w-2xl"
      >
        <FileText className="w-8 h-8 text-[var(--text-dim)] mx-auto mb-3" />
        <p className="text-sm text-[var(--text-muted)]">No reports generated yet</p>
        <p className="text-xs text-[var(--text-dim)] mt-1 font-mono">
          Enter a stock symbol above to generate your first AI research report
        </p>
      </motion.div>
    </div>
  );
}
