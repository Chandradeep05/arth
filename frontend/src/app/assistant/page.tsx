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
  const { session } = useAuth();
  const api = useAuthenticatedApi();
  
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  
  const messagesEndRef = useRef<HTMLDivElement>(null);
  
  useEffect(() => {
    fetchConversations();
  }, []);
  
  useEffect(() => {
    if (activeConversationId) {
      // In a real app we'd fetch messages for this conversation here.
      // Assuming a GET /user/conversations/{id}/messages endpoint or similar.
      // For now, we'll just clear messages on switch if we can't fetch them.
      setMessages([]);
    }
  }, [activeConversationId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const fetchConversations = async () => {
    try {
      const data = await api.get('/user/conversations');
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
      const data = await api.post('/user/conversations', { title: 'New Conversation' });
      setConversations([data, ...conversations]);
      setActiveConversationId(data.id);
      setMessages([]);
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };

  const deleteConversation = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await api.delete(`/user/conversations/${id}`);
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
        const newConv = await api.post('/user/conversations', { title: input.substring(0, 30) });
        setConversations([newConv, ...conversations]);
        convId = newConv.id;
        setActiveConversationId(convId);
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
      // First save the message to DB
      await api.post(`/user/conversations/${convId}/messages`, { content: userMsg.content });
      
      // Then start SSE stream
      const response = await fetch(`${API_URL}/api/v1/assistant/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${session?.access_token}`
        },
        body: JSON.stringify({ message: userMsg.content, session_id: convId, stream: true })
      });

      if (!response.ok) throw new Error('Stream failed');
      
      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      
      if (reader) {
        let aiContent = '';
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          
          const chunk = decoder.decode(value, { stream: true });
          const lines = chunk.split('\n');
          
          for (const line of lines) {
            if (line.startsWith('data: ') && line !== 'data: [DONE]') {
              try {
                const data = JSON.parse(line.slice(6));
                if (data.delta) {
                  aiContent += data.delta;
                  setMessages(prev => prev.map(m => m.id === assistantMsgId ? { ...m, content: aiContent } : m));
                }
              } catch (e) {
                console.error('SSE parse error:', e);
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
    // Simple markdown renderer for code blocks and basic text
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
      // Text
      return <div key={index} className="whitespace-pre-wrap">{part}</div>;
    });
  };

  return (
    <div className="flex h-screen bg-zinc-950 text-zinc-100 font-sans">
      {/* Mobile Sidebar Overlay */}
      <AnimatePresence>
        {isSidebarOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/50 z-40 md:hidden"
            onClick={() => setIsSidebarOpen(false)}
          />
        )}
      </AnimatePresence>

      {/* Sidebar */}
      <div className={`fixed inset-y-0 left-0 z-50 w-72 bg-zinc-900 border-r border-zinc-800 transform transition-transform duration-300 ease-in-out md:relative md:translate-x-0 flex flex-col ${isSidebarOpen ? 'translate-x-0' : '-translate-x-full'}`}>
        <div className="p-4 flex items-center justify-between border-b border-zinc-800">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <Bot className="w-5 h-5" /> ARTH Assistant
          </h2>
          <button onClick={() => setIsSidebarOpen(false)} className="md:hidden p-1 text-zinc-400 hover:text-white">
            <X className="w-5 h-5" />
          </button>
        </div>
        
        <div className="p-3">
          <button
            onClick={createConversation}
            className="w-full flex items-center gap-2 px-4 py-2 bg-zinc-800 hover:bg-zinc-700 rounded-lg text-sm font-medium transition-colors border border-zinc-700"
          >
            <Plus className="w-4 h-4" /> New Chat
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-3 pb-3 space-y-1">
          {conversations.length === 0 ? (
            <div className="text-center py-6 text-zinc-500 text-sm">No conversations yet</div>
          ) : (
            conversations.map(conv => (
              <div
                key={conv.id}
                onClick={() => { setActiveConversationId(conv.id); setIsSidebarOpen(false); }}
                className={`group flex items-center justify-between px-3 py-2.5 rounded-lg cursor-pointer transition-colors ${activeConversationId === conv.id ? 'bg-zinc-800 text-white' : 'text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-200'}`}
              >
                <div className="flex items-center gap-3 truncate">
                  <MessageSquare className="w-4 h-4 shrink-0" />
                  <span className="truncate text-sm">{conv.title}</span>
                </div>
                <button
                  onClick={(e) => deleteConversation(conv.id, e)}
                  className="opacity-0 group-hover:opacity-100 p-1 text-zinc-500 hover:text-red-400 transition-opacity"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <header className="h-14 border-b border-zinc-800 flex items-center px-4 bg-zinc-950/80 backdrop-blur sticky top-0 z-10 shrink-0">
          <button
            onClick={() => setIsSidebarOpen(true)}
            className="md:hidden p-2 -ml-2 mr-2 text-zinc-400 hover:text-white rounded-lg hover:bg-zinc-800"
          >
            <Menu className="w-5 h-5" />
          </button>
          <h1 className="text-sm font-medium text-zinc-300">
            {conversations.find(c => c.id === activeConversationId)?.title || 'New Chat'}
          </h1>
        </header>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-6">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-zinc-500 space-y-4">
              <Bot className="w-12 h-12 text-zinc-700" />
              <p>Start a conversation with the AI assistant</p>
            </div>
          ) : (
            messages.map((msg, idx) => (
              <motion.div
                key={msg.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                className={`flex gap-4 max-w-4xl mx-auto ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}
              >
                <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${msg.role === 'user' ? 'bg-blue-600' : 'bg-zinc-800'}`}>
                  {msg.role === 'user' ? <User className="w-5 h-5 text-white" /> : <Bot className="w-5 h-5 text-zinc-300" />}
                </div>
                <div className={`flex-1 rounded-2xl px-5 py-4 ${msg.role === 'user' ? 'bg-blue-600/20 text-blue-50 ml-12' : 'bg-zinc-900 text-zinc-200 border border-zinc-800 mr-12'}`}>
                  {renderMarkdown(msg.content)}
                  {msg.role === 'assistant' && msg.content === '' && isLoading && idx === messages.length - 1 && (
                    <div className="flex gap-1 items-center h-5">
                      <span className="w-1.5 h-1.5 bg-zinc-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                      <span className="w-1.5 h-1.5 bg-zinc-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                      <span className="w-1.5 h-1.5 bg-zinc-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                    </div>
                  )}
                </div>
              </motion.div>
            ))
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="p-4 md:p-6 bg-zinc-950 border-t border-zinc-900 shrink-0">
          <form onSubmit={sendMessage} className="max-w-4xl mx-auto relative flex items-end gap-2 bg-zinc-900 border border-zinc-800 rounded-xl focus-within:border-zinc-700 focus-within:ring-1 focus-within:ring-zinc-700 transition-all">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  sendMessage();
                }
              }}
              placeholder="Message the assistant..."
              className="w-full max-h-48 min-h-[56px] py-4 pl-4 pr-12 bg-transparent text-zinc-100 placeholder-zinc-500 resize-none outline-none overflow-y-auto"
              rows={1}
            />
            <button
              type="submit"
              disabled={!input.trim() || isLoading}
              className="absolute right-3 bottom-3 p-2 bg-zinc-800 text-zinc-300 rounded-lg hover:bg-zinc-700 hover:text-white disabled:opacity-50 disabled:hover:bg-zinc-800 disabled:hover:text-zinc-300 transition-colors"
            >
              {isLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            </button>
          </form>
          <div className="text-center mt-2 text-xs text-zinc-600">
            AI can make mistakes. Consider verifying important information.
          </div>
        </div>
      </div>
    </div>
  );
}
