'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { useAuthenticatedApi } from '@/lib/auth/useAuthenticatedApi';
import { useAuth } from '@/lib/auth/AuthProvider';
import { 
  Trash2, Bell, Check, Plus, AlertCircle, Clock, 
  Pencil, X, ArrowUpRight, ArrowDownRight, ExternalLink 
} from 'lucide-react';

interface Alert {
  id: string;
  symbol: string;
  alert_type: 'price_above' | 'price_below';
  threshold: number;
  trigger_state: 'armed' | 'triggered';
  last_evaluated_value?: number | null;
  last_evaluated_price?: number | null;
  last_triggered_at?: string | null;
  created_at: string;
  currency?: string;
}

interface Notification {
  id: string;
  alert_id?: string;
  title?: string;
  body?: string;
  message?: string;
  is_read: boolean;
  created_at: string;
  symbol?: string;
  alert_type?: 'price_above' | 'price_below';
  threshold?: number;
  last_evaluated_value?: number;
  currency?: string;
}

export default function AlertsPage() {
  const { user, loading: authLoading } = useAuth();
  const api = useAuthenticatedApi();
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [symbol, setSymbol] = useState('');
  const [alertType, setAlertType] = useState<'price_above' | 'price_below'>('price_above');
  const [threshold, setThreshold] = useState('');
  const [formError, setFormError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Edit Modal State
  const [editingAlert, setEditingAlert] = useState<Alert | null>(null);
  const [editThreshold, setEditThreshold] = useState('');
  const [editAlertType, setEditAlertType] = useState<'price_above' | 'price_below'>('price_above');
  const [editLoading, setEditLoading] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  const fetchAlertsAndNotifications = async () => {
    try {
      const [alertsRes, notifsRaw] = await Promise.all([
        api.get<Alert[]>('/api/v1/user/alerts'),
        api.get<any>('/api/v1/user/notifications')
      ]);
      if (alertsRes) setAlerts(alertsRes);
      const notifsItems = Array.isArray(notifsRaw) ? notifsRaw : (notifsRaw?.items || []);
      if (notifsItems) setNotifications(notifsItems);
    } catch (error) {
      console.error('Failed to fetch alerts & notifications', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!authLoading && user) {
      fetchAlertsAndNotifications();
    }
  }, [authLoading, user]);

  const handleCreateAlert = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!symbol || !threshold) return;
    setFormError(null);
    try {
      await api.post('/api/v1/user/alerts', {
        symbol: symbol.toUpperCase(),
        alert_type: alertType,
        threshold: parseFloat(threshold)
      });
      setSymbol('');
      setThreshold('');
      fetchAlertsAndNotifications();
    } catch (error: any) {
      console.error('Failed to create alert', error);
      const msg = error?.message || error?.detail || '';
      if (msg.includes('Duplicate') || msg.includes('409') || error?.status === 409) {
        setFormError('An active alert with this threshold already exists for this symbol.');
      } else if (msg.includes('Max 50') || msg.includes('429')) {
        setFormError('Maximum 50 active alerts reached. Please remove an alert to add a new one.');
      } else {
        setFormError(msg || 'Failed to create alert. Please check your inputs.');
      }
    }
  };

  const handleOpenEdit = (alert: Alert) => {
    setEditingAlert(alert);
    setEditThreshold(alert.threshold.toString());
    setEditAlertType(alert.alert_type);
    setEditError(null);
  };

  const handleSaveEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingAlert || !editThreshold) return;
    setEditLoading(true);
    setEditError(null);
    try {
      const updated = await api.patch<Alert>(`/api/v1/user/alerts/${editingAlert.id}`, {
        threshold: parseFloat(editThreshold),
        alert_type: editAlertType,
      });
      if (updated) {
        setAlerts(prev => prev.map(a => a.id === editingAlert.id ? { ...a, ...updated } : a));
      }
      setEditingAlert(null);
      fetchAlertsAndNotifications();
    } catch (err: any) {
      console.error('Failed to edit alert', err);
      setEditError(err?.message || 'Failed to update alert');
    } finally {
      setEditLoading(false);
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
      await api.post(`/api/v1/user/notifications/${id}/read`, {});
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
            <option value="price_above">Price Above (≥)</option>
            <option value="price_below">Price Below (≤)</option>
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
        {formError && (
          <div className="mt-3 p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-xs font-mono flex items-center justify-between animate-fadeIn">
            <span>{formError}</span>
            <button
              type="button"
              onClick={() => setFormError(null)}
              className="text-red-400/60 hover:text-red-400 text-sm font-bold ml-2 cursor-pointer"
            >
              ×
            </button>
          </div>
        )}
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
              const sym = alert.symbol || '';
              const isINR = sym.endsWith('.NS') || sym.endsWith('.BO');
              const currency = alert.currency || (isINR ? '₹' : '$');
              const thresh = Number(alert.threshold ?? 0);
              const lastPrice = alert.last_evaluated_value ?? alert.last_evaluated_price;
              const hasLastPrice = lastPrice != null && !isNaN(Number(lastPrice));
              const diffPct = hasLastPrice && thresh > 0 ? ((Number(lastPrice) - thresh) / thresh) * 100 : null;

              return (
                <div key={alert.id} className="card p-4 flex items-center justify-between hover:border-[var(--border-bright)] transition-colors">
                  <div className="flex items-center gap-4">
                    <Link
                      href={`/markets/${alert.symbol}`}
                      className="w-10 h-10 rounded-full bg-[rgba(255,255,255,0.04)] border border-[rgba(255,255,255,0.08)] flex items-center justify-center font-mono text-xs font-bold text-[var(--text)] hover:border-[var(--green)]/50 transition-colors"
                    >
                      {alert.symbol.slice(0, 2)}
                    </Link>
                    <div>
                      <div className="flex items-center gap-2 mb-1">
                        <Link
                          href={`/markets/${alert.symbol}`}
                          className="font-mono text-sm font-bold text-white hover:text-[var(--green)] flex items-center gap-1 transition-colors"
                        >
                          {alert.symbol}
                          <ExternalLink className="w-3 h-3 text-[var(--text-dim)]" />
                        </Link>
                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-mono font-medium ${
                          isArmed 
                            ? 'bg-[rgba(16,185,129,0.12)] text-[var(--green)] border border-[rgba(16,185,129,0.25)]' 
                            : 'bg-[rgba(245,158,11,0.12)] text-[var(--gold)] border border-[rgba(245,158,11,0.25)]'
                        }`}>
                          {alert.trigger_state.toUpperCase()}
                        </span>
                      </div>
                      <div className="text-xs font-mono text-[var(--text-dim)] flex flex-wrap items-center gap-2">
                        <span>
                          Target: {alert.alert_type === 'price_above' ? '≥' : '≤'} <strong className="text-white">{currency}{!isNaN(thresh) ? thresh.toFixed(2) : '—'}</strong>
                        </span>
                        {hasLastPrice && (
                          <span className="text-[var(--text-muted)]">
                            · Last: <span className="text-white font-medium">{currency}{Number(lastPrice).toFixed(2)}</span>
                          </span>
                        )}
                        {diffPct != null && (
                          <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                            diffPct >= 0 ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'
                          }`}>
                            {diffPct >= 0 ? `+${diffPct.toFixed(2)}%` : `${diffPct.toFixed(2)}%`}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => handleOpenEdit(alert)}
                      className="p-2 text-[var(--text-dim)] hover:text-white hover:bg-white/[0.06] rounded-full transition-colors cursor-pointer"
                      title="Edit Alert"
                    >
                      <Pencil className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleDeleteAlert(alert.id)}
                      className="p-2 text-[var(--text-dim)] hover:text-[var(--red)] hover:bg-[rgba(239,68,68,0.1)] rounded-full transition-colors cursor-pointer"
                      title="Delete Alert"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
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
            {notifications.map((notif) => {
              // Extract symbol from notification or parse from title
              const displaySymbol = notif.symbol || (notif.title ? notif.title.split(' ')[0] : 'ALERT');
              const isCrossAbove = (notif.title && notif.title.includes('above')) || notif.alert_type === 'price_above';

              return (
                <div
                  key={notif.id}
                  className={`p-4 rounded-xl border flex items-start justify-between gap-4 transition-colors ${
                    notif.is_read 
                      ? 'bg-[var(--surface)] border-[var(--border)] opacity-60' 
                      : 'bg-[var(--surface)] border-[var(--green)]/30 shadow-sm'
                  }`}
                >
                  <div className="flex items-start gap-3.5">
                    <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${
                      isCrossAbove ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'
                    }`}>
                      {isCrossAbove ? <ArrowUpRight className="w-4 h-4" /> : <ArrowDownRight className="w-4 h-4" />}
                    </div>
                    <div>
                      <div className="flex items-center gap-2 mb-1">
                        <Link
                          href={`/markets/${displaySymbol}`}
                          className="font-mono text-xs font-bold text-white hover:text-[var(--green)] flex items-center gap-1 transition-colors"
                        >
                          {displaySymbol}
                        </Link>
                        <span className={`text-[10px] font-mono px-2 py-0.5 rounded-full ${
                          isCrossAbove 
                            ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' 
                            : 'bg-red-500/10 text-red-400 border border-red-500/20'
                        }`}>
                          {isCrossAbove ? '▲ CROSSED ABOVE' : '▼ DROPPED BELOW'}
                        </span>
                      </div>
                      
                      <p className={`text-xs ${notif.is_read ? 'text-[var(--text-muted)]' : 'text-white font-medium'}`}>
                        {notif.body || notif.title || notif.message || 'Price threshold reached'}
                      </p>

                      <div className="flex items-center gap-1 mt-1 text-[10px] font-mono text-[var(--text-dim)]">
                        <Clock className="w-3 h-3" />
                        {new Date(notif.created_at).toLocaleString()}
                      </div>
                    </div>
                  </div>
                  {!notif.is_read && (
                    <button
                      onClick={() => handleMarkRead(notif.id)}
                      className="p-1.5 text-[var(--text-dim)] hover:text-[var(--green)] hover:bg-[rgba(16,185,129,0.1)] rounded-full transition-colors cursor-pointer"
                      title="Mark as read"
                    >
                      <Check className="w-4 h-4" />
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Edit Alert Modal */}
      {editingAlert && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4 animate-fadeIn">
          <div className="card p-6 max-w-md w-full border border-white/[0.1] shadow-2xl relative">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-heading text-sm font-bold uppercase tracking-wider text-white flex items-center gap-2">
                <Pencil className="w-4 h-4 text-[var(--green)]" />
                Edit Trigger: {editingAlert.symbol}
              </h3>
              <button
                onClick={() => setEditingAlert(null)}
                className="text-[var(--text-dim)] hover:text-white transition-colors cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleSaveEdit} className="space-y-4">
              <div>
                <label className="block text-[11px] font-mono text-[var(--text-muted)] mb-1">
                  Condition Direction
                </label>
                <select
                  value={editAlertType}
                  onChange={(e) => setEditAlertType(e.target.value as any)}
                  className="w-full bg-[var(--surface-2)] border border-[var(--border)] rounded-lg px-3 py-2 text-xs font-mono text-[var(--text)] outline-none focus:border-[var(--green)]/50"
                >
                  <option value="price_above">Price Above (≥)</option>
                  <option value="price_below">Price Below (≤)</option>
                </select>
              </div>

              <div>
                <label className="block text-[11px] font-mono text-[var(--text-muted)] mb-1">
                  Threshold Price ({editingAlert.currency || (editingAlert.symbol.endsWith('.NS') ? '₹' : '$')})
                </label>
                <input
                  type="number"
                  step="0.01"
                  value={editThreshold}
                  onChange={(e) => setEditThreshold(e.target.value)}
                  className="w-full bg-[var(--surface-2)] border border-[var(--border)] rounded-lg px-3 py-2 text-xs font-mono text-[var(--text)] outline-none focus:border-[var(--green)]/50"
                  required
                />
              </div>

              {editError && (
                <div className="p-2.5 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-xs font-mono">
                  {editError}
                </div>
              )}

              <div className="flex items-center justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setEditingAlert(null)}
                  className="px-4 py-2 rounded-lg text-xs font-mono text-[var(--text-dim)] hover:text-white transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={editLoading}
                  className="bg-[var(--green)] hover:bg-[var(--green-hover)] text-black px-4 py-2 rounded-lg text-xs font-bold transition-all cursor-pointer disabled:opacity-50"
                >
                  {editLoading ? 'Saving...' : 'Update & Re-arm'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
