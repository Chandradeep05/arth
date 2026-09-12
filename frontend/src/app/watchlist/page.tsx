'use client';

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useAuth } from '@/lib/auth/AuthProvider';
import { useAuthenticatedApi } from '@/lib/auth/useAuthenticatedApi';
import { apiClient } from '@/lib/api';
import WatchlistTable, { type WatchlistItem, type SortField, type SortDir } from '@/components/watchlist/WatchlistTable';
import LoadingSkeleton from '@/components/shared/LoadingSkeleton';
import Disclaimer from '@/components/shared/Disclaimer';
import { useWebSocket } from '@/lib/useWebSocket';
import { Star, Plus, Search, RefreshCw, Trash2, X } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

// Types
interface Watchlist {
  id: string;
  name: string;
  is_default: boolean;
  item_count: number;
  created_at: string;
}

interface WatchlistAPIItem {
  id: string;
  symbol: string;
  added_at: string;
}

export default function WatchlistPage() {
  const { user, loading: authLoading } = useAuth();
  const api = useAuthenticatedApi();
  
  const [watchlists, setWatchlists] = useState<Watchlist[]>([]);
  const [activeListId, setActiveListId] = useState<string | null>(null);
  const [apiItems, setApiItems] = useState<WatchlistAPIItem[]>([]);
  const [marketData, setMarketData] = useState<Record<string, any>>({});
  
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  
  // UI states
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newListName, setNewListName] = useState('');
  const [showAddSymbolModal, setShowAddSymbolModal] = useState(false);
  const [newSymbol, setNewSymbol] = useState('');
  
  const [sortField, setSortField] = useState<SortField>('symbol');
  const [sortDir, setSortDir] = useState<SortDir>('asc');

  // Load watchlists
  const loadWatchlists = useCallback(async () => {
    try {
      setIsLoading(true);
      const res = await api.get<any>('/user/watchlists');
      const lists: Watchlist[] = (Array.isArray(res) ? res : res?.data) || [];
      setWatchlists(lists);
      
      if (lists.length > 0) {
        const defaultList = lists.find((l: Watchlist) => l.is_default) || lists[0];
        setActiveListId(defaultList.id);
      } else {
        setActiveListId(null);
        setApiItems([]);
        setMarketData({});
      }
    } catch (err) {
      console.error('Failed to load watchlists', err);
    } finally {
      setIsLoading(false);
    }
  }, [api]);

  useEffect(() => {
    if (!authLoading && user) {
      loadWatchlists();
    }
  }, [authLoading, user, loadWatchlists]);

  // Load items and market data for active list
  const loadActiveListItems = useCallback(async (isRefresh = false) => {
    if (!activeListId) return;
    try {
      if (isRefresh) setIsRefreshing(true);
      
      const res = await api.get<any>(`/user/watchlists/${activeListId}/items`);
      const items: WatchlistAPIItem[] = (Array.isArray(res) ? res : res?.data) || [];
      setApiItems(items);
      
      if (items.length > 0) {
        const symbols = items.map(i => i.symbol);
        const marketRes = await apiClient.post<any>('/market/batch', { symbols });
        const quotes = marketRes?.data?.quotes || marketRes?.quotes;
        if (quotes) {
          setMarketData(quotes);
        }
      } else {
        setMarketData({});
      }
    } catch (err) {
      console.error('Failed to load items', err);
    } finally {
      if (isRefresh) setIsRefreshing(false);
    }
  }, [activeListId, api]);

  useEffect(() => {
    if (activeListId) {
      loadActiveListItems();
    }
  }, [activeListId, loadActiveListItems]);

  // Handle WebSocket updates
  const activeSymbols = useMemo(() => apiItems.map(i => i.symbol), [apiItems]);
  const { prices } = useWebSocket(activeSymbols);

  useEffect(() => {
    if (prices.size > 0) {
      setMarketData(prev => {
        const next = { ...prev };
        prices.forEach((update, sym) => {
          next[sym] = {
            ...(next[sym] || {}),
            price: update.price,
            change: update.change,
            change_pct: update.change_percent,
            volume: update.volume,
            day_high: update.high,
            day_low: update.low,
            timestamp: update.timestamp,
          };
        });
        return next;
      });
    }
  }, [prices]);

  // Actions
  const handleCreateList = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newListName.trim()) return;
    
    try {
      const res = await api.post<any>('/user/watchlists', { name: newListName.trim() });
      const newList: Watchlist = res?.data || res;
      if (newList && newList.id) {
        setWatchlists(prev => [...prev, newList]);
        setActiveListId(newList.id);
      }
      setShowCreateModal(false);
      setNewListName('');
    } catch (err) {
      console.error('Failed to create watchlist', err);
    }
  };

  const handleDeleteList = async (id: string) => {
    if (!window.confirm('Are you sure you want to delete this watchlist?')) return;
    try {
      await api.delete(`/user/watchlists/${id}`);
      setWatchlists(prev => prev.filter(l => l.id !== id));
      if (activeListId === id) {
        const remaining = watchlists.filter(l => l.id !== id);
        setActiveListId(remaining.length > 0 ? remaining[0].id : null);
      }
    } catch (err) {
      console.error('Failed to delete watchlist', err);
    }
  };

  const handleAddSymbol = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeListId || !newSymbol.trim()) return;
    
    try {
      const symbol = newSymbol.trim().toUpperCase();
      await api.post(`/user/watchlists/${activeListId}/items`, { symbol });
      setShowAddSymbolModal(false);
      setNewSymbol('');
      loadActiveListItems();
    } catch (err) {
      console.error('Failed to add symbol', err);
    }
  };

  const handleRemoveSymbol = async (symbol: string) => {
    if (!activeListId) return;
    try {
      await api.delete(`/user/watchlists/${activeListId}/items/${symbol}`);
      setApiItems(prev => prev.filter(i => i.symbol !== symbol));
    } catch (err) {
      console.error('Failed to remove symbol', err);
    }
  };

  // Prepare table data
  const tableData: WatchlistItem[] = useMemo(() => {
    return apiItems.map(item => {
      const quote = marketData[item.symbol] || {};
      return {
        symbol: item.symbol,
        price: quote.price || 0,
        change: quote.change || 0,
        changePct: quote.change_pct || 0,
        volume: quote.volume || 0,
        dayHigh: quote.day_high || 0,
        dayLow: quote.day_low || 0,
        marketCap: quote.market_cap || 0,
        prevClose: quote.prev_close || 0,
        timestamp: quote.timestamp || new Date().toISOString()
      };
    });
  }, [apiItems, marketData]);

  if (authLoading || isLoading) {
    return (
      <div className="space-y-6 animate-fadeIn">
        <LoadingSkeleton />
      </div>
    );
  }

  const activeList = watchlists.find(l => l.id === activeListId);

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="font-heading text-xl font-extrabold tracking-tight text-[var(--text)] flex items-center gap-2">
            <Star className="text-[var(--gold)] w-5 h-5 fill-[var(--gold)]/20" />
            Watchlists & Holdings
          </h1>
          <p className="text-xs text-[var(--text-muted)] mt-1 font-mono">
            Track custom asset baskets with real-time streaming quotes & risk metrics
          </p>
        </div>
        
        <button 
          onClick={() => setShowCreateModal(true)}
          className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-full bg-[rgba(255,255,255,0.04)] hover:bg-[rgba(255,255,255,0.08)] border border-[var(--border)] text-xs font-medium text-[var(--text)] transition-all cursor-pointer w-fit"
        >
          <Plus size={14} className="text-[var(--green)]" />
          New Watchlist
        </button>
      </div>

      {/* Tabs */}
      {watchlists.length > 0 ? (
        <div className="flex items-center gap-2 overflow-x-auto no-scrollbar pb-1">
          {watchlists.map(list => {
            const isActive = activeListId === list.id;
            return (
              <button 
                key={list.id} 
                onClick={() => setActiveListId(list.id)}
                className={`flex items-center gap-2 px-3.5 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-all cursor-pointer ${
                  isActive 
                    ? 'bg-[rgba(16,185,129,0.12)] text-[var(--green)] border border-[rgba(16,185,129,0.3)] shadow-[0_0_12px_rgba(16,185,129,0.1)]' 
                    : 'bg-[rgba(255,255,255,0.03)] text-[var(--text-muted)] border border-[rgba(255,255,255,0.06)] hover:text-white hover:bg-[rgba(255,255,255,0.06)]'
                }`}
              >
                <span>{list.name}</span>
                <span className={`text-[10px] font-mono px-1.5 py-0.2 rounded-full ${
                  isActive ? 'bg-[var(--green)]/20 text-[var(--green)]' : 'bg-[rgba(255,255,255,0.06)] text-[var(--text-dim)]'
                }`}>
                  {list.item_count || 0}
                </span>
              </button>
            );
          })}
        </div>
      ) : (
        <div className="text-center py-12 card">
          <Star className="mx-auto text-[var(--text-dim)] mb-3 opacity-40" size={36} />
          <h3 className="text-sm font-semibold mb-1 text-[var(--text)]">No watchlists found</h3>
          <p className="text-xs text-[var(--text-dim)] mb-4 font-mono">Create your first watchlist to start tracking assets.</p>
          <button 
            onClick={() => setShowCreateModal(true)}
            className="bg-[var(--green)] hover:bg-[var(--green-hover)] text-black px-4 py-2 rounded-full text-xs font-bold transition-colors cursor-pointer"
          >
            Create Watchlist
          </button>
        </div>
      )}

      {/* Active List Actions & Table */}
      {activeListId && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-2.5">
              <h2 className="font-heading text-sm font-bold text-[var(--text)] uppercase tracking-wider">
                {activeList?.name}
              </h2>
              {activeList && !activeList.is_default && (
                <button 
                  onClick={() => handleDeleteList(activeList.id)}
                  className="text-[var(--text-dim)] hover:text-[var(--red)] p-1 rounded-md transition-colors cursor-pointer"
                  title="Delete watchlist"
                >
                  <Trash2 size={13} />
                </button>
              )}
            </div>
            
            <div className="flex items-center gap-2">
              <button 
                onClick={() => loadActiveListItems(true)}
                disabled={isRefreshing}
                className={`p-1.5 bg-[rgba(255,255,255,0.03)] border border-[var(--border)] rounded-full text-[var(--text-dim)] hover:text-white transition-colors cursor-pointer ${isRefreshing ? 'opacity-50' : ''}`}
                title="Refresh market quotes"
              >
                <RefreshCw size={14} className={isRefreshing ? 'animate-spin' : ''} />
              </button>
              <button 
                onClick={() => setShowAddSymbolModal(true)}
                className="flex items-center gap-1.5 bg-[var(--green)] hover:bg-[var(--green-hover)] text-black px-3.5 py-1.5 rounded-full text-xs font-bold transition-colors cursor-pointer shadow-sm"
              >
                <Plus size={14} />
                Add Symbol
              </button>
            </div>
          </div>

          <div className="min-h-[350px]">
            {apiItems.length > 0 ? (
              <WatchlistTable 
                items={tableData}
                sortBy={sortField}
                sortDir={sortDir}
                onSort={(field) => {
                  if (sortField === field) {
                    setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
                  } else {
                    setSortField(field);
                    setSortDir('desc');
                  }
                }}
                onRemove={handleRemoveSymbol}
              />
            ) : (
              <div className="card flex flex-col items-center justify-center h-[300px] text-[var(--text-dim)]">
                <Search size={36} className="mb-3 opacity-30" />
                <p className="text-sm font-medium text-[var(--text)] mb-1">This watchlist is empty</p>
                <p className="text-xs text-[var(--text-dim)] font-mono mb-4">Add symbols like RELIANCE.NS, TCS.NS or AAPL</p>
                <button 
                  onClick={() => setShowAddSymbolModal(true)}
                  className="bg-[rgba(255,255,255,0.05)] hover:bg-[rgba(255,255,255,0.1)] border border-[var(--border)] text-white px-4 py-2 rounded-full text-xs font-semibold transition-colors cursor-pointer"
                >
                  Add First Symbol
                </button>
              </div>
            )}
          </div>
        </div>
      )}
      
      <div className="mt-8">
        <Disclaimer />
      </div>

      {/* Modals */}
      <AnimatePresence>
        {showCreateModal && (
          <motion.div 
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md"
          >
            <motion.div 
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="card w-full max-w-md p-6 shadow-2xl relative"
            >
              <div className="flex justify-between items-center mb-5">
                <h3 className="font-heading text-base font-bold text-[var(--text)]">Create Watchlist</h3>
                <button onClick={() => setShowCreateModal(false)} className="text-[var(--text-dim)] hover:text-white cursor-pointer">
                  <X size={18} />
                </button>
              </div>
              <form onSubmit={handleCreateList}>
                <div className="mb-5">
                  <label className="block text-xs font-mono text-[var(--text-muted)] mb-2">Watchlist Name</label>
                  <input 
                    type="text" 
                    value={newListName}
                    onChange={e => setNewListName(e.target.value)}
                    placeholder="e.g. High Conviction, Nifty 50, US Tech"
                    className="w-full bg-[var(--surface-2)] border border-[var(--border)] rounded-lg px-3.5 py-2.5 text-xs text-white placeholder:text-[var(--text-dim)] font-mono focus:outline-none focus:border-[var(--green)] transition-colors"
                    autoFocus
                  />
                </div>
                <div className="flex justify-end gap-2">
                  <button 
                    type="button" 
                    onClick={() => setShowCreateModal(false)}
                    className="px-4 py-2 rounded-full text-xs text-[var(--text-muted)] hover:bg-[rgba(255,255,255,0.05)] transition-colors cursor-pointer"
                  >
                    Cancel
                  </button>
                  <button 
                    type="submit"
                    disabled={!newListName.trim()}
                    className="bg-[var(--green)] hover:bg-[var(--green-hover)] text-black px-4 py-2 rounded-full text-xs font-bold disabled:opacity-40 transition-colors cursor-pointer"
                  >
                    Create
                  </button>
                </div>
              </form>
            </motion.div>
          </motion.div>
        )}

        {showAddSymbolModal && (
          <motion.div 
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md"
          >
            <motion.div 
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="card w-full max-w-md p-6 shadow-2xl relative"
            >
              <div className="flex justify-between items-center mb-5">
                <h3 className="font-heading text-base font-bold text-[var(--text)]">Add Symbol</h3>
                <button onClick={() => setShowAddSymbolModal(false)} className="text-[var(--text-dim)] hover:text-white cursor-pointer">
                  <X size={18} />
                </button>
              </div>
              <form onSubmit={handleAddSymbol}>
                <div className="mb-5">
                  <label className="block text-xs font-mono text-[var(--text-muted)] mb-2">Symbol or Ticker</label>
                  <input 
                    type="text" 
                    value={newSymbol}
                    onChange={e => setNewSymbol(e.target.value.toUpperCase())}
                    placeholder="e.g. RELIANCE.NS, TCS.NS, NVDA, AAPL"
                    className="w-full bg-[var(--surface-2)] border border-[var(--border)] rounded-lg px-3.5 py-2.5 text-xs text-white placeholder:text-[var(--text-dim)] font-mono focus:outline-none focus:border-[var(--green)] transition-colors uppercase"
                    autoFocus
                  />
                </div>
                <div className="flex justify-end gap-2">
                  <button 
                    type="button" 
                    onClick={() => setShowAddSymbolModal(false)}
                    className="px-4 py-2 rounded-full text-xs text-[var(--text-muted)] hover:bg-[rgba(255,255,255,0.05)] transition-colors cursor-pointer"
                  >
                    Cancel
                  </button>
                  <button 
                    type="submit"
                    disabled={!newSymbol.trim()}
                    className="bg-[var(--green)] hover:bg-[var(--green-hover)] text-black px-4 py-2 rounded-full text-xs font-bold disabled:opacity-40 transition-colors cursor-pointer"
                  >
                    Add
                  </button>
                </div>
              </form>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
