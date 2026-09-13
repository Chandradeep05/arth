// ARTH Phase 4 -- Browser-side Supabase client
// Uses createBrowserClient from @supabase/ssr so sessions are stored in COOKIES,
// not localStorage. This is critical: the middleware (server-side) uses
// createServerClient which can only read cookies. If we used createClient from
// @supabase/supabase-js (localStorage), the middleware would never see the session
// and would redirect authenticated users back to /login.

import { createBrowserClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";

// Fallback to placeholder during Next.js static generation (build time).
const supabaseUrl =
  process.env.NEXT_PUBLIC_SUPABASE_URL ?? "https://placeholder.supabase.co";
const supabaseAnonKey =
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "placeholder-anon-key";

export const supabase: SupabaseClient = createBrowserClient(
  supabaseUrl,
  supabaseAnonKey
);

// Helper: check if Supabase is properly configured (env vars are set)
export const isSupabaseConfigured =
  !!process.env.NEXT_PUBLIC_SUPABASE_URL &&
  !!process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
