'use client';

import { motion } from 'framer-motion';
import { Bot, MessageSquare, Brain, Bell, LineChart, Lock } from 'lucide-react';

export default function AssistantPage() {
  const capabilities = [
    { icon: MessageSquare, title: 'Natural Language Analysis', desc: 'Ask questions about any stock in plain English and get data-driven answers' },
    { icon: LineChart, title: 'Portfolio Review', desc: 'Get AI-powered portfolio optimization suggestions and risk assessment' },
    { icon: Brain, title: 'Market Event Explanations', desc: 'Understand why markets moved with context-aware AI analysis' },
    { icon: Bell, title: 'Custom Watchlist Alerts', desc: 'Set intelligent alerts based on technical signals and news sentiment' },
  ];

  return (
    <div className="space-y-8 animate-fadeIn">
      <div>
        <h1 className="font-heading text-xl font-extrabold tracking-tight text-[var(--text)]">
          AI Assistant
        </h1>
        <p className="text-sm text-[var(--text-muted)] mt-1 font-mono">
          Conversational financial intelligence
        </p>
      </div>

      {/* Chat Mockup */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        className="card max-w-2xl overflow-hidden"
      >
        {/* Chat header */}
        <div className="px-5 py-3 border-b border-[var(--border)] flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Bot className="w-5 h-5 text-[var(--accent)]" />
            <span className="font-heading text-sm font-bold text-[var(--text)]">ARTH Assistant</span>
          </div>
          <span className="badge badge-yellow text-[10px] font-mono">Coming in Phase 2</span>
        </div>

        {/* Mock messages */}
        <div className="p-5 space-y-4 min-h-[260px]">
          <div className="flex gap-3">
            <div className="w-7 h-7 rounded-full bg-[var(--accent)]/20 flex items-center justify-center shrink-0">
              <Bot className="w-4 h-4 text-[var(--accent)]" />
            </div>
            <div className="card p-3 max-w-[80%]">
              <p className="text-sm text-[var(--text)]">
                Hello! I&apos;m your AI financial assistant. I can analyze stocks, explain market movements, and review your portfolio.
              </p>
              <p className="text-xs text-[var(--text-dim)] mt-2 font-mono">
                What would you like to explore today?
              </p>
            </div>
          </div>

          <div className="flex gap-3 justify-end">
            <div className="rounded-lg p-3 max-w-[80%] bg-[var(--accent)]/10 border border-[var(--accent)]/20">
              <p className="text-sm text-[var(--text)]">
                Why did RELIANCE drop today?
              </p>
            </div>
          </div>

          <div className="flex gap-3">
            <div className="w-7 h-7 rounded-full bg-[var(--accent)]/20 flex items-center justify-center shrink-0">
              <Bot className="w-4 h-4 text-[var(--accent)]" />
            </div>
            <div className="card p-3 max-w-[80%]">
              <div className="flex items-center gap-2 mb-2">
                <Lock className="w-3 h-3 text-[var(--gold)]" />
                <span className="text-[10px] font-mono text-[var(--gold)]">Feature locked — Phase 2</span>
              </div>
              <p className="text-xs text-[var(--text-dim)] italic">
                Conversational analysis will be available when the assistant module is deployed...
              </p>
            </div>
          </div>
        </div>

        {/* Disabled input */}
        <div className="px-5 py-3 border-t border-[var(--border)]">
          <div className="flex gap-2">
            <input
              disabled
              placeholder="Ask about any stock... (coming soon)"
              className="flex-1 px-4 py-2.5 rounded-lg bg-[var(--bg)] border border-[var(--border)]
                         text-[var(--text-dim)] font-mono text-sm cursor-not-allowed opacity-50"
            />
            <button
              disabled
              className="px-4 py-2.5 rounded-lg bg-[var(--surface-2)] text-[var(--text-dim)] text-sm
                         cursor-not-allowed opacity-50"
            >
              Send
            </button>
          </div>
        </div>
      </motion.div>

      {/* Planned Capabilities */}
      <div>
        <h2 className="font-heading text-sm font-bold uppercase tracking-wider text-[var(--text-muted)] mb-4">
          Planned Capabilities
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-w-2xl">
          {capabilities.map((cap, i) => (
            <motion.div
              key={cap.title}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3 + i * 0.1 }}
              className="card p-4 flex gap-3"
            >
              <cap.icon className="w-5 h-5 text-[var(--accent)] shrink-0 mt-0.5" />
              <div>
                <h3 className="text-sm font-bold text-[var(--text)]">{cap.title}</h3>
                <p className="text-xs text-[var(--text-dim)] mt-0.5 font-mono leading-relaxed">{cap.desc}</p>
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </div>
  );
}
