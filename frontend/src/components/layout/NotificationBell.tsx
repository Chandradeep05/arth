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
        className="relative p-2 text-zinc-400 hover:text-white transition-colors"
        aria-label="Notifications"
      >
        <Bell className="w-5 h-5" />
        {unreadCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 bg-red-500 text-white text-[10px] font-bold rounded-full min-w-[18px] h-[18px] flex items-center justify-center px-1">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {isOpen && (
        <div className="absolute right-0 top-full mt-2 w-80 max-h-96 bg-zinc-900 border border-zinc-700 rounded-lg shadow-xl overflow-hidden z-50">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-700">
            <span className="text-sm font-semibold text-white">Notifications</span>
            {unreadCount > 0 && (
              <button
                onClick={markAllRead}
                className="text-xs text-blue-400 hover:text-blue-300"
              >
                Mark all read
              </button>
            )}
          </div>

          {/* Body */}
          <div className="overflow-y-auto max-h-[320px]">
            {loading ? (
              <div className="p-4 text-center text-zinc-500 text-sm">Loading...</div>
            ) : notifications.length === 0 ? (
              <div className="p-6 text-center text-zinc-500 text-sm">
                No notifications yet
              </div>
            ) : (
              notifications.map((n) => (
                <div
                  key={n.id}
                  className={`px-4 py-3 border-b border-zinc-800 ${
                    n.is_read ? 'opacity-60' : ''
                  }`}
                >
                  <p className="text-sm text-zinc-200">{n.message}</p>
                  <p className="text-xs text-zinc-500 mt-1">
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
