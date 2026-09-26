'use client';

import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { MessageSquare, Plus, Trash2, Edit3, Send, Bot, User, Menu, X, Loader2 } from 'lucide-react';
import { useAuth } from '@/lib/auth/AuthProvider';
import { useAuthenticatedApi } from '@/lib/auth/useAuthenticatedApi';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'https://arth-rdd5.onrender.com';

interface Conversation {
  id: string;
  title: string;
  last_message_at: string;
  message_count: number;
}

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

export default function AssistantPage() {
  const { session, user, loading: authLoading } = useAuth();
  const api = useAuthenticatedApi();
  
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  
  const messagesEndRef = useRef<HTMLDivElement>(null);
  
  useEffect(() => {
    if (!authLoading && session) {
      fetchConversations();
    }
  }, [authLoading, session]);
  
  useEffect(() => {
    if (activeConversationId) {
      const loadHistory = async () => {
        try {
          const data = await api.get<any>(`/api/v1/user/conversations/${activeConversationId}?limit=50`);
          if (data?.messages) {
            setMessages(data.messages.map((m: any) => ({
              id: m.id || crypto.randomUUID(),
              role: m.role as 'user' | 'assistant',
              content: m.content,
            })));
          } else {
            setMessages([]);
          }
        } catch (err) {
          console.error('Failed to load conversation history:', err);
          setMessages([]);
        }
      };
      loadHistory();
    } else {
      setMessages([]);
    }
  }, [activeConversationId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const fetchConversations = async () => {
    try {
      const data = await api.get<Conversation[]>('/api/v1/user/conversations');
      setConversations(data || []);
      if (data && data.length > 0 && !activeConversationId) {
        setActiveConversationId(data[0].id);
      }
    } catch (error) {
      console.error('Failed to fetch conversations:', error);
    }
  };

  const createConversation = async () => {
    try {
      const data = await api.post<Conversation>('/api/v1/user/conversations', { title: 'New Conversation' });
      if (data) {
        setConversations([data, ...conversations]);
        setActiveConversationId(data.id);
        setMessages([]);
      }
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };

  const deleteConversation = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await api.delete(`/api/v1/user/conversations/${id}`);
      setConversations(conversations.filter(c => c.id !== id));
      if (activeConversationId === id) {
        setActiveConversationId(null);
        setMessages([]);
      }
    } catch (error) {
      console.error('Failed to delete conversation:', error);
    }
  };

  const sendMessage = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!input.trim() || isLoading) return;

    let convId = activeConversationId;
    if (!convId) {
      try {
        const newConv = await api.post<Conversation>('/api/v1/user/conversations', { title: input.substring(0, 30) });
        if (newConv) {
          setConversations([newConv, ...conversations]);
          convId = newConv.id;
          setActiveConversationId(convId);
        }
      } catch (err) {
        console.error(err);
        return;
      }
    }

    const userMsg: Message = { id: Date.now().toString(), role: 'user', content: input };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setIsLoading(true);

    const assistantMsgId = (Date.now() + 1).toString();
    setMessages(prev => [...prev, { id: assistantMsgId, role: 'assistant', content: '' }]);

    try {
      // Stream via /assistant/chat — backend owns persistence (no separate POST needed)
      const response = await fetch(`${API_URL}/api/v1/assistant/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${session?.access_token}`
        },
        body: JSON.stringify({
          message: userMsg.content,
          session_id: convId,
          conversation_id: convId,
          idempotency_key: crypto.randomUUID(),  // Prevent double-burn on retries
          stream: true,
        })
      });

      if (response.status === 401) {
        setMessages(prev => prev.map(m => m.id === assistantMsgId ? { ...m, content: 'Sign in to use the AI assistant.' } : m));
        setIsLoading(false);
        return;
      }
      if (!response.ok) throw new Error('Stream failed');
      
      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      
      if (reader) {
        let aiContent = '';
        let sseBuffer = '';  // Accumulate across TCP chunks
        
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          
          sseBuffer += decoder.decode(value, { stream: true });
          
          // Process only complete SSE events (terminated by double newline)
          let eventEnd: number;
          while ((eventEnd = sseBuffer.indexOf('\n\n')) !== -1) {
            const event = sseBuffer.slice(0, eventEnd);
            sseBuffer = sseBuffer.slice(eventEnd + 2);
            
            for (const line of event.split('\n')) {
              if (line.startsWith('data: ') && line !== 'data: [DONE]') {
                try {
                  const data = JSON.parse(line.slice(6));
                  if (data.type === 'token' && data.content) {
                    aiContent += data.content;
                    setMessages(prev => prev.map(m => m.id === assistantMsgId ? { ...m, content: aiContent } : m));
                  } else if (data.type === 'done') {
                    // Stream complete — entities available if needed
                  } else if (data.type === 'error') {
                    console.error(data.message || 'Stream error'); // Changed setError to console.error to avoid ReferenceError
                  }
                } catch (e) {
                  // Incomplete JSON — should not happen with proper buffering
                  console.error('SSE parse error:', e);
                }
              }
            }
          }
        }
        
        // Flush any remaining buffer content
        if (sseBuffer.trim()) {
          for (const line of sseBuffer.split('\n')) {
            if (line.startsWith('data: ') && line !== 'data: [DONE]') {
              try {
                const data = JSON.parse(line.slice(6));
                if (data.type === 'token' && data.content) {
                  aiContent += data.content;
                  setMessages(prev => prev.map(m => m.id === assistantMsgId ? { ...m, content: aiContent } : m));
                }
              } catch (e) {
                // Partial final event — acceptable to lose
              }
            }
          }
        }
      }
    } catch (error) {
      console.error('Chat error:', error);
      setMessages(prev => prev.map(m => m.id === assistantMsgId ? { ...m, content: 'Error: Could not get response.' } : m));
    } finally {
      setIsLoading(false);
    }
  };

  const renderMarkdown = (content: string) => {
    const parts = content.split('```');
    return parts.map((part, index) => {
      if (index % 2 === 1) {
        // Code block
        const newlineIdx = part.indexOf('\n');
        const lang = newlineIdx > -1 ? part.slice(0, newlineIdx) : '';
        const code = newlineIdx > -1 ? part.slice(newlineIdx + 1) : part;
        return (
          <div key={index} className="my-2 rounded bg-zinc-950 border border-zinc-800 overflow-hidden">
            {lang && <div className="px-3 py-1 bg-zinc-900 text-xs text-zinc-400 border-b border-zinc-800">{lang}</div>}
            <pre className="p-3 overflow-x-auto text-sm text-zinc-300">
              <code>{code}</code>
            </pre>
          </div>
        );
      }
      // Process text with inline markdown
      const lines = part.split('\n');
      return (
        <div key={index}>
          {lines.map((line, li) => {
            // Bullet points
            const bulletMatch = line.match(/^\s*[-*]\s+(.+)/);
            if (bulletMatch) {
              return (
                <div key={li} className="flex gap-2 ml-2 my-0.5">
                  <span className="text-[var(--text-dim)] shrink-0">•</span>
                  <span>{renderInline(bulletMatch[1])}</span>
                </div>
              );
            }
            // Numbered lists
            const numMatch = line.match(/^\s*(\d+)\.\s+(.+)/);
            if (numMatch) {
              return (
                <div key={li} className="flex gap-2 ml-2 my-0.5">
                  <span className="text-[var(--text-dim)] shrink-0 font-mono text-xs">{numMatch[1]}.</span>
                  <span>{renderInline(numMatch[2])}</span>
                </div>
              );
            }
            // Empty lines = paragraph break
            if (!line.trim()) return <div key={li} className="h-2" />
            // Regular text
            return <div key={li} className="whitespace-pre-wrap">{renderInline(line)}</div>;
          })}
        </div>
      );
    });
  };

  // Inline formatting: **bold** and `code`
  const renderInline = (text: string): React.ReactNode => {
    const parts: React.ReactNode[] = [];
    let remaining = text;
    let key = 0;
    while (remaining) {
      // Bold
      const boldMatch = remaining.match(/\*\*(.+?)\*\*/);
      // Inline code
      const codeMatch = remaining.match(/`([^`]+)`/);
      
      const boldIdx = boldMatch?.index ?? Infinity;
      const codeIdx = codeMatch?.index ?? Infinity;
      
      if (boldIdx === Infinity && codeIdx === Infinity) {
        parts.push(remaining);
        break;
      }
      
      if (boldIdx <= codeIdx && boldMatch) {
        if (boldMatch.index! > 0) parts.push(remaining.slice(0, boldMatch.index!));
        parts.push(<strong key={key++} className="font-semibold text-white">{boldMatch[1]}</strong>);
        remaining = remaining.slice(boldMatch.index! + boldMatch[0].length);
      } else if (codeMatch) {
        if (codeMatch.index! > 0) parts.push(remaining.slice(0, codeMatch.index!));
        parts.push(<code key={key++} className="px-1 py-0.5 rounded bg-zinc-800 text-emerald-400 text-xs font-mono">{codeMatch[1]}</code>);
        remaining = remaining.slice(codeMatch.index! + codeMatch[0].length);
      }
    }
    return parts.length === 1 ? parts[0] : <>{parts}</>;
  };

  return (
    <div className="flex h-screen bg-[var(--bg)] text-[var(--text)] font-sans">
      {/* Mobile Sidebar Overlay */}
      <AnimatePresence>
        {isSidebarOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40 md:hidden"
            onClick={() => setIsSidebarOpen(false)}
          />
        )}
      </AnimatePresence>

      {/* Sidebar */}
      <div className={`fixed inset-y-0 left-0 z-50 w-72 bg-[var(--surface)] backdrop-blur-xl border-r border-[var(--border)] transform transition-transform duration-300 ease-in-out md:relative md:translate-x-0 flex flex-col ${isSidebarOpen ? 'translate-x-0' : '-translate-x-full'}`}>
        <div className="p-4 flex items-center justify-between border-b border-[var(--border)]">
          <h2 className="text-sm font-semibold flex items-center gap-2 text-[var(--text)]">
            <Bot className="w-4 h-4 text-[var(--green)]" /> ARTH Intelligence
          </h2>
          <button onClick={() => setIsSidebarOpen(false)} className="md:hidden p-1 text-[var(--text-dim)] hover:text-white cursor-pointer">
            <X className="w-4 h-4" />
          </button>
        </div>
        
        <div className="p-3">
          <button
            onClick={createConversation}
            className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-[rgba(255,255,255,0.04)] hover:bg-[rgba(255,255,255,0.08)] rounded-full text-xs font-semibold text-[var(--text)] transition-colors border border-[var(--border)] cursor-pointer"
          >
            <Plus className="w-3.5 h-3.5 text-[var(--green)]" /> New Chat
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-3 pb-3 space-y-1">
          {conversations.length === 0 ? (
            <div className="text-center py-6 text-[var(--text-dim)] text-xs font-mono">No previous sessions</div>
          ) : (
            conversations.map(conv => (
              <div
                key={conv.id}
                onClick={() => { setActiveConversationId(conv.id); setIsSidebarOpen(false); }}
                className={`group flex items-center justify-between px-3 py-2 rounded-lg cursor-pointer transition-colors text-xs ${
                  activeConversationId === conv.id 
                    ? 'bg-[rgba(16,185,129,0.12)] text-[var(--green)] border border-[rgba(16,185,129,0.25)]' 
                    : 'text-[var(--text-muted)] hover:bg-[rgba(255,255,255,0.04)] hover:text-white'
                }`}
              >
                <div className="flex items-center gap-2.5 truncate">
                  <MessageSquare className="w-3.5 h-3.5 shrink-0 opacity-70" />
                  <span className="truncate">{conv.title}</span>
                </div>
                <button
                  onClick={(e) => deleteConversation(conv.id, e)}
                  className="opacity-0 group-hover:opacity-100 p-1 text-[var(--text-dim)] hover:text-[var(--red)] transition-opacity cursor-pointer"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <header className="h-14 border-b border-[var(--border)] flex items-center px-4 bg-[var(--surface)]/80 backdrop-blur sticky top-0 z-10 shrink-0">
          <button
            onClick={() => setIsSidebarOpen(true)}
            className="md:hidden p-2 -ml-2 mr-2 text-[var(--text-dim)] hover:text-white rounded-lg hover:bg-[var(--surface-2)] cursor-pointer"
          >
            <Menu className="w-4 h-4" />
          </button>
          <h1 className="text-xs font-mono font-medium text-[var(--text)]">
            {conversations.find(c => c.id === activeConversationId)?.title || 'Market Research Session'}
          </h1>
        </header>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-5">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-[var(--text-dim)] space-y-3">
              <div className="w-12 h-12 rounded-full bg-[rgba(16,185,129,0.1)] border border-[var(--green)]/20 flex items-center justify-center">
                <Bot className="w-6 h-6 text-[var(--green)]" />
              </div>
              <p className="text-xs font-mono text-[var(--text-muted)]">Ask ARTH about technical signals, risk dimensions, or corporate filings</p>
            </div>
          ) : (
            messages.map((msg, idx) => (
              <motion.div
                key={msg.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className={`flex gap-3 max-w-4xl mx-auto ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}
              >
                <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${
                  msg.role === 'user' 
                    ? 'bg-[var(--surface-2)] border border-[var(--border)] text-white' 
                    : 'bg-[rgba(16,185,129,0.12)] border border-[rgba(16,185,129,0.3)] text-[var(--green)]'
                }`}>
                  {msg.role === 'user' ? <User className="w-3.5 h-3.5" /> : <Bot className="w-3.5 h-3.5" />}
                </div>
                <div className={`flex-1 rounded-2xl px-4 py-3 text-xs leading-relaxed ${
                  msg.role === 'user' 
                    ? 'bg-[rgba(16,185,129,0.1)] text-emerald-100 border border-[rgba(16,185,129,0.22)] ml-12' 
                    : 'bg-[var(--surface)] text-[var(--text)] border border-[var(--border)] mr-12 shadow-sm'
                }`}>
                  {renderMarkdown(msg.content)}
                  {msg.role === 'assistant' && msg.content === '' && isLoading && idx === messages.length - 1 && (
                    <div className="flex gap-1 items-center h-5">
                      <span className="w-1.5 h-1.5 bg-[var(--green)] rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                      <span className="w-1.5 h-1.5 bg-[var(--green)] rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                      <span className="w-1.5 h-1.5 bg-[var(--green)] rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                    </div>
                  )}
                </div>
              </motion.div>
            ))
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="p-4 md:p-6 bg-[var(--bg)] border-t border-[var(--border)] shrink-0">
          <form onSubmit={sendMessage} className="max-w-4xl mx-auto relative flex items-end gap-2 bg-[var(--surface)] border border-[var(--border)] rounded-xl focus-within:border-[var(--green)]/40 transition-all shadow-inner">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  sendMessage();
                }
              }}
              placeholder="Query ARTH Assistant (e.g., 'Compare RELIANCE and TCS risk metrics')..."
              className="w-full max-h-48 min-h-[50px] py-3.5 pl-4 pr-12 bg-transparent text-[var(--text)] placeholder:text-[var(--text-dim)] text-xs resize-none outline-none overflow-y-auto"
              rows={1}
            />
            <button
              type="submit"
              disabled={!input.trim() || isLoading}
              className="absolute right-2.5 bottom-2.5 p-2 bg-[var(--green)] text-black rounded-lg hover:bg-[var(--green-hover)] disabled:opacity-40 disabled:hover:bg-[var(--green)] transition-colors cursor-pointer"
            >
              {isLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
            </button>
          </form>
          <div className="text-center mt-2 text-[10px] font-mono text-[var(--text-dim)]">
            Institutional algorithmic intelligence · Always verify before making investment decisions
          </div>
        </div>
      </div>
    </div>
  );
}
