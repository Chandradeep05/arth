'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { motion } from 'framer-motion';
import { FileText, Loader2, AlertTriangle } from 'lucide-react';
import { STREAMING_API_URL } from '@/lib/constants';
import { useAuth } from '@/lib/auth/AuthProvider';

interface ResearchReportProps {
  symbol: string;
}

export default function ResearchReport({ symbol }: ResearchReportProps) {
  const [content, setContent] = useState('');
  const [status, setStatus] = useState<'idle' | 'loading' | 'streaming' | 'done' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const { session } = useAuth();

  const generateReport = useCallback(async () => {
    setContent('');
    setStatus('loading');
    setError(null);

    try {
      const response = await fetch(
        `${STREAMING_API_URL}/api/v1/research/generate/${encodeURIComponent(symbol)}?stream=true&depth=standard`,
        {
          method: 'POST',
          headers: { 
            'Accept': 'text/event-stream',
            'Authorization': `Bearer ${session?.access_token || ''}`
          },
        }
      );

      if (!response.ok || !response.body) {
        throw new Error(`API error: ${response.status}`);
      }

      setStatus('streaming');

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const raw = line.slice(6).trim();
            if (!raw || raw === '[DONE]') continue;
            try {
              const parsed = JSON.parse(raw);
              if (parsed.type === 'token' && parsed.content) {
                const text = parsed.content.replace(/\\n/g, '\n');
                setContent((prev) => prev + text);
              }
            } catch {
              // Non-JSON SSE data, skip
            }
          }
        }
      }

      setStatus('done');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to generate report');
      setStatus('error');
    }
  }, [symbol, session?.access_token]);

  // Auto-scroll during streaming
  useEffect(() => {
    if (status === 'streaming' && contentRef.current) {
      contentRef.current.scrollTop = contentRef.current.scrollHeight;
    }
  }, [content, status]);

  const renderInline = (text: string): React.ReactNode => {
    const parts: React.ReactNode[] = [];
    let remaining = text;
    let key = 0;
    while (remaining) {
      const boldMatch = remaining.match(/\*\*(.+?)\*\*/);
      const codeMatch = remaining.match(/`([^`]+)`/);
      const italicMatch = remaining.match(/(?<!\*)\*([^*]+)\*(?!\*)/);

      const boldIdx = boldMatch?.index ?? Infinity;
      const codeIdx = codeMatch?.index ?? Infinity;
      const italicIdx = italicMatch?.index ?? Infinity;

      const minIdx = Math.min(boldIdx, codeIdx, italicIdx);
      if (minIdx === Infinity) {
        parts.push(remaining);
        break;
      }

      if (minIdx === boldIdx && boldMatch) {
        if (boldMatch.index! > 0) parts.push(remaining.slice(0, boldMatch.index!));
        parts.push(<strong key={key++} className="font-semibold text-white">{renderInline(boldMatch[1])}</strong>);
        remaining = remaining.slice(boldMatch.index! + boldMatch[0].length);
      } else if (minIdx === codeIdx && codeMatch) {
        if (codeMatch.index! > 0) parts.push(remaining.slice(0, codeMatch.index!));
        parts.push(<code key={key++} className="px-1.5 py-0.5 rounded bg-white/[0.06] text-emerald-400 font-mono text-[11px]">{codeMatch[1]}</code>);
        remaining = remaining.slice(codeMatch.index! + codeMatch[0].length);
      } else if (minIdx === italicIdx && italicMatch) {
        if (italicMatch.index! > 0) parts.push(remaining.slice(0, italicMatch.index!));
        parts.push(<em key={key++} className="italic text-[var(--text-muted)]">{italicMatch[1]}</em>);
        remaining = remaining.slice(italicMatch.index! + italicMatch[0].length);
      }
    }
    return parts.length === 1 ? parts[0] : <>{parts}</>;
  };

  const renderReportContent = (text: string) => {
    const sections = text.split('```');
    return sections.map((sec, secIdx) => {
      if (secIdx % 2 === 1) {
        const newlineIdx = sec.indexOf('\n');
        const lang = newlineIdx > -1 ? sec.slice(0, newlineIdx).trim() : '';
        const code = newlineIdx > -1 ? sec.slice(newlineIdx + 1) : sec;
        return (
          <div key={`code-${secIdx}`} className="my-3 rounded-lg bg-black/40 border border-white/[0.08] overflow-hidden">
            {lang && <div className="px-3 py-1 bg-white/[0.04] text-[10px] font-mono text-[var(--text-dim)] border-b border-white/[0.06]">{lang}</div>}
            <pre className="p-3 text-xs font-mono text-emerald-400 overflow-x-auto leading-relaxed">{code}</pre>
          </div>
        );
      }

      const rawLines = sec.split('\n');
      const renderedElements: React.ReactNode[] = [];
      let i = 0;

      while (i < rawLines.length) {
        const line = rawLines[i];
        const trimmed = line.trim();

        if (trimmed.startsWith('|') && trimmed.endsWith('|') && i + 1 < rawLines.length && rawLines[i + 1].includes('---')) {
          const tableHeaders = trimmed.split('|').slice(1, -1).map(c => c.trim());
          i += 2;
          const tableRows: string[][] = [];
          while (i < rawLines.length && rawLines[i].trim().startsWith('|') && rawLines[i].trim().endsWith('|')) {
            tableRows.push(rawLines[i].trim().split('|').slice(1, -1).map(c => c.trim()));
            i++;
          }
          renderedElements.push(
            <div key={`tbl-${i}`} className="my-4 overflow-x-auto rounded-lg border border-white/[0.08] bg-white/[0.01]">
              <table className="w-full text-xs text-left">
                <thead className="bg-white/[0.04] text-[var(--text-muted)] font-mono border-b border-white/[0.08]">
                  <tr>
                    {tableHeaders.map((h, hi) => (
                      <th key={hi} className="px-3 py-2 font-semibold">{renderInline(h)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.04]">
                  {tableRows.map((r, ri) => (
                    <tr key={ri} className="hover:bg-white/[0.02]">
                      {r.map((cell, ci) => (
                        <td key={ci} className="px-3 py-2 font-mono text-[var(--text)]">{renderInline(cell)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
          continue;
        }

        if (line.startsWith('# ')) {
          renderedElements.push(<h2 key={i} className="text-base font-bold text-white mt-5 mb-2 font-heading tracking-wide flex items-center gap-2">{renderInline(line.slice(2))}</h2>);
        } else if (line.startsWith('## ')) {
          renderedElements.push(<h3 key={i} className="text-sm font-bold text-white mt-4 mb-2 font-heading tracking-wide">{renderInline(line.slice(3))}</h3>);
        } else if (line.startsWith('### ')) {
          renderedElements.push(<h4 key={i} className="text-xs font-semibold text-emerald-400 uppercase tracking-wider mt-3 mb-1 font-mono">{renderInline(line.slice(4))}</h4>);
        } else if (line.startsWith('#### ')) {
          renderedElements.push(<h5 key={i} className="text-xs font-semibold text-[var(--text-muted)] mt-2 mb-1">{renderInline(line.slice(5))}</h5>);
        } else if (trimmed === '---' || trimmed === '***') {
          renderedElements.push(<hr key={i} className="my-4 border-white/[0.08]" />);
        } else if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
          renderedElements.push(
            <div key={i} className="flex gap-2 ml-2 my-1 text-xs text-[var(--text)] leading-relaxed">
              <span className="text-emerald-400 shrink-0 select-none">•</span>
              <div>{renderInline(trimmed.slice(2))}</div>
            </div>
          );
        } else if (/^\d+\.\s/.test(trimmed)) {
          const numMatch = trimmed.match(/^(\d+)\.\s+(.*)/);
          if (numMatch) {
            renderedElements.push(
              <div key={i} className="flex gap-2 ml-2 my-1 text-xs text-[var(--text)] leading-relaxed">
                <span className="text-emerald-400 font-mono text-[11px] shrink-0 select-none">{numMatch[1]}.</span>
                <div>{renderInline(numMatch[2])}</div>
              </div>
            );
          }
        } else if (trimmed.startsWith('>')) {
          renderedElements.push(
            <blockquote key={i} className="my-2 pl-3 border-l-2 border-emerald-500/40 text-xs italic text-[var(--text-muted)]">
              {renderInline(trimmed.slice(1).trim())}
            </blockquote>
          );
        } else if (!trimmed) {
          renderedElements.push(<div key={i} className="h-2" />);
        } else {
          renderedElements.push(
            <p key={i} className="text-xs text-[var(--text)] leading-relaxed mb-2 font-sans">
              {renderInline(line)}
            </p>
          );
        }
        i++;
      }

      return <div key={`sec-${secIdx}`}>{renderedElements}</div>;
    });
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.4 }}
      className="card overflow-hidden"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3.5 border-b border-white/[0.06]">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-white/[0.04] border border-white/[0.08] flex items-center justify-center">
            <FileText className="w-3.5 h-3.5 text-emerald-400" />
          </div>
          <h3 className="font-heading text-xs font-bold uppercase tracking-wider text-white">
            AI Research Report
          </h3>
        </div>
        <button
          onClick={generateReport}
          disabled={status === 'loading' || status === 'streaming'}
          className={`
            px-3 py-1.5 text-xs font-mono rounded-lg cursor-pointer transition-all
            ${status === 'loading' || status === 'streaming'
              ? 'bg-white/[0.03] text-[var(--text-dim)] cursor-not-allowed border border-white/[0.05]'
              : 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/25'
            }
          `}
        >
          {status === 'loading' && (
            <span className="flex items-center gap-1.5">
              <Loader2 className="w-3 h-3 animate-spin" /> Fetching data...
            </span>
          )}
          {status === 'streaming' && (
            <span className="flex items-center gap-1.5">
              <Loader2 className="w-3 h-3 animate-spin" /> Generating...
            </span>
          )}
          {(status === 'idle' || status === 'done' || status === 'error') && 'Generate Report'}
        </button>
      </div>

      {/* Content */}
      <div
        ref={contentRef}
        className="p-6 max-h-[500px] overflow-y-auto"
      >
        {status === 'idle' && (
          <div className="text-center py-12 text-[var(--text-dim)]">
            <FileText className="w-8 h-8 mx-auto mb-3 opacity-30" />
            <p className="text-xs font-mono text-[var(--text-muted)]">Click &quot;Generate Report&quot; to create an institutional AI analysis</p>
            <p className="text-[10px] mt-1 text-[var(--text-dim)] font-mono">
              Synthesized from market fundamentals, SEC filings, and technical indicators
            </p>
          </div>
        )}

        {status === 'error' && (
          <div className="text-center py-8">
            <AlertTriangle className="w-5 h-5 mx-auto mb-2 text-amber-400" />
            <p className="text-xs text-amber-400 font-mono">{error}</p>
            <p className="text-[10px] mt-1 text-[var(--text-dim)] font-mono">
              Ensure the backend is running with appropriate model keys configured
            </p>
          </div>
        )}

        {(status === 'streaming' || status === 'done') && (
          <div className="prose prose-invert prose-sm max-w-none">
            <div className="text-xs text-[var(--text)] leading-relaxed space-y-1">
              {renderReportContent(content)}
              {status === 'streaming' && (
                <span className="inline-block w-1.5 h-3.5 bg-emerald-400 animate-pulse-dot ml-0.5" />
              )}
            </div>
          </div>
        )}
      </div>

      {/* Footer disclaimer */}
      {(status === 'streaming' || status === 'done') && (
        <div className="px-5 py-2.5 border-t border-white/[0.06] bg-transparent">
          <p className="text-[10px] font-mono text-[var(--text-dim)]">
            ⚠ AI-generated · For informational purposes only · Powered by ARTH AI
          </p>
        </div>
      )}
    </motion.div>
  );
}
