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

interface SidebarProps {
  isMobileOpen?: boolean;
  onMobileClose?: () => void;
}

export default function Sidebar({ isMobileOpen = false, onMobileClose }: SidebarProps) {
  const [collapsed, setCollapsed] = useState(false);
  const pathname = usePathname();

  const sidebarWidth = collapsed ? 64 : 240;

  // ── Shared nav content (used by both desktop and mobile) ──────────────────
  function NavContent() {
    return (
      <>
        {/* Logo */}
        <div className="flex items-center h-14 px-4 border-b border-[var(--border)]">
          <Link href="/" className="flex items-center gap-2 overflow-hidden" onClick={onMobileClose}>
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
                onClick={onMobileClose}
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

        {/* Collapse Toggle — desktop only */}
        <div className="border-t border-[var(--border)] p-2 hidden lg:block">
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
      </>
    );
  }

  return (
    <>
      {/* ── Desktop sidebar (lg+): fixed, collapsible ── */}
      <motion.aside
        className="
          fixed left-0 top-0 bottom-0 z-40
          hidden lg:flex flex-col
          bg-[var(--surface)] border-r border-[var(--border)]
          overflow-hidden
        "
        animate={{ width: sidebarWidth }}
        transition={{ duration: 0.25, ease: 'easeInOut' }}
      >
        <NavContent />
      </motion.aside>

      {/* ── Mobile drawer (<lg): slide-in from left ── */}
      <AnimatePresence>
        {isMobileOpen && (
          <>
            {/* Backdrop */}
            <motion.div
              key="mobile-backdrop"
              className="fixed inset-0 z-40 bg-black/50 lg:hidden"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              onClick={onMobileClose}
              aria-hidden="true"
            />

            {/* Drawer panel */}
            <motion.aside
              key="mobile-drawer"
              className="
                fixed left-0 top-0 bottom-0 z-50 w-[250px]
                flex flex-col lg:hidden
                bg-[var(--surface)] border-r border-[var(--border)]
                overflow-hidden
              "
              initial={{ x: -250 }}
              animate={{ x: 0 }}
              exit={{ x: -250 }}
              transition={{ duration: 0.25, ease: 'easeInOut' }}
            >
              <NavContent />
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </>
  );
}
