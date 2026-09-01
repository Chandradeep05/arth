'use client';

import { useState, useEffect, useMemo } from 'react';
import { Search, Circle, Menu } from 'lucide-react';
import { MARKET_HOURS, DATA_DELAY_LABEL } from '@/lib/constants';

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
        flex items-center justify-between gap-4
        h-14 px-6
        bg-[var(--surface)]/80 backdrop-blur-xl
        border-b border-[var(--border)]
      "
    >
      {/* Left: Hamburger (mobile) + Page title */}
      <div className="flex items-center gap-2 min-w-0">
        {/* Hamburger — visible only on mobile (<lg) */}
        <button
          onClick={onMenuOpen}
          className="
            lg:hidden
            flex items-center justify-center
            h-8 w-8 rounded-md shrink-0
            text-[var(--text-muted)] hover:text-[var(--text)]
            hover:bg-[var(--surface-2)]
            transition-colors duration-150
            cursor-pointer
          "
          aria-label="Open navigation menu"
        >
          <Menu className="h-5 w-5" />
        </button>

        <h1 className="font-heading text-sm font-bold text-[var(--text)] truncate">
          Intelligence Dashboard
        </h1>
      </div>

      {/* Center: Search */}
      <div className="flex-1 max-w-lg">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--text-dim)]" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search stocks... (e.g., RELIANCE.NS, AAPL)"
            className="
              w-full h-9 pl-10 pr-4
              rounded-lg
              bg-[var(--bg)] border border-[var(--border)]
              text-sm text-[var(--text)] placeholder:text-[var(--text-dim)]
              font-mono
              outline-none
              focus:border-[var(--accent)] focus:ring-1 focus:ring-[var(--accent)]/30
              transition-all duration-200
            "
          />
        </div>
      </div>

      {/* Right: Market status */}
      <div className="flex items-center gap-3 shrink-0">
        <div className="flex items-center gap-2">
          <Circle
            className={`h-2.5 w-2.5 fill-current ${marketStatus.dotColor}`}
          />
          <span className="text-xs font-medium text-[var(--text)]">
            {marketStatus.label}
          </span>
        </div>
        <span className="text-[10px] font-mono text-[var(--text-dim)]">
          {DATA_DELAY_LABEL}
        </span>
      </div>
    </header>
  );
}
