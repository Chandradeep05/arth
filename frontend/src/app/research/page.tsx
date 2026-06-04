'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import {
  FileText, Sparkles, ArrowRight, Clock, BookOpen, Database,
  Loader2, CheckCircle, AlertCircle,
} from 'lucide-react';
import Disclaimer from '@/components/shared/Disclaimer';
import CitedReport from '@/components/research/CitedReport';
import { apiClient } from '@/lib/api';

type ResearchMode = 'standard' | 'deep';

interface DeepReportData {
  report_content: string;
  company_name: string;
  sources: { id: number; title: string; source: string; date: string; type: string; url?: string; relevance?: number }[];
  chunks_retrieved: number;
  confidence_score: number;
  generated_at: string;
}

interface SourcesData {
  document_count: number;
  sources: { source: string; type: string; date: string }[];
  has_documents: boolean;
}

export default function ResearchPage() {
  const [symbol, setSymbol] = useState('');
  const [mode, setMode] = useState<ResearchMode>('standard');
  const router = useRouter();

  // Deep research state
  const [indexing, setIndexing] = useState(false);
  const [indexed, setIndexed] = useState(false);
  const [indexedCount, setIndexedCount] = useState(0);
  const [generating, setGenerating] = useState(false);
  const [deepReport, setDeepReport] = useState<DeepReportData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sourcesInfo, setSourcesInfo] = useState<SourcesData | null>(null);

  const handleStandardGenerate = (e: React.FormEvent) => {
    e.preventDefault();
    if (symbol.trim()) {
      router.push(`/markets/${encodeURIComponent(symbol.trim().toUpperCase())}`);
    }
  };

  const checkSources = async (sym: string) => {
    try {
      const res = await apiClient.get<{ success: boolean; data: SourcesData }>(
        `/api/v1/research/sources/${encodeURIComponent(sym)}`
      );
      if (res.success && res.data.has_documents) {
        setSourcesInfo(res.data);
        setIndexed(true);
        setIndexedCount(res.data.document_count);
      }
    } catch {
      // Not indexed yet — that's fine
    }
  };

  const handleIndex = async () => {
    if (!symbol.trim()) return;
    const sym = symbol.trim().toUpperCase();
    setIndexing(true);
    setError(null);

    try {
      const res = await apiClient.post<{ success: boolean; data: { documents_indexed: number; sources: any[] }; message?: string }>(
        `/api/v1/research/index/${encodeURIComponent(sym)}`,
        {}
      );
      if (res.success) {
        setIndexed(true);
        setIndexedCount(res.data.documents_indexed);
        await checkSources(sym);
      } else {
        setError(res.message || 'Indexing failed');
      }
    } catch (err: any) {
      setError(err.message || 'Indexing failed');
    } finally {
      setIndexing(false);
    }
  };

  const handleDeepGenerate = async () => {
    if (!symbol.trim()) return;
    const sym = symbol.trim().toUpperCase();
    setGenerating(true);
    setError(null);
    setDeepReport(null);

    try {
      const res = await apiClient.post<{ success: boolean; data: DeepReportData; message?: string }>(
        `/api/v1/research/generate/${encodeURIComponent(sym)}?depth=deep&stream=false`,
        {}
      );
      if (res.success) {
        setDeepReport(res.data);
      } else {
        setError(res.message || 'Generation failed');
      }
    } catch (err: any) {
      setError(err.message || 'Generation failed');
    } finally {
      setGenerating(false);
    }
  };

  const resetDeepState = () => {
    setIndexed(false);
    setIndexedCount(0);
    setDeepReport(null);
    setError(null);
    setSourcesInfo(null);
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

      {/* Mode Toggle */}
      <div className="flex gap-2">
        {[
          { key: 'standard' as const, label: 'Standard Research', icon: Sparkles },
          { key: 'deep' as const, label: 'Deep Research (RAG)', icon: BookOpen },
        ].map((m) => (
          <button
            key={m.key}
            onClick={() => { setMode(m.key); resetDeepState(); }}
            className={`px-4 py-2 rounded-lg text-xs font-bold uppercase tracking-wider flex items-center gap-2
                        transition-all cursor-pointer border ${
              mode === m.key
                ? 'bg-[var(--accent)]/10 border-[var(--accent)] text-[var(--accent)]'
                : 'bg-[var(--surface)] border-[var(--border)] text-[var(--text-muted)] hover:border-[var(--border-bright)]'
            }`}
          >
            <m.icon className="w-3.5 h-3.5" />
            {m.label}
          </button>
        ))}
      </div>

      {/* Standard Research Mode */}
      {mode === 'standard' && (
        <>
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

            <form onSubmit={handleStandardGenerate} className="flex gap-3">
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

          {/* What's Included */}
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
        </>
      )}

      {/* Deep Research Mode (RAG) */}
      {mode === 'deep' && (
        <>
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            className="card p-6 max-w-2xl"
          >
            <div className="flex items-center gap-2 mb-4">
              <BookOpen className="w-5 h-5 text-[var(--accent-purple)]" />
              <h2 className="font-heading text-sm font-bold uppercase tracking-wider text-[var(--text)]">
                Deep Research with Citations
              </h2>
              <span className="badge badge-purple text-[10px] font-mono ml-auto">RAG-Powered</span>
            </div>

            <p className="text-xs text-[var(--text-muted)] font-mono mb-4 leading-relaxed">
              Indexes company documents (news, financials, description) into a vector store,
              then generates a cited research report backed by multiple sources.
            </p>

            {/* Step 1: Enter Symbol */}
            <div className="flex gap-3 mb-4">
              <input
                type="text"
                value={symbol}
                onChange={(e) => { setSymbol(e.target.value); resetDeepState(); }}
                placeholder="Enter stock symbol (e.g., RELIANCE.NS)"
                className="flex-1 px-4 py-3 rounded-lg bg-[var(--bg)] border border-[var(--border)]
                           text-[var(--text)] font-mono text-sm placeholder:text-[var(--text-dim)]
                           focus:outline-none focus:border-[var(--accent)] focus:shadow-[0_0_0_3px_rgba(0,212,255,0.1)]
                           transition-all"
              />
            </div>

            {/* Step 2: Index Documents */}
            {!indexed && !deepReport && (
              <button
                onClick={handleIndex}
                disabled={indexing || !symbol.trim()}
                className="w-full px-4 py-3 rounded-lg border border-[var(--accent-purple)]/30 text-sm
                           font-bold text-[var(--accent-purple)] hover:bg-[var(--accent-purple)]/5
                           transition-all cursor-pointer flex items-center justify-center gap-2
                           disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {indexing ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Indexing documents...
                  </>
                ) : (
                  <>
                    <Database className="w-4 h-4" />
                    Index Documents for {symbol.trim().toUpperCase() || '...'}
                  </>
                )}
              </button>
            )}

            {/* Step 3: Indexed — Show Generate */}
            {indexed && !deepReport && (
              <div className="space-y-3">
                <div className="flex items-center gap-2 p-3 rounded-lg bg-[var(--accent-green)]/5 border border-[var(--accent-green)]/20">
                  <CheckCircle className="w-4 h-4 text-[var(--accent-green)]" />
                  <span className="text-xs font-mono text-[var(--accent-green)]">
                    {indexedCount} documents indexed successfully
                  </span>
                </div>
                <button
                  onClick={handleDeepGenerate}
                  disabled={generating}
                  className="w-full px-4 py-3 rounded-lg bg-[var(--accent-purple)] text-white text-sm
                             font-bold uppercase tracking-wider hover:brightness-110 transition-all
                             cursor-pointer flex items-center justify-center gap-2
                             disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  {generating ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Generating deep research...
                    </>
                  ) : (
                    <>
                      <Sparkles className="w-4 h-4" />
                      Generate Deep Research
                    </>
                  )}
                </button>
              </div>
            )}

            {/* Error Display */}
            {error && (
              <div className="flex items-center gap-2 p-3 rounded-lg bg-[var(--red)]/5 border border-[var(--red)]/20 mt-3">
                <AlertCircle className="w-4 h-4 text-[var(--red)]" />
                <span className="text-xs font-mono text-[var(--red)]">{error}</span>
              </div>
            )}
          </motion.div>

          {/* Deep Research Features */}
          {!deepReport && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 max-w-3xl">
              {[
                { title: 'Multi-Source Analysis', desc: 'Company info, news, financials, and sector context indexed', icon: Database },
                { title: 'Inline Citations', desc: 'Every claim backed by [SOURCE N] references you can verify', icon: BookOpen },
                { title: 'Higher Confidence', desc: 'RAG grounding reduces hallucination, increases accuracy', icon: CheckCircle },
              ].map((item, i) => (
                <motion.div
                  key={item.title}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.2 + i * 0.1 }}
                  className="card p-5"
                >
                  <item.icon className="w-5 h-5 text-[var(--accent-purple)] mb-3" />
                  <h3 className="font-heading text-sm font-bold text-[var(--text)] mb-1">{item.title}</h3>
                  <p className="text-xs text-[var(--text-dim)] font-mono leading-relaxed">{item.desc}</p>
                </motion.div>
              ))}
            </div>
          )}

          {/* Deep Report Display */}
          {deepReport && (
            <CitedReport
              content={deepReport.report_content}
              sources={deepReport.sources}
              companyName={deepReport.company_name}
            />
          )}
        </>
      )}
    </div>
  );
}
