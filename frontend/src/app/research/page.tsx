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
import { useAuth } from '@/lib/auth/AuthProvider';
import { useAuthenticatedApi } from '@/lib/auth/useAuthenticatedApi';
import { Save } from 'lucide-react';

type ResearchMode = 'standard' | 'deep';

interface DeepReportData {
  report_content: string;
  company_name: string;
  sources: { id: number; title: string; source: string; date: string; type: string; url?: string; relevance?: number }[];
  chunks_retrieved: number;
  evidence_strength: number;
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

  // Save state
  const { user } = useAuth();
  const authApi = useAuthenticatedApi();
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const handleSaveReport = async () => {
    if (!deepReport || !authApi.isAuthenticated) return;
    setSaving(true);
    try {
      await authApi.post('/api/v1/user/research/saved', {
        symbol: symbol.trim().toUpperCase(),
        title: `Deep Research — ${deepReport.company_name}`,
        report_content: { text: deepReport.report_content },
        sources: deepReport.sources,
        generated_at: deepReport.generated_at,
        engine_version: 'ARTH Research v1',
      });
      setSaved(true);
    } catch (err: any) {
      setError(err.message || 'Failed to save report');
    } finally {
      setSaving(false);
    }
  };

  const handleStandardGenerate = (e: React.FormEvent) => {
    e.preventDefault();
    if (symbol.trim()) {
      router.push(`/markets/${encodeURIComponent(symbol.trim().toUpperCase())}`);
    }
  };

