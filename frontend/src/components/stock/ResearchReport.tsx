'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { motion } from 'framer-motion';
import { FileText, Loader2, AlertTriangle } from 'lucide-react';
import { STREAMING_API_URL } from '@/lib/constants';

interface ResearchReportProps {
  symbol: string;
}

export default function ResearchReport({ symbol }: ResearchReportProps) {
  const [content, setContent] = useState('');
  const [status, setStatus] = useState<'idle' | 'loading' | 'streaming' | 'done' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  const generateReport = useCallback(async () => {
    setContent('');
    setStatus('loading');
    setError(null);

    try {
      const response = await fetch(
        `${STREAMING_API_URL}/api/v1/research/generate/${encodeURIComponent(symbol)}?stream=true&depth=standard`,
        {
          method: 'POST',
          headers: { 'Accept': 'text/event-stream' },
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
  }, [symbol]);

  // Auto-scroll during streaming
  useEffect(() => {
    if (status === 'streaming' && contentRef.current) {
      contentRef.current.scrollTop = contentRef.current.scrollHeight;
    }
  }, [content, status]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.4 }}
      className="card overflow-hidden"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-[var(--border)]">
        <div className="flex items-center gap-2">
          <FileText className="w-4 h-4 text-[var(--accent-purple)]" />
          <h3 className="font-heading text-sm font-bold uppercase tracking-wider text-[var(--text-muted)]">
            AI Research Report
          </h3>
        </div>
        <button
          onClick={generateReport}
          disabled={status === 'loading' || status === 'streaming'}
          className={`
            px-3 py-1.5 text-xs font-mono rounded cursor-pointer transition-all
            ${status === 'loading' || status === 'streaming'
              ? 'bg-[var(--surface-2)] text-[var(--text-dim)] cursor-not-allowed'
              : 'bg-[var(--accent)]/15 text-[var(--accent)] border border-[var(--accent)]/30 hover:bg-[var(--accent)]/25'
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
        className="p-5 max-h-[500px] overflow-y-auto"
      >
        {status === 'idle' && (
          <div className="text-center py-12 text-[var(--text-dim)]">
            <FileText className="w-8 h-8 mx-auto mb-3 opacity-30" />
            <p className="text-sm font-mono">Click &quot;Generate Report&quot; to create an AI analysis</p>
            <p className="text-[10px] mt-1 text-[var(--text-dim)]">
              Uses real-time Yahoo Finance data + Groq LLaMA 3.3 70B
            </p>
          </div>
        )}

        {status === 'error' && (
          <div className="text-center py-8">
            <AlertTriangle className="w-6 h-6 mx-auto mb-2 text-[var(--accent-orange)]" />
            <p className="text-sm text-[var(--accent-orange)]">{error}</p>
            <p className="text-[10px] mt-1 text-[var(--text-dim)]">
              Ensure the backend is running and GROQ_API_KEY is set
            </p>
          </div>
        )}

        {(status === 'streaming' || status === 'done') && (
          <div className="prose prose-invert prose-sm max-w-none">
            <pre className="whitespace-pre-wrap font-sans text-sm text-[var(--text)] leading-relaxed">
              {content}
              {status === 'streaming' && (
                <span className="inline-block w-2 h-4 bg-[var(--accent)] animate-pulse-dot ml-0.5" />
              )}
            </pre>
          </div>
        )}
      </div>

      {/* Footer disclaimer */}
      {(status === 'streaming' || status === 'done') && (
        <div className="px-5 py-2 border-t border-[var(--border)] bg-[var(--bg)]">
          <p className="text-[10px] font-mono text-[var(--text-dim)]">
            ⚠ AI-generated · Not financial advice · Data delayed ~15s · Groq LLaMA 3.3 70B
          </p>
        </div>
      )}
    </motion.div>
  );
}
