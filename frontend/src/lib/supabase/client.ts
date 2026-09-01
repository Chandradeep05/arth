// ARTH Phase 4 -- Browser-side Supabase client
// Uses lazy initialization so the build does not throw during static prerendering.
// Actual network calls only happen in the browser where NEXT_PUBLIC_* vars are set.

import { createClient, SupabaseClient } from "@supabase/supabase-js";

// Fallback to placeholder during Next.js static generation (build time).
// Supabase client with placeholder values initializes fine but any real auth
// calls will fail gracefully -- this only matters during server-side prerender
// of pages that don't use auth (login page is dynamically rendered).
const supabaseUrl =
  process.env.NEXT_PUBLIC_SUPABASE_URL ?? "https://placeholder.supabase.co";
const supabaseAnonKey =
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "placeholder-anon-key";

export const supabase: SupabaseClient = createClient(supabaseUrl, supabaseAnonKey, {
  auth: {
    persistSession: true,
    storageKey: "arth-auth",
    detectSessionInUrl: true,
    flowType: "pkce",
  },
});

// Helper: check if Supabase is properly configured (env vars are set)
export const isSupabaseConfigured =
  !!process.env.NEXT_PUBLIC_SUPABASE_URL &&
  !!process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
