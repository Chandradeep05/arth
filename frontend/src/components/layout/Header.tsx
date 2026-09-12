'use client';

import { useState, useEffect, useMemo } from 'react';
import { Search, Circle, Menu } from 'lucide-react';
import { MARKET_HOURS, DATA_DELAY_LABEL } from '@/lib/constants';
import UserMenu from '@/components/layout/UserMenu';
import NotificationBell from '@/components/layout/NotificationBell';

function isMarketOpen(): boolean {
  const now = new Date();

  // Check NSE hours (primary market)
  const nseHours = MARKET_HOURS.NSE;
  const istTime = new Date(
    now.toLocaleString('en-US', { timeZone: nseHours.timezone })
  );
  const currentMinutes = istTime.getHours() * 60 + istTime.getMinutes();
  const openMinutes = nseHours.open.hour * 60 + nseHours.open.minute;
  const closeMinutes = nseHours.close.hour * 60 + nseHours.close.minute;
  const dayOfWeek = istTime.getDay();

  // Weekday check (Mon-Fri)
  if (dayOfWeek === 0 || dayOfWeek === 6) return false;

  return currentMinutes >= openMinutes && currentMinutes < closeMinutes;
}

interface HeaderProps {
  onMenuOpen?: () => void;
}

export default function Header({ onMenuOpen }: HeaderProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [marketOpen, setMarketOpen] = useState(false);

  useEffect(() => {
    setMarketOpen(isMarketOpen());
    const interval = setInterval(() => {
      setMarketOpen(isMarketOpen());
    }, 60_000);
    return () => clearInterval(interval);
  }, []);

  const marketStatus = useMemo(
    () => ({
      label: marketOpen ? 'Market Open' : 'Market Closed',
      dotColor: marketOpen ? 'text-[var(--green)]' : 'text-[var(--red)]',
    }),
    [marketOpen]
  );

  return (
    <header
      className="
        sticky top-0 z-30
        flex items-center justify-between gap-2 sm:gap-4
        h-14 sm:h-16 px-3 sm:px-6
        bg-[#070b09]/80 backdrop-blur-2xl
        border-b border-white/[0.06]
      "
    >
      {/* Left: Hamburger (mobile) + Page title */}
      <div className="flex items-center gap-2 sm:gap-3 min-w-0">
        {/* Hamburger — visible only on mobile (<lg) */}
        <button
          onClick={onMenuOpen}
          className="
            lg:hidden
            flex items-center justify-center
            h-8.5 w-8.5 rounded-lg shrink-0
            text-[var(--text-muted)] hover:text-white
            hover:bg-white/[0.05] border border-white/[0.06]
            transition-colors duration-150
            cursor-pointer
          "
          aria-label="Open navigation menu"
        >
          <Menu className="h-4.5 w-4.5" />
        </button>

        <span className="text-xs font-mono uppercase tracking-widest text-[var(--text-dim)] hidden sm:inline">
          ARTH TERMINAL
        </span>
      </div>

      {/* Center: Reference-matching Search Pill */}
      <div className="flex-1 max-w-xl mx-1 sm:mx-2 min-w-0">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (searchQuery.trim()) {
              window.location.href = `/markets/${encodeURIComponent(searchQuery.trim().toUpperCase())}`;
            }
          }}
          className="relative group"
        >
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 sm:h-4 sm:w-4 text-[var(--text-dim)] group-focus-within:text-emerald-400 transition-colors" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search stocks, indices..."
            className="
              w-full h-8.5 sm:h-9.5 pl-8.5 sm:pl-10 pr-3 sm:pr-4
              rounded-full
              bg-white/[0.03] border border-white/[0.07]
              text-xs text-white placeholder:text-[var(--text-dim)]
              font-sans
              outline-none
              focus:border-emerald-500/40 focus:bg-white/[0.04] focus:ring-1 focus:ring-emerald-500/20
              transition-all duration-200
            "
          />
        </form>
      </div>

      {/* Right: Market status + Notification + User */}
      <div className="flex items-center gap-2 sm:gap-3 shrink-0">
        <div className="flex items-center gap-1.5 sm:gap-2 px-2 sm:px-2.5 py-1 rounded-full bg-white/[0.02] border border-white/[0.05]">
          <span
            className={`h-2 w-2 rounded-full shrink-0 ${
              marketOpen
                ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]'
                : 'bg-red-400 shadow-[0_0_8px_rgba(248,113,113,0.8)]'
            }`}
          />
          <span className="text-[11px] font-medium text-[var(--text)] whitespace-nowrap hidden md:inline">
            {marketStatus.label}
          </span>
          <span className="text-[10px] font-mono text-[var(--text-dim)] hidden lg:inline whitespace-nowrap">
            • {DATA_DELAY_LABEL}
          </span>
        </div>

        <div className="w-px h-4 bg-white/[0.08] hidden sm:block" />

        <NotificationBell />
        <UserMenu />
      </div>
    </header>
  );
}
