'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { BookOpen, ExternalLink } from 'lucide-react';
import { useRef, useCallback } from 'react';

interface Source {
  id: number;
  title: string;
  source: string;
  date: string;
  type: string;
  url?: string;
  relevance?: number;
}

interface CitedReportProps {
  content: string;
  sources: Source[];
  companyName?: string;
}

/**
 * Renders a research report with inline [SOURCE N] citations
 * that link to a references section at the bottom.
 */
export default function CitedReport({ content, sources, companyName }: CitedReportProps) {
  const refsRef = useRef<HTMLDivElement>(null);

  const scrollToRef = useCallback((id: number) => {
    const el = document.getElementById(`source-ref-${id}`);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el.classList.add('ring-2', 'ring-[var(--accent)]');
      setTimeout(() => el.classList.remove('ring-2', 'ring-[var(--accent)]'), 2000);
    }
  }, []);

  const renderLine = (line: string, idx: number) => {
    // Heading detection
    if (line.startsWith('## ')) {
      return (
        <h2 key={idx} className="font-heading text-base font-bold text-[var(--text)] mt-6 mb-2">
          {renderInlineContent(line.slice(3))}
        </h2>
      );
    }
    if (line.startsWith('### ')) {
      return (
        <h3 key={idx} className="font-heading text-sm font-bold text-[var(--text-muted)] mt-4 mb-1">
          {renderInlineContent(line.slice(4))}
        </h3>
      );
    }
    // Horizontal rule
    if (line.startsWith('---')) {
      return <hr key={idx} className="border-[var(--border)] my-4" />;
    }
    // List items
    if (line.startsWith('- ') || line.startsWith('* ')) {
      return (
        <li key={idx} className="text-sm text-[var(--text)] ml-4 mb-1 list-disc list-inside">
          {renderInlineContent(line.slice(2))}
        </li>
      );
    }
    // Numbered list
    const numMatch = line.match(/^(\d+)\.\s/);
    if (numMatch) {
      return (
        <li key={idx} className="text-sm text-[var(--text)] ml-4 mb-1 list-decimal list-inside">
          {renderInlineContent(line.slice(numMatch[0].length))}
        </li>
      );
    }
    // Empty line
    if (line.trim() === '') {
      return <div key={idx} className="h-2" />;
    }
    // Disclaimer line
    if (line.startsWith('⚠')) {
      return (
        <p key={idx} className="text-xs text-[var(--gold)] font-mono mt-4 p-3 rounded-lg bg-[var(--gold)]/5 border border-[var(--gold)]/20">
          {line}
        </p>
      );
    }
    // Regular paragraph
    return (
      <p key={idx} className="text-sm text-[var(--text)] leading-relaxed mb-2">
        {renderInlineContent(line)}
      </p>
    );
  };

  const renderInlineContent = (text: string) => {
    // Replace **bold**, [SOURCE N], and regular text
    const parts: React.ReactNode[] = [];
    // Match [SOURCE N] and **bold**
    const regex = /(\[SOURCE\s*(\d+)\]|\*\*(.+?)\*\*)/g;
    let lastIndex = 0;
    let match;

    while ((match = regex.exec(text)) !== null) {
      // Add text before match
      if (match.index > lastIndex) {
        parts.push(text.slice(lastIndex, match.index));
      }

      if (match[2]) {
        // [SOURCE N] — citation link
        const sourceId = parseInt(match[2], 10);
        const source = sources.find(s => s.id === sourceId);
        parts.push(
          <sup
            key={`cite-${match.index}`}
            className="inline-flex items-center cursor-pointer group relative"
            onClick={() => scrollToRef(sourceId)}
          >
            <span className="text-[10px] font-mono font-bold text-[var(--accent)] bg-[var(--accent)]/10 
                             px-1 py-0.5 rounded hover:bg-[var(--accent)]/20 transition-colors">
              {sourceId}
            </span>
            {source && (
              <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 w-48 p-2 rounded-lg
                               bg-[var(--surface-2)] border border-[var(--border)] text-[10px] text-[var(--text-muted)]
                               font-mono opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-50
                               shadow-lg">
                {source.title}
                <br />
                <span className="text-[var(--text-dim)]">{source.source} · {source.date}</span>
              </span>
            )}
          </sup>
        );
      } else if (match[3]) {
        // **bold**
        parts.push(
          <strong key={`bold-${match.index}`} className="font-semibold text-[var(--text)]">
            {match[3]}
          </strong>
        );
      }

      lastIndex = regex.lastIndex;
    }

    // Add remaining text
    if (lastIndex < text.length) {
      parts.push(text.slice(lastIndex));
    }

    return parts.length > 0 ? parts : text;
  };

  const lines = content.split('\n');

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="space-y-0"
    >
      {/* Report Content */}
      <div className="card p-6">
        {companyName && (
          <div className="flex items-center gap-2 mb-4 pb-3 border-b border-[var(--border)]">
            <BookOpen className="w-4 h-4 text-[var(--accent)]" />
            <span className="font-heading text-sm font-bold text-[var(--text)]">
              Deep Research Report — {companyName}
            </span>
            <span className="badge badge-green text-[10px] font-mono ml-auto">
              RAG · {sources.length} sources
            </span>
          </div>
        )}

        <div className="prose-arth">
          {lines.map((line, i) => renderLine(line, i))}
        </div>
      </div>

      {/* Sources Reference Section */}
      {sources.length > 0 && (
        <motion.div
          ref={refsRef}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.3 }}
          className="card p-5 mt-4"
        >
          <h3 className="font-heading text-xs font-bold uppercase tracking-wider text-[var(--text-muted)] mb-3">
            Sources Referenced ({sources.length})
          </h3>
          <div className="space-y-2">
            {sources.map((source) => (
              <div
                key={source.id}
                id={`source-ref-${source.id}`}
                className="flex items-start gap-3 p-2 rounded-lg hover:bg-[var(--surface-2)] transition-colors"
              >
                <span className="text-[10px] font-mono font-bold text-[var(--accent)] bg-[var(--accent)]/10
                                 px-1.5 py-0.5 rounded mt-0.5 shrink-0">
                  {source.id}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium text-[var(--text)] truncate">
                    {source.title}
                  </p>
                  <p className="text-[10px] font-mono text-[var(--text-dim)]">
                    {source.source} · {source.type} · {source.date}
                    {source.relevance !== undefined && (
                      <span className="ml-2 text-[var(--accent)]">
                        {(source.relevance * 100).toFixed(0)}% relevant
                      </span>
                    )}
                  </p>
                </div>
                {source.url && (
                  <a
                    href={source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[var(--text-dim)] hover:text-[var(--accent)] transition-colors shrink-0"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <ExternalLink className="w-3 h-3" />
                  </a>
                )}
              </div>
            ))}
          </div>
        </motion.div>
      )}
    </motion.div>
  );
}
