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
  const { user, isLoading: authLoading } = useAuth();
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
      const res = await api.get('/user/watchlists');
      const lists = res.data || [];
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
      
      const res = await api.get(`/user/watchlists/${activeListId}/items`);
      const items: WatchlistAPIItem[] = res.data || [];
      setApiItems(items);
      
      if (items.length > 0) {
        const symbols = items.map(i => i.symbol);
        const marketRes = await apiClient.post('/market/batch', { symbols });
        if (marketRes.data?.quotes) {
          setMarketData(marketRes.data.quotes);
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
  
  const handleWsMessage = useCallback((message: any) => {
    if (message.type === 'market_update' && message.data) {
      const update = message.data;
      if (activeSymbols.includes(update.symbol)) {
        setMarketData(prev => ({
          ...prev,
          [update.symbol]: {
            ...(prev[update.symbol] || {}),
            ...update
          }
        }));
      }
    }
  }, [activeSymbols]);

  const { isConnected } = useWebSocket({
    onMessage: handleWsMessage,
    subscribeOnConnect: activeSymbols.length > 0 ? { type: 'subscribe', channels: ['market_data'], symbols: activeSymbols } : undefined
  });

  // Actions
  const handleCreateList = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newListName.trim()) return;
    
    try {
      const res = await api.post('/user/watchlists', { name: newListName.trim() });
      const newList = res.data;
      setWatchlists(prev => [...prev, newList]);
      setActiveListId(newList.id);
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
      <div className="min-h-screen bg-black text-white p-4 md:p-8 pt-20">
        <LoadingSkeleton />
      </div>
    );
  }

  const activeList = watchlists.find(l => l.id === activeListId);

  return (
    <div className="min-h-screen bg-black text-white p-4 md:p-8 pt-20">
      <div className="max-w-7xl mx-auto space-y-6">
        
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold flex items-center gap-2">
              <Star className="text-yellow-400" size={28} />
              Your Watchlists
            </h1>
            <p className="text-zinc-400 mt-1">Track your favorite assets in real-time</p>
          </div>
          
          <button 
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-2 bg-zinc-800 hover:bg-zinc-700 px-4 py-2 rounded-lg text-sm font-medium transition-colors"
          >
            <Plus size={16} />
            New Watchlist
          </button>
        </div>

        {/* Tabs */}
        {watchlists.length > 0 ? (
          <div className="border-b border-zinc-800 flex overflow-x-auto no-scrollbar">
            {watchlists.map(list => (
              <div 
                key={list.id} 
                className={`flex items-center gap-2 px-4 py-3 cursor-pointer whitespace-nowrap transition-colors ${
                  activeListId === list.id ? 'border-b-2 border-white text-white' : 'text-zinc-500 hover:text-zinc-300'
                }`}
                onClick={() => setActiveListId(list.id)}
              >
                <span className="font-medium">{list.name}</span>
                <span className="text-xs bg-zinc-800 px-2 py-0.5 rounded-full">{list.item_count || 0}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-12 bg-zinc-900/50 rounded-xl border border-zinc-800">
            <Star className="mx-auto text-zinc-600 mb-4" size={48} />
            <h3 className="text-xl font-medium mb-2">No watchlists found</h3>
            <p className="text-zinc-400 mb-6">Create your first watchlist to start tracking assets.</p>
            <button 
              onClick={() => setShowCreateModal(true)}
              className="bg-white text-black hover:bg-zinc-200 px-6 py-2 rounded-lg font-medium transition-colors"
            >
              Create Watchlist
            </button>
          </div>
        )}

        {/* Active List Actions & Table */}
        {activeListId && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <h2 className="text-xl font-semibold flex items-center gap-2">
                {activeList?.name}
                {activeList && !activeList.is_default && (
                  <button 
                    onClick={() => handleDeleteList(activeList.id)}
                    className="text-zinc-500 hover:text-red-400 p-1 rounded-md transition-colors"
                    title="Delete watchlist"
                  >
                    <Trash2 size={16} />
                  </button>
                )}
              </h2>
              
              <div className="flex items-center gap-2">
                <button 
                  onClick={() => loadActiveListItems(true)}
                  disabled={isRefreshing}
                  className={`p-2 bg-zinc-900 border border-zinc-800 rounded-lg text-zinc-400 hover:text-white transition-colors ${isRefreshing ? 'opacity-50' : ''}`}
                  title="Refresh data"
                >
                  <RefreshCw size={18} className={isRefreshing ? 'animate-spin' : ''} />
                </button>
                <button 
                  onClick={() => setShowAddSymbolModal(true)}
                  className="flex items-center gap-2 bg-zinc-100 text-black hover:bg-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
                >
                  <Plus size={16} />
                  Add Symbol
                </button>
              </div>
            </div>

            <div className="bg-zinc-900/50 rounded-xl border border-zinc-800 overflow-hidden min-h-[400px]">
              {apiItems.length > 0 ? (
                <WatchlistTable 
                  data={tableData}
                  sortField={sortField}
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
                <div className="flex flex-col items-center justify-center h-[400px] text-zinc-500">
                  <Search size={48} className="mb-4 opacity-50" />
                  <p className="text-lg mb-2">This watchlist is empty</p>
                  <p className="text-sm mb-4">Add symbols to track their performance</p>
                  <button 
                    onClick={() => setShowAddSymbolModal(true)}
                    className="text-white bg-zinc-800 hover:bg-zinc-700 px-4 py-2 rounded-lg text-sm font-medium transition-colors"
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
      </div>

      {/* Modals */}
      <AnimatePresence>
        {showCreateModal && (
          <motion.div 
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm"
          >
            <motion.div 
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-zinc-900 border border-zinc-800 rounded-xl w-full max-w-md p-6 shadow-2xl"
            >
              <div className="flex justify-between items-center mb-6">
                <h3 className="text-xl font-semibold">Create Watchlist</h3>
                <button onClick={() => setShowCreateModal(false)} className="text-zinc-400 hover:text-white">
                  <X size={24} />
                </button>
              </div>
              <form onSubmit={handleCreateList}>
                <div className="mb-6">
                  <label className="block text-sm font-medium text-zinc-400 mb-2">Watchlist Name</label>
                  <input 
                    type="text" 
                    value={newListName}
                    onChange={e => setNewListName(e.target.value)}
                    placeholder="e.g. Tech Stocks, Crypto..."
                    className="w-full bg-black border border-zinc-800 rounded-lg px-4 py-2 text-white focus:outline-none focus:border-zinc-600"
                    autoFocus
                  />
                </div>
                <div className="flex justify-end gap-3">
                  <button 
                    type="button" 
                    onClick={() => setShowCreateModal(false)}
                    className="px-4 py-2 rounded-lg text-zinc-300 hover:bg-zinc-800 transition-colors"
                  >
                    Cancel
                  </button>
                  <button 
                    type="submit"
                    disabled={!newListName.trim()}
                    className="bg-white text-black px-4 py-2 rounded-lg font-medium disabled:opacity-50 transition-colors"
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
            className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm"
          >
            <motion.div 
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-zinc-900 border border-zinc-800 rounded-xl w-full max-w-md p-6 shadow-2xl"
            >
              <div className="flex justify-between items-center mb-6">
                <h3 className="text-xl font-semibold">Add Symbol</h3>
                <button onClick={() => setShowAddSymbolModal(false)} className="text-zinc-400 hover:text-white">
                  <X size={24} />
                </button>
              </div>
              <form onSubmit={handleAddSymbol}>
                <div className="mb-6">
                  <label className="block text-sm font-medium text-zinc-400 mb-2">Symbol or Ticker</label>
                  <input 
                    type="text" 
                    value={newSymbol}
                    onChange={e => setNewSymbol(e.target.value.toUpperCase())}
                    placeholder="e.g. RELIANCE.NS, BTC-USD..."
                    className="w-full bg-black border border-zinc-800 rounded-lg px-4 py-2 text-white focus:outline-none focus:border-zinc-600 uppercase"
                    autoFocus
                  />
                </div>
                <div className="flex justify-end gap-3">
                  <button 
                    type="button" 
                    onClick={() => setShowAddSymbolModal(false)}
                    className="px-4 py-2 rounded-lg text-zinc-300 hover:bg-zinc-800 transition-colors"
                  >
                    Cancel
                  </button>
                  <button 
                    type="submit"
                    disabled={!newSymbol.trim()}
                    className="bg-white text-black px-4 py-2 rounded-lg font-medium disabled:opacity-50 transition-colors"
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
