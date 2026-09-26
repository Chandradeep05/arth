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
  Bell,
  BookMarked,
  ChevronLeft,
  ChevronRight,
  User,
} from 'lucide-react';
import { useAuth } from '@/lib/auth/AuthProvider';

const navItems = [
  { href: '/', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/markets', label: 'Markets', icon: TrendingUp },
  { href: '/research', label: 'Research', icon: FileText },
  { href: '/financials', label: 'Financials', icon: BarChart3 },
  { href: '/risk', label: 'Risk', icon: ShieldAlert },
  { href: '/watchlist', label: 'Watchlist', icon: Star },
  { href: '/assistant', label: 'Assistant', icon: Bot },
  { href: '/alerts', label: 'Alerts', icon: Bell },
  { href: '/research/saved', label: 'Saved Research', icon: BookMarked },
  { href: '/system', label: 'System', icon: Activity },
] as const;

interface SidebarProps {
  isMobileOpen?: boolean;
  onMobileClose?: () => void;
}

export default function Sidebar({ isMobileOpen = false, onMobileClose }: SidebarProps) {
  const [collapsed, setCollapsed] = useState(false);
  const pathname = usePathname();
  const { user, isAdmin } = useAuth();

  const userName = user?.user_metadata?.full_name || (user?.email ? user.email.split('@')[0] : 'Chandradeep');
  const userAvatar = user?.user_metadata?.avatar_url;

  const sidebarWidth = collapsed ? 68 : 240;

  // ── Shared nav content (used by both desktop and mobile) ──────────────────
  function NavContent() {
    return (
      <div className="flex flex-col h-full select-none relative">
        {/* Subtle amber/gold atmospheric glow pool at navigation base (reference finishing) */}
        <div
          className="absolute bottom-0 left-0 right-0 h-56 pointer-events-none z-0"
          style={{
            background: 'radial-gradient(circle at 25% 95%, rgba(245, 158, 11, 0.09) 0%, rgba(217, 119, 6, 0.03) 50%, transparent 80%)',
          }}
          aria-hidden="true"
        />

        {/* Brand Header */}
        <div className="flex items-center justify-between h-16 px-4 border-b border-white/[0.06] relative z-10">
          <Link
            href="/"
            className="flex items-center gap-2.5 overflow-hidden group"
            onClick={onMobileClose}
          >
            {/* ARTH Stylized Glyph */}
            <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center shrink-0 shadow-[0_0_12px_rgba(16,185,129,0.15)] group-hover:border-emerald-500/50 transition-colors">
              <svg
                className="w-4 h-4 text-emerald-400 transform -rotate-12"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M12 2L2 19h20L12 2z" />
              </svg>
            </div>

            <AnimatePresence>
              {!collapsed && (
                <motion.div
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -6 }}
                  className="flex items-baseline gap-1.5 overflow-hidden"
                >
                  <span className="font-heading text-lg font-bold tracking-tight text-white">
                    ARTH
                  </span>
                  <span className="text-[10px] font-mono uppercase tracking-widest text-[var(--text-dim)]">
                    Intelligence
                  </span>
                </motion.div>
              )}
            </AnimatePresence>
          </Link>
        </div>

        {/* Navigation links */}
        <nav className="flex-1 py-4 space-y-1 px-2.5 overflow-y-auto">
          {navItems.map(({ href, label, icon: Icon }) => {
            const isActive = href === '/' ? pathname === '/' : pathname.startsWith(href);

            return (
              <Link
                key={href}
                href={href}
                onClick={onMobileClose}
                className={`
                  group relative flex items-center gap-3 rounded-xl
                  h-10 transition-all duration-150
                  ${collapsed ? 'justify-center px-2' : 'px-3'}
                  ${
                    isActive
                      ? 'bg-emerald-500/10 text-white border border-emerald-500/25 shadow-[0_0_15px_rgba(16,185,129,0.06)]'
                      : 'text-[var(--text-muted)] hover:bg-white/[0.035] hover:text-white border border-transparent'
                  }
                `}
                title={collapsed ? label : undefined}
              >
                {/* Active indicator bar */}
                {isActive && (
                  <motion.div
                    layoutId="sidebar-active"
                    className="absolute left-1 top-2 bottom-2 w-1 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]"
                    transition={{ type: 'spring', stiffness: 350, damping: 30 }}
                  />
                )}

                <Icon
                  className={`h-4.5 w-4.5 shrink-0 transition-colors ${
                    isActive ? 'text-emerald-400' : 'text-[var(--text-dim)] group-hover:text-white'
                  }`}
                />

                <AnimatePresence>
                  {!collapsed && (
                    <motion.span
                      initial={{ opacity: 0, width: 0 }}
                      animate={{ opacity: 1, width: 'auto' }}
                      exit={{ opacity: 0, width: 0 }}
                      className={`text-[13px] font-medium whitespace-nowrap overflow-hidden ${
                        isActive ? 'text-white font-semibold' : 'text-[var(--text-muted)]'
                      }`}
                    >
                      {label}
                    </motion.span>
                  )}
                </AnimatePresence>
              </Link>
            );
          })}
          {isAdmin && (
            <Link
              href="/admin"
              onClick={onMobileClose}
              className={`
                group relative flex items-center gap-3 rounded-xl
                h-10 transition-all duration-150
                ${collapsed ? 'justify-center px-2' : 'px-3'}
                ${
                  pathname.startsWith('/admin')
                    ? 'bg-emerald-500/10 text-white border border-emerald-500/25 shadow-[0_0_15px_rgba(16,185,129,0.06)]'
                    : 'text-[var(--text-muted)] hover:bg-white/[0.035] hover:text-white border border-transparent'
                }
              `}
              title={collapsed ? 'Admin' : undefined}
            >
              {pathname.startsWith('/admin') && (
                <motion.div
                  layoutId="sidebar-active"
                  className="absolute left-1 top-2 bottom-2 w-1 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]"
                  transition={{ type: 'spring', stiffness: 350, damping: 30 }}
                />
              )}
              <ShieldAlert
                className={`h-4.5 w-4.5 shrink-0 transition-colors ${
                  pathname.startsWith('/admin') ? 'text-emerald-400' : 'text-[var(--text-dim)] group-hover:text-white'
                }`}
              />
              <AnimatePresence>
                {!collapsed && (
                  <motion.span
                    initial={{ opacity: 0, width: 0 }}
                    animate={{ opacity: 1, width: 'auto' }}
                    exit={{ opacity: 0, width: 0 }}
                    className={`text-[13px] font-medium whitespace-nowrap overflow-hidden ${
                      pathname.startsWith('/admin') ? 'text-white font-semibold' : 'text-[var(--text-muted)]'
                    }`}
                  >
                    Admin
                  </motion.span>
                )}
              </AnimatePresence>
            </Link>
          )}
        </nav>

        {/* Bottom User Card (Reference Layout with subtle amber finishing) */}
        <div className="p-3 border-t border-white/[0.06] relative z-10">
          <Link
            href="/login"
            className={`
              flex items-center gap-3 p-2 rounded-xl transition-all
              bg-white/[0.02] border border-amber-500/15 hover:border-amber-500/35 hover:bg-amber-500/[0.04]
              ${collapsed ? 'justify-center' : ''}
            `}
          >
            <div className="relative shrink-0">
              {userAvatar ? (
                <img
                  src={userAvatar}
                  alt={userName}
                  className="w-8 h-8 rounded-full object-cover ring-1 ring-amber-500/30"
                />
              ) : (
                <div className="w-8 h-8 rounded-full bg-emerald-950/60 border border-amber-500/30 flex items-center justify-center text-amber-300 font-semibold text-xs">
                  {userName.charAt(0).toUpperCase()}
                </div>
              )}
              <span className="absolute bottom-0 right-0 w-2 h-2 rounded-full bg-emerald-400 ring-2 ring-[#060908]" />
            </div>

            <AnimatePresence>
              {!collapsed && (
                <motion.div
                  initial={{ opacity: 0, width: 0 }}
                  animate={{ opacity: 1, width: 'auto' }}
                  exit={{ opacity: 0, width: 0 }}
                  className="flex flex-col min-w-0 flex-1 overflow-hidden"
                >
                  <span className="text-[10px] text-[var(--text-dim)] leading-tight truncate">
                    Good Morning,
                  </span>
                  <span className="text-xs font-semibold text-white leading-tight truncate">
                    {userName}
                  </span>
                  <span className="text-[9px] font-mono text-amber-400/80 leading-tight">
                    Investor
                  </span>
                </motion.div>
              )}
            </AnimatePresence>
          </Link>
        </div>

        {/* Desktop Collapse Toggle */}
        <div className="px-3 pb-3 hidden lg:block relative z-10">
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="
              flex items-center justify-center w-full h-8 rounded-lg
              text-[var(--text-dim)] hover:text-white
              hover:bg-white/[0.04] border border-transparent hover:border-white/[0.06]
              transition-all duration-150
              cursor-pointer text-xs font-mono
            "
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {collapsed ? (
              <ChevronRight className="h-4 w-4" />
            ) : (
              <div className="flex items-center gap-1.5">
                <ChevronLeft className="h-3.5 w-3.5" />
                <span className="text-[10px]">Collapse</span>
              </div>
            )}
          </button>
        </div>
      </div>
    );
  }

  return (
    <>
      {/* ── Desktop sidebar (lg+): fixed, collapsible ── */}
      <motion.aside
        className="
          fixed left-0 top-0 bottom-0 z-40
          hidden lg:flex flex-col
          bg-[#070b09]/85 backdrop-blur-2xl border-r border-white/[0.065]
          overflow-hidden
        "
        animate={{ width: sidebarWidth }}
        transition={{ duration: 0.2, ease: 'easeInOut' }}
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
              className="fixed inset-0 z-40 bg-black/70 backdrop-blur-sm lg:hidden"
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
                fixed left-0 top-0 bottom-0 z-50 w-[260px]
                flex flex-col lg:hidden
                bg-[#070b09]/95 backdrop-blur-2xl border-r border-white/[0.08]
                overflow-hidden
              "
              initial={{ x: -260 }}
              animate={{ x: 0 }}
              exit={{ x: -260 }}
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
