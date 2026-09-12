'use client'

import React, { useState, useEffect } from 'react';
import { useAuthenticatedApi } from '@/lib/auth/useAuthenticatedApi';
import { useAuth } from '@/lib/auth/AuthProvider';
import { Trash2, Bell, Check, Plus, AlertCircle, Clock } from 'lucide-react';

interface Alert {
  id: string;
  symbol: string;
  alert_type: 'price_above' | 'price_below';
  threshold: number;
  trigger_state: 'armed' | 'triggered';
  last_evaluated_price: number | null;
  last_evaluated_at: string | null;
  created_at: string;
}

interface Notification {
  id: string;
  alert_id: string;
  message: string;
  is_read: boolean;
  created_at: string;
}

export default function AlertsPage() {
  const api = useAuthenticatedApi();
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [symbol, setSymbol] = useState('');
  const [alertType, setAlertType] = useState<'price_above' | 'price_below'>('price_above');
  const [threshold, setThreshold] = useState('');
  const [loading, setLoading] = useState(true);

  const fetchAlertsAndNotifications = async () => {
    try {
      const [alertsRes, notifsRes] = await Promise.all([
        api.get('/api/v1/user/alerts'),
        api.get('/api/v1/user/notifications')
      ]);
      if (alertsRes.ok) setAlerts(await alertsRes.json());
      if (notifsRes.ok) setNotifications(await notifsRes.json());
    } catch (error) {
      console.error('Failed to fetch', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAlertsAndNotifications();
  }, []);

  const handleCreateAlert = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!symbol || !threshold) return;
    try {
      const res = await api.post('/api/v1/user/alerts', {
        symbol: symbol.toUpperCase(),
        alert_type: alertType,
        threshold: parseFloat(threshold)
      });
      if (res.ok) {
        setSymbol('');
        setThreshold('');
        fetchAlertsAndNotifications();
      }
    } catch (error) {
      console.error('Failed to create alert', error);
    }
  };

  const handleDeleteAlert = async (id: string) => {
    try {
      const res = await api.delete(`/api/v1/user/alerts/${id}`);
      if (res.ok) {
        setAlerts(alerts.filter(a => a.id !== id));
      }
    } catch (error) {
      console.error('Failed to delete alert', error);
    }
  };

  const handleMarkRead = async (id: string) => {
    try {
      const res = await api.patch(`/api/v1/user/notifications/${id}/read`, {});
      if (res.ok) {
        setNotifications(notifications.map(n => n.id === id ? { ...n, is_read: true } : n));
      }
    } catch (error) {
      console.error('Failed to mark read', error);
    }
  };

  const handleMarkAllRead = async () => {
    try {
      const res = await api.post('/api/v1/user/notifications/read-all', {});
      if (res.ok) {
        setNotifications(notifications.map(n => ({ ...n, is_read: true })));
      }
    } catch (error) {
      console.error('Failed to mark all read', error);
    }
  };

  if (loading) return <div className="p-8 text-zinc-400">Loading alerts...</div>;

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 p-4 md:p-8 space-y-8">
      <div className="max-w-4xl mx-auto space-y-8">
        <div>
          <h1 className="text-3xl font-bold mb-4">Price Alerts</h1>
          <form onSubmit={handleCreateAlert} className="bg-zinc-900 p-4 md:p-6 rounded-xl border border-zinc-800 flex flex-col md:flex-row gap-4">
            <input
              type="text"
              placeholder="Symbol (e.g. AAPL)"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              className="bg-zinc-950 border border-zinc-800 rounded-lg px-4 py-2 flex-1 outline-none focus:border-zinc-500 transition-colors"
              required
            />
            <select
              value={alertType}
              onChange={(e) => setAlertType(e.target.value as any)}
              className="bg-zinc-950 border border-zinc-800 rounded-lg px-4 py-2 flex-1 outline-none focus:border-zinc-500 transition-colors"
            >
              <option value="price_above">Price Above</option>
              <option value="price_below">Price Below</option>
            </select>
            <input
              type="number"
              step="0.01"
              placeholder="Threshold ($)"
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
              className="bg-zinc-950 border border-zinc-800 rounded-lg px-4 py-2 flex-1 outline-none focus:border-zinc-500 transition-colors"
              required
            />
            <button
              type="submit"
              className="bg-white text-black px-6 py-2 rounded-lg font-medium hover:bg-zinc-200 transition-colors flex items-center justify-center gap-2"
            >
              <Plus className="w-4 h-4" /> Add
            </button>
          </form>
        </div>

        <div className="space-y-4">
          <h2 className="text-xl font-semibold text-zinc-300">Active Alerts</h2>
          {alerts.length === 0 ? (
            <p className="text-zinc-500 italic">No active alerts.</p>
          ) : (
            <div className="grid gap-4">
              {alerts.map((alert) => (
                <div key={alert.id} className="bg-zinc-900 p-4 rounded-xl border border-zinc-800 flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-3 mb-1">
                      <span className="font-bold text-lg">{alert.symbol}</span>
                      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                        alert.trigger_state === 'armed' ? 'bg-green-500/10 text-green-500' : 'bg-orange-500/10 text-orange-500'
                      }`}>
                        {alert.trigger_state}
                      </span>
                    </div>
                    <div className="text-sm text-zinc-400">
                      {alert.alert_type === 'price_above' ? 'Above' : 'Below'} ${alert.threshold.toFixed(2)}
                      {alert.last_evaluated_price && ` (Last: $${alert.last_evaluated_price.toFixed(2)})`}
                    </div>
                  </div>
                  <button
                    onClick={() => handleDeleteAlert(alert.id)}
                    className="p-2 text-zinc-500 hover:text-red-400 hover:bg-red-400/10 rounded-lg transition-colors"
                  >
                    <Trash2 className="w-5 h-5" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="space-y-4 pt-8 border-t border-zinc-800">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-semibold text-zinc-300 flex items-center gap-2">
              <Bell className="w-5 h-5" /> Notifications
            </h2>
            {notifications.some(n => !n.is_read) && (
              <button
                onClick={handleMarkAllRead}
                className="text-sm text-zinc-400 hover:text-white transition-colors"
              >
                Mark all as read
              </button>
            )}
          </div>
          {notifications.length === 0 ? (
            <p className="text-zinc-500 italic">No recent notifications.</p>
          ) : (
            <div className="space-y-3">
              {notifications.map((notif) => (
                <div
                  key={notif.id}
                  className={`p-4 rounded-xl border flex items-start justify-between gap-4 transition-colors ${
                    notif.is_read ? 'bg-zinc-900/50 border-zinc-800/50 opacity-70' : 'bg-zinc-900 border-zinc-700'
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <AlertCircle className={`w-5 h-5 mt-0.5 ${notif.is_read ? 'text-zinc-500' : 'text-blue-400'}`} />
                    <div>
                      <p className={notif.is_read ? 'text-zinc-400' : 'text-zinc-100'}>{notif.message}</p>
                      <div className="flex items-center gap-1 mt-1 text-xs text-zinc-500">
                        <Clock className="w-3 h-3" />
                        {new Date(notif.created_at).toLocaleString()}
                      </div>
                    </div>
                  </div>
                  {!notif.is_read && (
                    <button
                      onClick={() => handleMarkRead(notif.id)}
                      className="p-1.5 text-zinc-400 hover:text-white hover:bg-zinc-800 rounded-lg transition-colors"
                      title="Mark as read"
                    >
                      <Check className="w-4 h-4" />
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
