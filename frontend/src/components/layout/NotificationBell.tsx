'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { Bell } from 'lucide-react';
import { useAuth } from '@/lib/auth/AuthProvider';
import { useAuthenticatedApi } from '@/lib/auth/useAuthenticatedApi';

interface Notification {
  id: string;
  alert_id: string;
  message: string;
  is_read: boolean;
  created_at: string;
}

export default function NotificationBell() {
  const { user } = useAuth();
  const api = useAuthenticatedApi();
  const [unreadCount, setUnreadCount] = useState(0);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Fetch unread count periodically
  const fetchUnreadCount = useCallback(async () => {
    if (!api.isAuthenticated) return;
    try {
      const data = await api.get<{ unread_count: number }>('/api/v1/user/notifications/unread-count');
      setUnreadCount(data.unread_count);
    } catch {
      // Silent — non-fatal
    }
  }, [api]);

  useEffect(() => {
    if (!user) return;
    fetchUnreadCount();
    const interval = setInterval(fetchUnreadCount, 30_000); // every 30s
    return () => clearInterval(interval);
  }, [user, fetchUnreadCount]);

  // Fetch notifications when dropdown opens
  const openDropdown = useCallback(async () => {
    setIsOpen(true);
    if (!api.isAuthenticated) return;
    setLoading(true);
    try {
      const data = await api.get<Notification[]>('/api/v1/user/notifications?limit=10');
      setNotifications(Array.isArray(data) ? data : []);
    } catch {
      // Silent
    } finally {
      setLoading(false);
    }
  }, [api]);

  // Mark all as read
  const markAllRead = useCallback(async () => {
    if (!api.isAuthenticated) return;
    try {
      await api.post('/api/v1/user/notifications/read-all');
      setUnreadCount(0);
      setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
    } catch {
      // Silent
    }
  }, [api]);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  if (!user) return null;

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => (isOpen ? setIsOpen(false) : openDropdown())}
        className="relative p-2 text-[var(--text-muted)] hover:text-white rounded-lg hover:bg-white/[0.04] transition-all cursor-pointer"
        aria-label="Notifications"
      >
        <Bell className="w-4 h-4" />
        {unreadCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 bg-red-500 text-white text-[9px] font-bold rounded-full min-w-[16px] h-[16px] flex items-center justify-center px-0.5">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {isOpen && (
        <div className="absolute right-0 top-full mt-2 w-80 max-h-96 bg-[#090e0c]/95 backdrop-blur-2xl border border-white/[0.08] rounded-2xl shadow-[0_20px_50px_rgba(0,0,0,0.8)] overflow-hidden z-50">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.06]">
            <span className="text-xs font-semibold text-white">Notifications</span>
            {unreadCount > 0 && (
              <button
                onClick={markAllRead}
                className="text-[11px] text-emerald-400 hover:text-emerald-300 font-medium cursor-pointer"
              >
                Mark all read
              </button>
            )}
          </div>

          {/* Body */}
          <div className="overflow-y-auto max-h-[320px]">
            {loading ? (
              <div className="p-4 text-center text-[var(--text-dim)] text-xs font-mono">Loading...</div>
            ) : notifications.length === 0 ? (
              <div className="p-6 text-center text-[var(--text-dim)] text-xs font-mono">
                No notifications yet
              </div>
            ) : (
              notifications.map((n) => (
                <div
                  key={n.id}
                  className={`px-4 py-3 border-b border-white/[0.04] ${
                    n.is_read ? 'opacity-50' : ''
                  }`}
                >
                  <p className="text-xs text-[var(--text)]">{n.message}</p>
                  <p className="text-[10px] text-[var(--text-dim)] font-mono mt-1">
                    {new Date(n.created_at).toLocaleString()}
                  </p>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
