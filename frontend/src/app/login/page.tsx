"use client";

import { useState } from "react";
import { supabase } from "@/lib/supabase/client";
import { TrendingUp, LogIn } from "lucide-react";

export default function LoginPage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleGoogleSignIn() {
    setLoading(true);
    setError(null);
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${window.location.origin}/auth/callback`,
        queryParams: {
          access_type: "offline",
          prompt: "consent",
        },
      },
    });
    if (error) {
      setError(error.message);
      setLoading(false);
    }
    // On success, browser redirects to Google -- no manual redirect needed
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
      <div className="w-full max-w-md px-8 py-10 rounded-2xl bg-[var(--surface)] border border-[var(--border)] shadow-2xl">
        {/* Logo */}
        <div className="flex flex-col items-center gap-3 mb-10">
          <div className="flex items-center gap-2">
            <TrendingUp className="h-8 w-8 text-[var(--accent)]" />
            <span className="font-heading text-3xl font-extrabold text-[var(--accent)] drop-shadow-[0_0_12px_rgba(0,212,255,0.4)]">
              ARTH
            </span>
          </div>
          <p className="text-sm font-mono text-[var(--text-muted)] text-center">
            AI Research &amp; Trading Hub
          </p>
        </div>

        {/* Tagline */}
        <p className="text-center text-[var(--text)] text-sm mb-8">
          Sign in to access your personal watchlists, AI assistant history, price alerts, and saved research.
        </p>

        {/* Google Sign In */}
        <button
          onClick={handleGoogleSignIn}
          disabled={loading}
          className="
            w-full flex items-center justify-center gap-3
            h-12 px-6 rounded-lg
            bg-[var(--accent)] hover:bg-[var(--accent)]/90
            text-black font-semibold text-sm
            transition-all duration-200
            disabled:opacity-60 disabled:cursor-not-allowed
            shadow-[0_0_20px_rgba(0,212,255,0.3)]
            hover:shadow-[0_0_30px_rgba(0,212,255,0.5)]
          "
          aria-label="Sign in with Google"
        >
          {loading ? (
            <span className="animate-spin h-5 w-5 border-2 border-black/30 border-t-black rounded-full" />
          ) : (
            <>
              {/* Google SVG icon */}
              <svg className="h-5 w-5" viewBox="0 0 24 24" aria-hidden="true">
                <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
              </svg>
              <LogIn className="h-4 w-4" />
              Continue with Google
            </>
          )}
        </button>

        {error && (
          <p className="mt-4 text-center text-sm text-[var(--red)]">{error}</p>
        )}

        {/* Access note */}
        <p className="mt-8 text-center text-xs text-[var(--text-dim)]">
          New account? You will need an invite code to activate access.
          <br />
          Public market data is available without signing in.
        </p>
      </div>
    </div>
  );
}
