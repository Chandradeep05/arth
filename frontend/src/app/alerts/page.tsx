'use client';

import React, { useState, useEffect } from 'react';
import { useAuthenticatedApi } from '@/lib/auth/useAuthenticatedApi';
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
        api.get<Alert[]>('/api/v1/user/alerts'),
        api.get<Notification[]>('/api/v1/user/notifications')
      ]);
      if (alertsRes) setAlerts(alertsRes);
      if (notifsRes) setNotifications(notifsRes);
    } catch (error) {
      console.error('Failed to fetch alerts & notifications', error);
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
      await api.post('/api/v1/user/alerts', {
        symbol: symbol.toUpperCase(),
        alert_type: alertType,
        threshold: parseFloat(threshold)
      });
      setSymbol('');
      setThreshold('');
      fetchAlertsAndNotifications();
    } catch (error) {
      console.error('Failed to create alert', error);
    }
  };

  const handleDeleteAlert = async (id: string) => {
    try {
      await api.delete(`/api/v1/user/alerts/${id}`);
      setAlerts(alerts.filter(a => a.id !== id));
    } catch (error) {
      console.error('Failed to delete alert', error);
    }
  };

  const handleMarkRead = async (id: string) => {
    try {
      await api.patch(`/api/v1/user/notifications/${id}/read`, {});
      setNotifications(notifications.map(n => n.id === id ? { ...n, is_read: true } : n));
    } catch (error) {
      console.error('Failed to mark read', error);
    }
  };

  const handleMarkAllRead = async () => {
    try {
      await api.post('/api/v1/user/notifications/read-all', {});
      setNotifications(notifications.map(n => ({ ...n, is_read: true })));
    } catch (error) {
      console.error('Failed to mark all read', error);
    }
  };

  if (loading) {
    return (
      <div className="p-8 text-[var(--text-dim)] font-mono text-xs">
        Loading intelligence alerts & triggers...
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-fadeIn max-w-5xl">
      <div>
        <h1 className="font-heading text-xl font-extrabold tracking-tight text-[var(--text)]">
          Price Alerts & Notifications
        </h1>
        <p className="text-xs text-[var(--text-muted)] mt-1 font-mono">
          Set deterministic thresholds for price breaches and real-time portfolio signals
        </p>
      </div>

      {/* Create Form */}
      <div className="card p-5">
        <h2 className="font-heading text-xs font-bold uppercase tracking-wider text-[var(--text-muted)] mb-3">
          Create Price Threshold
        </h2>
        <form onSubmit={handleCreateAlert} className="flex flex-col sm:flex-row gap-3">
          <input
            type="text"
            placeholder="Symbol (e.g. RELIANCE.NS, AAPL)"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            className="bg-[var(--surface-2)] border border-[var(--border)] rounded-full px-4 py-2.5 flex-1 outline-none text-xs font-mono text-[var(--text)] placeholder:text-[var(--text-dim)] focus:border-[var(--green)]/50 uppercase transition-colors"
            required
          />
          <select
            value={alertType}
            onChange={(e) => setAlertType(e.target.value as any)}
            className="bg-[var(--surface-2)] border border-[var(--border)] rounded-full px-4 py-2.5 text-xs font-mono text-[var(--text)] outline-none focus:border-[var(--green)]/50 transition-colors"
          >
            <option value="price_above">Price Above (&gt;=)</option>
            <option value="price_below">Price Below (&lt;=)</option>
          </select>
          <input
            type="number"
            step="0.01"
            placeholder="Threshold Value"
            value={threshold}
            onChange={(e) => setThreshold(e.target.value)}
            className="bg-[var(--surface-2)] border border-[var(--border)] rounded-full px-4 py-2.5 text-xs font-mono text-[var(--text)] placeholder:text-[var(--text-dim)] outline-none focus:border-[var(--green)]/50 transition-colors sm:w-40"
            required
          />
          <button
            type="submit"
            className="bg-[var(--green)] hover:bg-[var(--green-hover)] text-black px-5 py-2.5 rounded-full text-xs font-bold transition-all cursor-pointer flex items-center justify-center gap-1.5 shadow-sm"
          >
            <Plus className="w-3.5 h-3.5" /> Set Alert
          </button>
        </form>
      </div>

      {/* Active Alerts */}
      <div className="space-y-3">
        <h2 className="font-heading text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">
          Active Watch Triggers ({alerts.length})
        </h2>
        {alerts.length === 0 ? (
          <div className="card p-6 text-center text-xs font-mono text-[var(--text-dim)]">
            No armed price alerts active. Create one above to monitor market breakouts.
          </div>
        ) : (
          <div className="grid gap-3">
            {alerts.map((alert) => {
              const isArmed = alert.trigger_state === 'armed';
              return (
                <div key={alert.id} className="card p-4 flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    <div className="w-9 h-9 rounded-full bg-[rgba(255,255,255,0.04)] border border-[rgba(255,255,255,0.08)] flex items-center justify-center font-mono text-xs font-bold text-[var(--text)]">
                      {alert.symbol.slice(0, 2)}
                    </div>
                    <div>
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className="font-mono text-sm font-bold text-white">{alert.symbol}</span>
                        <span className={`px-2 py-0.2 rounded-full text-[10px] font-mono font-medium ${
                          isArmed 
                            ? 'bg-[rgba(16,185,129,0.12)] text-[var(--green)] border border-[rgba(16,185,129,0.25)]' 
                            : 'bg-[rgba(245,158,11,0.12)] text-[var(--gold)] border border-[rgba(245,158,11,0.25)]'
                        }`}>
                          {alert.trigger_state.toUpperCase()}
                        </span>
                      </div>
                      <div className="text-xs font-mono text-[var(--text-dim)]">
                        Trigger when {alert.alert_type === 'price_above' ? '≥' : '≤'} {alert.threshold.toFixed(2)}
                        {alert.last_evaluated_price && ` · Last Evaluated: ${alert.last_evaluated_price.toFixed(2)}`}
                      </div>
                    </div>
                  </div>
                  <button
                    onClick={() => handleDeleteAlert(alert.id)}
                    className="p-2 text-[var(--text-dim)] hover:text-[var(--red)] hover:bg-[rgba(239,68,68,0.1)] rounded-full transition-colors cursor-pointer"
                    title="Delete Alert"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Notifications Section */}
      <div className="space-y-3 pt-6 border-t border-[var(--border)]">
        <div className="flex items-center justify-between">
          <h2 className="font-heading text-xs font-bold uppercase tracking-wider text-[var(--text-muted)] flex items-center gap-2">
            <Bell className="w-3.5 h-3.5 text-[var(--green)]" /> Notifications Stream
          </h2>
          {notifications.some(n => !n.is_read) && (
            <button
              onClick={handleMarkAllRead}
              className="text-xs text-[var(--text-dim)] hover:text-[var(--green)] font-mono transition-colors cursor-pointer"
            >
              Mark all as read
            </button>
          )}
        </div>
        {notifications.length === 0 ? (
          <div className="card p-6 text-center text-xs font-mono text-[var(--text-dim)]">
            No unread notifications or event triggers.
          </div>
        ) : (
          <div className="space-y-2">
            {notifications.map((notif) => (
              <div
                key={notif.id}
                className={`p-3.5 rounded-xl border flex items-start justify-between gap-4 transition-colors ${
                  notif.is_read 
                    ? 'bg-[var(--surface)] border-[var(--border)] opacity-60' 
                    : 'bg-[var(--surface)] border-[var(--green)]/30 shadow-sm'
                }`}
              >
                <div className="flex items-start gap-3">
                  <AlertCircle className={`w-4 h-4 mt-0.5 shrink-0 ${notif.is_read ? 'text-[var(--text-dim)]' : 'text-[var(--green)]'}`} />
                  <div>
                    <p className={`text-xs ${notif.is_read ? 'text-[var(--text-muted)]' : 'text-white font-medium'}`}>{notif.message}</p>
                    <div className="flex items-center gap-1 mt-1 text-[10px] font-mono text-[var(--text-dim)]">
                      <Clock className="w-3 h-3" />
                      {new Date(notif.created_at).toLocaleString()}
                    </div>
                  </div>
                </div>
                {!notif.is_read && (
                  <button
                    onClick={() => handleMarkRead(notif.id)}
                    className="p-1 text-[var(--text-dim)] hover:text-[var(--green)] hover:bg-[rgba(16,185,129,0.1)] rounded-full transition-colors cursor-pointer"
                    title="Mark as read"
                  >
                    <Check className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
