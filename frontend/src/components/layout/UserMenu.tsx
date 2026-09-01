"use client";

// UserMenu -- avatar dropdown shown in Header when user is signed in
// Shows: user email, access status badge, links to profile/settings, sign out

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { LogOut, User, Bell } from "lucide-react";
import { supabase } from "@/lib/supabase/client";

interface UserInfo {
  email: string;
  displayName: string | null;
  avatarUrl: string | null;
}

export default function UserMenu() {
  const [open, setOpen] = useState(false);
  const [user, setUser] = useState<UserInfo | null>(null);
  const [unreadCount, setUnreadCount] = useState(0);
  const menuRef = useRef<HTMLDivElement>(null);
  const router = useRouter();

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (session?.user) {
        setUser({
          email: session.user.email || "",
          displayName: session.user.user_metadata?.full_name || null,
          avatarUrl: session.user.user_metadata?.avatar_url || null,
        });
      }
    });

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      if (session?.user) {
        setUser({
          email: session.user.email || "",
          displayName: session.user.user_metadata?.full_name || null,
          avatarUrl: session.user.user_metadata?.avatar_url || null,
        });
      } else {
        setUser(null);
      }
    });

    return () => subscription.unsubscribe();
  }, []);

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  async function handleSignOut() {
    await supabase.auth.signOut();
    router.replace("/login");
  }

  if (!user) {
    return (
      <button
        onClick={() => router.push("/login")}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-[var(--accent)]/10 text-[var(--accent)] hover:bg-[var(--accent)]/20 transition-colors"
      >
        <User className="h-3.5 w-3.5" />
        Sign In
      </button>
    );
  }

  const initials = (user.displayName || user.email)
    .split(" ").map((s: string) => s[0]).join("").toUpperCase().slice(0, 2);

  return (
    <div ref={menuRef} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 cursor-pointer"
        aria-label="User menu"
      >
        {user.avatarUrl ? (
          <img src={user.avatarUrl} alt="Avatar" className="h-8 w-8 rounded-full ring-2 ring-[var(--accent)]/30" />
        ) : (
          <div className="h-8 w-8 rounded-full bg-[var(--accent)]/20 flex items-center justify-center ring-2 ring-[var(--accent)]/30">
            <span className="text-xs font-bold text-[var(--accent)]">{initials}</span>
          </div>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-10 w-64 rounded-xl bg-[var(--surface)] border border-[var(--border)] shadow-2xl z-50 py-2">
          {/* User info */}
          <div className="px-4 py-3 border-b border-[var(--border)]">
            <p className="text-sm font-semibold text-[var(--text)] truncate">
              {user.displayName || user.email}
            </p>
            <p className="text-xs text-[var(--text-muted)] truncate mt-0.5">{user.email}</p>
          </div>

          {/* Actions */}
          <div className="py-1">
            <button
              onClick={() => { router.push("/alerts"); setOpen(false); }}
              className="w-full flex items-center gap-3 px-4 py-2 text-sm text-[var(--text)] hover:bg-[var(--surface-2)] transition-colors"
            >
              <Bell className="h-4 w-4 text-[var(--text-muted)]" />
              Alerts &amp; Notifications
            </button>
          </div>

          {/* Sign out */}
          <div className="border-t border-[var(--border)] py-1 mt-1">
            <button
              onClick={handleSignOut}
              className="w-full flex items-center gap-3 px-4 py-2 text-sm text-[var(--red)] hover:bg-[var(--surface-2)] transition-colors"
            >
              <LogOut className="h-4 w-4" />
              Sign Out
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
