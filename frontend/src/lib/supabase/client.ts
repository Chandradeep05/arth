// ARTH Phase 4 -- Browser-side Supabase client
// Used in Client Components for auth state (onAuthStateChange, signIn, signOut)
// NEXT_PUBLIC_* vars are safe to expose in browser -- they are the anon key (not service key)

import { createClient } from "@supabase/supabase-js";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

if (!supabaseUrl || !supabaseAnonKey) {
  throw new Error("Missing NEXT_PUBLIC_SUPABASE_URL or NEXT_PUBLIC_SUPABASE_ANON_KEY");
}

// Singleton client -- shared across the browser session
export const supabase = createClient(supabaseUrl, supabaseAnonKey, {
  auth: {
    persistSession: true,          // keep session across page reloads
    storageKey: "arth-auth",       // localStorage key
    detectSessionInUrl: true,      // handle OAuth callback fragment
    flowType: "pkce",              // PKCE is more secure than implicit for SPAs
  },
});
