"use client";

// UserMenu -- avatar dropdown shown in Header when user is signed in
// Shows: user email, access status badge, links to profile/settings, sign out

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { LogOut, User, Bell, Shield } from "lucide-react";
import { supabase } from "@/lib/supabase/client";
import { useAuth } from "@/lib/auth/AuthProvider";

interface UserInfo {
  email: string;
  displayName: string | null;
  avatarUrl: string | null;
}

export default function UserMenu() {
  const [open, setOpen] = useState(false);
  const [user, setUser] = useState<UserInfo | null>(null);
  const [unreadCount, setUnreadCount] = useState(0);
  const { isAdmin } = useAuth();
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
        className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs font-medium bg-white/[0.04] border border-white/[0.08] text-white hover:bg-white/[0.08] hover:border-white/[0.15] transition-all cursor-pointer"
      >
        <User className="h-3.5 w-3.5 text-zinc-400" />
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
        className="flex items-center gap-2 cursor-pointer p-0.5 rounded-full hover:ring-2 hover:ring-white/20 transition-all"
        aria-label="User menu"
      >
        {user.avatarUrl ? (
          <img src={user.avatarUrl} alt="Avatar" className="h-8 w-8 rounded-full ring-1 ring-emerald-500/30 object-cover" />
        ) : (
          <div className="h-8 w-8 rounded-full bg-emerald-950/60 border border-emerald-500/30 flex items-center justify-center text-emerald-300 font-semibold text-xs">
            <span>{initials}</span>
          </div>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-11 w-64 rounded-2xl bg-[#090e0c]/95 backdrop-blur-2xl border border-white/[0.08] shadow-[0_20px_50px_rgba(0,0,0,0.8)] z-50 py-2 overflow-hidden">
          {/* User info */}
          <div className="px-4 py-3 border-b border-white/[0.06]">
            <p className="text-xs font-semibold text-white truncate">
              {user.displayName || user.email}
            </p>
            <p className="text-[11px] text-[var(--text-dim)] truncate mt-0.5 font-mono">{user.email}</p>
          </div>

          {/* Actions */}
          <div className="py-1">
            <button
              onClick={() => { router.push("/alerts"); setOpen(false); }}
              className="w-full flex items-center gap-3 px-4 py-2 text-xs text-[var(--text)] hover:bg-white/[0.04] transition-colors cursor-pointer"
            >
              <Bell className="h-3.5 w-3.5 text-[var(--text-dim)]" />
              Alerts &amp; Notifications
            </button>
            <button
              onClick={() => { router.push("/research/saved"); setOpen(false); }}
              className="w-full flex items-center gap-3 px-4 py-2 text-xs text-[var(--text)] hover:bg-white/[0.04] transition-colors cursor-pointer"
            >
              <User className="h-3.5 w-3.5 text-[var(--text-dim)]" />
              Saved Research
            </button>
            {isAdmin && (
              <button
                onClick={() => { router.push("/admin"); setOpen(false); }}
                className="w-full flex items-center gap-3 px-4 py-2 text-xs text-[var(--text)] hover:bg-white/[0.04] transition-colors cursor-pointer"
              >
                <Shield className="h-3.5 w-3.5 text-[var(--text-dim)]" />
                Admin Dashboard
              </button>
            )}
          </div>

          {/* Sign out */}
          <div className="border-t border-white/[0.06] py-1 mt-1">
            <button
              onClick={handleSignOut}
              className="w-full flex items-center gap-3 px-4 py-2 text-xs text-[var(--red)] hover:bg-white/[0.04] transition-colors cursor-pointer"
            >
              <LogOut className="h-3.5 w-3.5" />
              Sign Out
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
