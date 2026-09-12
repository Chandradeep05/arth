'use client';

import React, { createContext, useContext, useEffect, useState, useCallback, useMemo } from 'react';
import type { User, Session } from '@supabase/supabase-js';
import { supabase, isSupabaseConfigured } from '@/lib/supabase/client';

interface AuthContextType {
  user: User | null;
  session: Session | null;
  loading: boolean;
  isAdmin: boolean;
  accessStatus: string | null;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  session: null,
  loading: true,
  isAdmin: false,
  accessStatus: null,
  signOut: async () => {},
});

export function useAuth() {
  return useContext(AuthContext);
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [isAdmin, setIsAdmin] = useState(false);
  const [accessStatus, setAccessStatus] = useState<string | null>(null);

  // Fetch profile info (role, access_status) from backend after auth
  const fetchProfile = useCallback(async (accessToken: string) => {
    try {
      const API_URL = process.env.NEXT_PUBLIC_API_URL || 'https://arth-rdd5.onrender.com';
      const resp = await fetch(`${API_URL}/api/v1/auth/me`, {
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      if (resp.ok) {
        const data = await resp.json();
        setIsAdmin(data.role === 'admin');
        setAccessStatus(data.access_status);
      }
    } catch {
      // Profile fetch failed — non-fatal, user can still use public features
    }
  }, []);

  useEffect(() => {
    if (!isSupabaseConfigured) {
      setLoading(false);
      return;
    }

    // Get initial session
    supabase.auth.getSession().then(({ data: { session: s } }) => {
      setSession(s);
      setUser(s?.user ?? null);
      if (s?.access_token) {
        fetchProfile(s.access_token);
      }
      setLoading(false);
    });

    // Listen for auth state changes (login, logout, token refresh)
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      (_event, s) => {
        setSession(s);
        setUser(s?.user ?? null);
        if (s?.access_token) {
          fetchProfile(s.access_token);
        } else {
          setIsAdmin(false);
          setAccessStatus(null);
        }
        setLoading(false);
      }
    );

    return () => subscription.unsubscribe();
  }, [fetchProfile]);

  const signOut = useCallback(async () => {
    await supabase.auth.signOut();
    setUser(null);
    setSession(null);
    setIsAdmin(false);
    setAccessStatus(null);
  }, []);

  const value = useMemo(
    () => ({ user, session, loading, isAdmin, accessStatus, signOut }),
    [user, session, loading, isAdmin, accessStatus, signOut]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
