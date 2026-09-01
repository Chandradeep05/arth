"use client";

// Supabase OAuth Callback Handler
// After Google sign-in, Supabase redirects here with auth tokens in URL fragment.
// The Supabase client auto-detects the session from the URL via detectSessionInUrl:true.

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabase/client";

export default function AuthCallbackPage() {
  const router = useRouter();

  useEffect(() => {
    // Listen for auth state change (triggered when Supabase processes the callback URL)
    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === "SIGNED_IN" && session) {
        // Redirect to dashboard on successful sign-in
        router.replace("/");
      }
    });

    return () => subscription.unsubscribe();
  }, [router]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
      <div className="flex flex-col items-center gap-4">
        <span className="animate-spin h-10 w-10 border-4 border-[var(--border)] border-t-[var(--accent)] rounded-full" />
        <p className="text-sm font-mono text-[var(--text-muted)]">Signing you in...</p>
      </div>
    </div>
  );
}
