'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Bot, Send, User, Loader2, Sparkles, TrendingUp, BarChart3,
  ShieldAlert, MessageSquare, Trash2, ArrowDown,
} from 'lucide-react';
import Disclaimer from '@/components/shared/Disclaimer';
import { apiClient } from '@/lib/api';
import { STREAMING_API_URL } from '@/lib/constants';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
  toolsUsed?: string[];
  isStreaming?: boolean;
}

const SUGGESTED_QUERIES = [
  { icon: TrendingUp, text: 'How is RELIANCE.NS doing today?' },
  { icon: BarChart3, text: 'Analyze TCS.NS financials' },
  { icon: ShieldAlert, text: 'What are the risks for INFY.NS?' },
  { icon: Sparkles, text: 'Compare HDFCBANK.NS vs ICICIBANK.NS' },
];

function generateId(): string {
  return `msg-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

/* ── Markdown-lite renderer ── */
function renderContent(text: string) {
  const lines = text.split('\n');
  return lines.map((line, i) => {
    if (line.startsWith('## ')) {
      return <h3 key={i} className="font-heading text-sm font-bold text-[var(--text)] mt-3 mb-1">{renderInline(line.slice(3))}</h3>;
    }
    if (line.startsWith('### ')) {
      return <h4 key={i} className="font-heading text-xs font-bold text-[var(--text-muted)] mt-2 mb-1">{renderInline(line.slice(4))}</h4>;
    }
    if (line.startsWith('- ') || line.startsWith('* ')) {
      return <li key={i} className="text-sm text-[var(--text)] ml-4 mb-0.5 list-disc list-inside">{renderInline(line.slice(2))}</li>;
    }
    if (line.startsWith('⚠') || line.startsWith('---')) {
      return <p key={i} className="text-[11px] text-[var(--gold)] font-mono mt-3 py-1">{line}</p>;
    }
    if (line.trim() === '') return <div key={i} className="h-1.5" />;
    return <p key={i} className="text-sm text-[var(--text)] leading-relaxed mb-1">{renderInline(line)}</p>;
  });
}

function renderInline(text: string) {
  // Handle **bold**
  const parts = text.split(/(\*\*.*?\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i} className="font-semibold text-[var(--accent)]">{part.slice(2, -2)}</strong>;
    }
    return part;
  });
}

/* ── Chat bubble component ── */
function ChatBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === 'user';
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={`flex gap-3 ${isUser ? 'justify-end' : ''}`}
    >
      {!isUser && (
        <div className="w-7 h-7 rounded-full bg-[var(--accent)]/15 flex items-center justify-center shrink-0 mt-1">
          <Bot className="w-4 h-4 text-[var(--accent)]" />
        </div>
      )}

      <div className={`max-w-[85%] ${isUser
        ? 'rounded-2xl rounded-tr-sm px-4 py-3 bg-[var(--accent)]/10 border border-[var(--accent)]/20'
        : 'rounded-2xl rounded-tl-sm px-4 py-3 card'
      }`}>
        {/* Tool usage badges */}
        {!isUser && message.toolsUsed && message.toolsUsed.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-2">
            {message.toolsUsed.map((tool, i) => (
              <span key={i} className="badge badge-blue text-[9px] font-mono">
                📊 {tool}
              </span>
            ))}
          </div>
        )}

        <div className="prose-arth">
          {isUser ? (
            <p className="text-sm text-[var(--text)]">{message.content}</p>
          ) : (
            renderContent(message.content)
          )}
          {message.isStreaming && (
            <span className="inline-block w-2 h-4 bg-[var(--accent)] animate-pulse ml-0.5" />
          )}
        </div>

        <div className="text-[10px] font-mono text-[var(--text-dim)] mt-2">
          {message.timestamp.toLocaleTimeString()}
        </div>
      </div>

      {isUser && (
        <div className="w-7 h-7 rounded-full bg-[var(--surface-2)] flex items-center justify-center shrink-0 mt-1">
          <User className="w-4 h-4 text-[var(--text-muted)]" />
        </div>
      )}
    </motion.div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   AI Assistant Page
   ═══════════════════════════════════════════════════════════════ */
export default function AssistantPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [entities, setEntities] = useState<string[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  // Add welcome message on first mount
  useEffect(() => {
    setMessages([{
      id: generateId(),
      role: 'assistant',
      content: `Hello! I'm **ARTH**, your AI financial research assistant.\n\nI can analyze stocks, explain market movements, compare companies, and assess risks. Just mention a stock symbol (like **RELIANCE.NS** or **AAPL**) and I'll fetch live data.\n\nWhat would you like to explore?`,
      timestamp: new Date(),
    }]);
  }, []);

  const handleSubmit = async (text?: string) => {
    const msg = text || input.trim();
    if (!msg || isLoading) return;

    const userMessage: ChatMessage = {
      id: generateId(),
      role: 'user',
      content: msg,
      timestamp: new Date(),
    };

    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    // Create placeholder for streaming response
    const assistantId = generateId();
    const assistantMessage: ChatMessage = {
      id: assistantId,
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      toolsUsed: [],
      isStreaming: true,
    };
    setMessages(prev => [...prev, assistantMessage]);

    try {
      // SSE streaming
      // Use direct backend URL for SSE (Next.js rewrites may buffer streams)
      const url = `${STREAMING_API_URL}/api/v1/assistant/chat`;
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: msg,
          session_id: sessionId,
          stream: true,
        }),
      });

      if (!response.ok || !response.body) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let accumulatedContent = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const jsonStr = line.slice(6).trim();
          if (!jsonStr) continue;

          try {
            const event = JSON.parse(jsonStr);

            if (event.type === 'session' && event.session_id) {
              setSessionId(event.session_id);
            } else if (event.type === 'tools' && event.symbols) {
              setMessages(prev => prev.map(m =>
                m.id === assistantId
                  ? { ...m, toolsUsed: event.symbols.map((s: string) => `quote:${s}`) }
                  : m
              ));
            } else if (event.type === 'token') {
              accumulatedContent += event.content.replace(/\\n/g, '\n');
              setMessages(prev => prev.map(m =>
                m.id === assistantId
                  ? { ...m, content: accumulatedContent }
                  : m
              ));
            } else if (event.type === 'done') {
              if (event.entities) {
                setEntities(event.entities);
              }
              setMessages(prev => prev.map(m =>
                m.id === assistantId
                  ? { ...m, isStreaming: false }
                  : m
              ));
            }
          } catch {
            // Skip malformed events
          }
        }
      }
    } catch (error) {
      const errMsg = error instanceof Error && error.message.includes('fetch')
        ? 'Could not connect to the backend server. Make sure it is running.'
        : 'AI assistant encountered an error. The GROQ_API_KEY may not be configured, or the backend may be unavailable.';
      setMessages(prev => prev.map(m =>
        m.id === assistantId
          ? {
            ...m,
            content: errMsg,
            isStreaming: false,
          }
          : m
      ));
    } finally {
      setIsLoading(false);
      inputRef.current?.focus();
    }
  };

  const handleClear = () => {
    setMessages([{
      id: generateId(),
      role: 'assistant',
      content: 'Chat cleared. How can I help you?',
      timestamp: new Date(),
    }]);
    setSessionId(null);
    setEntities([]);
  };

  return (
    <div className="flex flex-col h-[calc(100vh-80px)] animate-fadeIn">
      <Disclaimer />

      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div>
          <h1 className="font-heading text-xl font-extrabold tracking-tight text-[var(--text)]">
            AI Assistant
          </h1>
          <p className="text-sm text-[var(--text-muted)] mt-0.5 font-mono">
            Conversational financial intelligence powered by Groq
          </p>
        </div>
        <div className="flex items-center gap-2">
          {entities.length > 0 && (
            <div className="flex gap-1">
              {entities.slice(-3).map(e => (
                <span key={e} className="badge badge-blue text-[10px] font-mono">{e}</span>
              ))}
            </div>
          )}
          <button
            onClick={handleClear}
            className="p-2 rounded-lg hover:bg-[var(--surface-2)] text-[var(--text-dim)]
                       hover:text-[var(--red)] transition-colors cursor-pointer"
            title="Clear chat"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Chat Messages */}
      <div
        ref={chatContainerRef}
        className="flex-1 overflow-y-auto space-y-4 px-1 py-4 scrollbar-thin"
      >
        <AnimatePresence>
          {messages.map(msg => (
            <ChatBubble key={msg.id} message={msg} />
          ))}
        </AnimatePresence>

        {/* Suggested queries (only when no user messages yet) */}
        {messages.length <= 1 && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3 }}
            className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-w-2xl mx-auto mt-4"
          >
            {SUGGESTED_QUERIES.map((q) => (
              <button
                key={q.text}
                onClick={() => handleSubmit(q.text)}
                className="card p-3 flex items-center gap-3 text-left hover:border-[var(--accent)]/30
                           transition-all cursor-pointer group"
              >
                <q.icon className="w-4 h-4 text-[var(--text-dim)] group-hover:text-[var(--accent)] transition-colors shrink-0" />
                <span className="text-xs text-[var(--text-muted)] group-hover:text-[var(--text)] transition-colors">
                  {q.text}
                </span>
              </button>
            ))}
          </motion.div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div className="border-t border-[var(--border)] pt-3 pb-1">
        <form
          onSubmit={(e) => { e.preventDefault(); handleSubmit(); }}
          className="flex gap-2 max-w-3xl mx-auto"
        >
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about any stock... (e.g., 'How is RELIANCE.NS doing?')"
            disabled={isLoading}
            className="flex-1 px-4 py-3 rounded-xl bg-[var(--bg)] border border-[var(--border)]
                       text-[var(--text)] font-mono text-sm placeholder:text-[var(--text-dim)]
                       focus:outline-none focus:border-[var(--accent)] focus:shadow-[0_0_0_3px_rgba(0,212,255,0.1)]
                       transition-all disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={isLoading || !input.trim()}
            className="px-4 py-3 rounded-xl bg-[var(--accent)] text-[var(--bg)] text-sm font-bold
                       hover:brightness-110 transition-all cursor-pointer
                       disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {isLoading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
          </button>
        </form>
        <p className="text-[10px] text-[var(--text-dim)] text-center mt-2 font-mono">
          ARTH uses Groq LLM · Data ~15s delayed · Not financial advice
        </p>
      </div>
    </div>
  );
}
