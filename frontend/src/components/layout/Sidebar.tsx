'use client';

import { useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import {
  LayoutDashboard,
  TrendingUp,
  FileText,
  BarChart3,
  ShieldAlert,
  Star,
  Bot,
  Activity,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';

const navItems = [
  { href: '/', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/markets', label: 'Markets', icon: TrendingUp },
  { href: '/research', label: 'Research', icon: FileText },
  { href: '/financials', label: 'Financials', icon: BarChart3 },
  { href: '/risk', label: 'Risk', icon: ShieldAlert },
  { href: '/watchlist', label: 'Watchlist', icon: Star },
  { href: '/assistant', label: 'Assistant', icon: Bot },
  { href: '/system', label: 'System', icon: Activity },
] as const;

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const pathname = usePathname();

  const sidebarWidth = collapsed ? 64 : 240;

  return (
    <motion.aside
      className="
        fixed left-0 top-0 bottom-0 z-40
        flex flex-col
        bg-[var(--surface)] border-r border-[var(--border)]
        overflow-hidden
      "
      animate={{ width: sidebarWidth }}
      transition={{ duration: 0.25, ease: 'easeInOut' }}
    >
      {/* Logo */}
      <div className="flex items-center h-14 px-4 border-b border-[var(--border)]">
        <Link href="/" className="flex items-center gap-2 overflow-hidden">
          <span
            className="
              font-heading text-xl font-extrabold tracking-tight
              text-[var(--accent)]
              drop-shadow-[0_0_12px_rgba(0,212,255,0.4)]
              shrink-0
            "
          >
            ARTH
          </span>
          <AnimatePresence>
            {!collapsed && (
              <motion.span
                initial={{ opacity: 0, width: 0 }}
                animate={{ opacity: 1, width: 'auto' }}
                exit={{ opacity: 0, width: 0 }}
                className="text-xs font-mono text-[var(--text-muted)] whitespace-nowrap overflow-hidden"
              >
                Intelligence
              </motion.span>
            )}
          </AnimatePresence>
        </Link>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-4 space-y-1 px-2">
        {navItems.map(({ href, label, icon: Icon }) => {
          const isActive = href === '/' ? pathname === '/' : pathname.startsWith(href);

          return (
            <Link
              key={href}
              href={href}
              className={`
                group relative flex items-center gap-3 rounded-md
                h-10 transition-colors duration-150
                ${collapsed ? 'justify-center px-2' : 'px-3'}
                ${
                  isActive
                    ? 'bg-[var(--accent)]/10 text-[var(--accent)]'
                    : 'text-[var(--text-muted)] hover:bg-[var(--surface-2)] hover:text-[var(--text)]'
                }
              `}
              title={collapsed ? label : undefined}
            >
              {/* Active indicator bar */}
              {isActive && (
                <motion.div
                  layoutId="sidebar-active"
                  className="absolute left-0 top-1 bottom-1 w-0.5 rounded-full bg-[var(--accent)]"
                  transition={{ type: 'spring', stiffness: 350, damping: 30 }}
                />
              )}

              <Icon className="h-5 w-5 shrink-0" />

              <AnimatePresence>
                {!collapsed && (
                  <motion.span
                    initial={{ opacity: 0, width: 0 }}
                    animate={{ opacity: 1, width: 'auto' }}
                    exit={{ opacity: 0, width: 0 }}
                    className="text-sm font-medium whitespace-nowrap overflow-hidden"
                  >
                    {label}
                  </motion.span>
                )}
              </AnimatePresence>
            </Link>
          );
        })}
      </nav>

      {/* Collapse Toggle */}
      <div className="border-t border-[var(--border)] p-2">
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="
            flex items-center justify-center w-full h-9 rounded-md
            text-[var(--text-muted)] hover:text-[var(--text)]
            hover:bg-[var(--surface-2)]
            transition-colors duration-150
            cursor-pointer
          "
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? (
            <ChevronRight className="h-4 w-4" />
          ) : (
            <ChevronLeft className="h-4 w-4" />
          )}
        </button>
      </div>
    </motion.aside>
  );
}