  const checkSources = async (sym: string) => {
    try {
      const res = await authApi.get<{ success: boolean; data: SourcesData }>(
        `/api/v1/research/sources/${encodeURIComponent(sym)}`
      );
      if (res?.success && res.data?.has_documents) {
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
      if (!authApi.isAuthenticated) {
        setError('Sign in to use deep research indexing.');
        setIndexing(false);
        return;
      }
      const res = await authApi.post<{ success: boolean; data: { documents_indexed: number; sources: any[] }; message?: string }>(
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
      if (err.status === 401) {
        setError('Sign in to use deep research indexing.');
      } else {
        setError(err.message || 'Indexing failed');
      }
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
    setSaved(false);

    try {
      if (!authApi.isAuthenticated) {
        setError('Sign in to generate research reports.');
        setGenerating(false);
        return;
      }
      const res = await authApi.post<{ success: boolean; data: DeepReportData; message?: string }>(
        `/api/v1/research/generate/${encodeURIComponent(sym)}?depth=deep&stream=false`,
        {}
      );
      if (res.success) {
        setDeepReport(res.data);
      } else {
        setError(res.message || 'Generation failed');
      }
    } catch (err: any) {
      if (err.status === 401) {
        setError('Sign in to generate research reports.');
      } else {
        setError(err.message || 'Generation failed');
      }
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
          Generate institutional-grade AI research reports powered by ARTH AI
        </p>
      </div>

      {/* Mode Toggle */}
      <div className="flex gap-2">
        {[
          { key: 'standard' as const, label: 'Standard Research', icon: Sparkles },
          { key: 'deep' as const, label: 'Deep Research (RAG)', icon: BookOpen },
        ].map((m) => {
          const isActive = mode === m.key;
          return (
            <button
              key={m.key}
              onClick={() => { setMode(m.key); resetDeepState(); }}
              className={`px-4 py-2 rounded-full text-xs font-semibold tracking-wider flex items-center gap-2
                          transition-all cursor-pointer border ${
                isActive
                  ? 'bg-[rgba(16,185,129,0.12)] border-[rgba(16,185,129,0.3)] text-[var(--green)] shadow-[0_0_12px_rgba(16,185,129,0.1)]'
                  : 'bg-[rgba(255,255,255,0.03)] border-[rgba(255,255,255,0.06)] text-[var(--text-muted)] hover:text-white hover:bg-[rgba(255,255,255,0.06)]'
              }`}
            >
              <m.icon className="w-3.5 h-3.5" />
              {m.label}
            </button>
          );
        })}
      </div>

      {/* Standard Research Mode */}
      {mode === 'standard' && (
        <>
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            className="card p-6 max-w-2xl relative overflow-hidden"
          >
            <div className="card-atmosphere card-atmosphere-intelligence" style={{ opacity: 0.05 }} aria-hidden="true" />
            <div className="relative z-10">
              <div className="flex items-center gap-2 mb-4">
                <Sparkles className="w-4 h-4 text-[var(--green)]" />
                <h2 className="font-heading text-xs font-bold uppercase tracking-wider text-[var(--text)]">
                  Generate Institutional Report
                </h2>
              </div>

              <form onSubmit={handleStandardGenerate} className="flex gap-2 relative">
                <input
                  type="text"
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value)}
                  placeholder="Enter stock symbol (e.g., RELIANCE.NS, AAPL, NVDA)"
                  className="flex-1 px-4 py-3 rounded-full bg-[var(--surface-2)] border border-[var(--border)]
                             text-[var(--text)] font-mono text-xs placeholder:text-[var(--text-dim)]
                             focus:outline-none focus:border-[var(--green)]/50 focus:ring-1 focus:ring-[var(--green)]/30
                             transition-all"
                />
                <button
                  type="submit"
                  className="px-5 py-2.5 rounded-full bg-[var(--green)] text-black text-xs font-bold
                             uppercase tracking-wider hover:bg-[var(--green-hover)] transition-all cursor-pointer
                             flex items-center gap-2 shadow-sm"
                >
                  Analyze <ArrowRight className="w-3.5 h-3.5" />
                </button>
              </form>
              <p className="text-[11px] text-[var(--text-dim)] mt-3 font-mono">
                Powered by ARTH AI · Sourced from institutional filings & real-time feeds
              </p>
            </div>
          </motion.div>

          {/* What's Included */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 max-w-3xl">
            {[
              { title: 'Company Analysis', desc: 'Business overview, sector positioning, competitive moat analysis', icon: FileText },
              { title: 'Technical Signals', desc: 'RSI, MACD, Bollinger Bands, VWAP with algorithmic trade signals', icon: Sparkles },
              { title: 'Financial Health', desc: 'Multi-period balance sheet analysis, cash flows, valuation multiples', icon: Clock },
            ].map((item, i) => (
              <motion.div
                key={item.title}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.2 + i * 0.1 }}
                className="card p-5"
              >
                <item.icon className="w-4 h-4 text-[var(--green)] mb-3" />
                <h3 className="font-heading text-xs font-bold text-[var(--text)] mb-1">{item.title}</h3>
                <p className="text-[11px] text-[var(--text-dim)] font-mono leading-relaxed">{item.desc}</p>
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
              <BookOpen className="w-4 h-4 text-[var(--green)]" />
              <h2 className="font-heading text-xs font-bold uppercase tracking-wider text-[var(--text)]">
                Deep Research with Citations
              </h2>
              <span className="badge badge-green text-[10px] font-mono ml-auto">RAG Grounded</span>
            </div>

            <p className="text-xs text-[var(--text-muted)] font-mono mb-4 leading-relaxed">
              Indexes corporate filings, quarterly releases, and financial metrics into a vector store,
              then synthesizes a cited research report with strict source verification.
            </p>

            {/* Step 1: Enter Symbol */}
            <div className="flex gap-3 mb-4">
              <input
                type="text"
                value={symbol}
                onChange={(e) => { setSymbol(e.target.value); resetDeepState(); }}
                placeholder="Enter stock symbol (e.g., RELIANCE.NS, TCS.NS)"
                className="flex-1 px-4 py-3 rounded-full bg-[var(--surface-2)] border border-[var(--border)]
                           text-[var(--text)] font-mono text-xs placeholder:text-[var(--text-dim)]
                           focus:outline-none focus:border-[var(--green)]/50 focus:ring-1 focus:ring-[var(--green)]/30
                           transition-all"
              />
            </div>

            {/* Step 2: Index Documents */}
            {!indexed && !deepReport && (
              <button
                onClick={handleIndex}
                disabled={indexing || !symbol.trim()}
                className="w-full px-4 py-2.5 rounded-full border border-[var(--green)]/30 text-xs
                           font-bold text-[var(--green)] hover:bg-[rgba(16,185,129,0.06)]
                           transition-all cursor-pointer flex items-center justify-center gap-2
                           disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {indexing ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    Indexing documents...
                  </>
                ) : (
                  <>
                    <Database className="w-3.5 h-3.5" />
                    Index Documents for {symbol.trim().toUpperCase() || '...'}
                  </>
                )}
              </button>
            )}

            {/* Step 3: Indexed — Show Generate */}
            {indexed && !deepReport && (
              <div className="space-y-3">
                <div className="flex items-center gap-2 p-3 rounded-lg bg-[rgba(16,185,129,0.06)] border border-[rgba(16,185,129,0.2)]">
                  <CheckCircle className="w-4 h-4 text-[var(--green)]" />
                  <span className="text-xs font-mono text-[var(--green)]">
                    {indexedCount} documents indexed successfully
                  </span>
                </div>
                <button
                  onClick={handleDeepGenerate}
                  disabled={generating}
                  className="w-full px-4 py-2.5 rounded-full bg-[var(--green)] text-black text-xs
                             font-bold uppercase tracking-wider hover:bg-[var(--green-hover)] transition-all
                             cursor-pointer flex items-center justify-center gap-2
                             disabled:opacity-60 disabled:cursor-not-allowed shadow-sm"
                >
                  {generating ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      Generating deep research...
                    </>
                  ) : (
                    <>
                      <Sparkles className="w-3.5 h-3.5" />
                      Generate Deep Research
                    </>
                  )}
                </button>
              </div>
            )}

            {/* Error Display */}
            {error && (
              <div className="flex items-center gap-2 p-3 rounded-lg bg-[var(--red)]/10 border border-[var(--red)]/20 mt-3">
                <AlertCircle className="w-4 h-4 text-[var(--red)]" />
                <span className="text-xs font-mono text-[var(--red)]">{error}</span>
              </div>
            )}
          </motion.div>

          {/* Deep Research Features */}
          {!deepReport && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 max-w-3xl">
              {[
                { title: 'Multi-Source Synthesis', desc: 'Regulatory filings, earnings transcripts, analyst estimates indexed', icon: Database },
                { title: 'Inline Citations', desc: 'Every qualitative statement linked to [SOURCE N] references', icon: BookOpen },
                { title: 'Hallucination Resistant', desc: 'Strict RAG grounding ensures assertions are verified', icon: CheckCircle },
              ].map((item, i) => (
                <motion.div
                  key={item.title}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.2 + i * 0.1 }}
                  className="card p-5"
                >
                  <item.icon className="w-4 h-4 text-[var(--green)] mb-3" />
                  <h3 className="font-heading text-xs font-bold text-[var(--text)] mb-1">{item.title}</h3>
                  <p className="text-[11px] text-[var(--text-dim)] font-mono leading-relaxed">{item.desc}</p>
                </motion.div>
              ))}
            </div>
          )}

          {/* Deep Report Display */}
          {deepReport && (
            <>
              <CitedReport
                content={deepReport.report_content}
                sources={deepReport.sources}
                companyName={deepReport.company_name}
              />
              {/* Save Button — only when logged in */}
              {user && (
                <div className="flex justify-end mt-3">
                  <button
                    onClick={handleSaveReport}
                    disabled={saving || saved}
                    className={`flex items-center gap-2 px-4 py-2 rounded-full text-xs font-bold transition-all cursor-pointer ${
                      saved
                        ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                        : 'bg-[var(--green)] hover:bg-[var(--green-hover)] text-black'
                    } disabled:opacity-60`}
                  >
                    {saved ? (
                      <><CheckCircle className="w-3.5 h-3.5" /> Saved to Library</>
                    ) : saving ? (
                      <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Saving...</>
                    ) : (
                      <><Save className="w-3.5 h-3.5" /> Save Report</>
                    )}
                  </button>
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
