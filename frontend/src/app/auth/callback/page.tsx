"use client";

// Supabase OAuth Callback Handler
// After Google sign-in, Supabase redirects here with either:
//   - PKCE flow: ?code=xxx in the URL (exchanged by the client automatically)
//   - Implicit flow: #access_token=xxx in the hash fragment
// The @supabase/ssr browser client handles both cases automatically
// and stores the session in cookies (shared with middleware).

import { Suspense, useEffect, useState, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { supabase } from "@/lib/supabase/client";

function CallbackHandler() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const exchangedRef = useRef(false);

  useEffect(() => {
    const code = searchParams.get("code");

    async function handleCallback() {
      if (code) {
        // Guard against double-exchange in React 18 StrictMode
        if (exchangedRef.current) return;
        exchangedRef.current = true;

        const { error } = await supabase.auth.exchangeCodeForSession(code);
        if (error) {
          // Check if session was already established (auto-exchange succeeded)
          const { data: { session } } = await supabase.auth.getSession();
          if (session) {
            router.replace("/");
            return;
          }
          setError(error.message);
          return;
        }
      }

      // Check if we have a session (works for both PKCE and implicit flow)
      const { data: { session } } = await supabase.auth.getSession();
      if (session) {
        router.replace("/");
      } else if (!code) {
        // No code and no session — listen for auth state change (implicit flow)
        const { data: { subscription } } = supabase.auth.onAuthStateChange((event, session) => {
          if (event === "SIGNED_IN" && session) {
            router.replace("/");
          }
        });
        // Timeout: if no session after 5 seconds, redirect to login
        const timeout = setTimeout(() => {
          subscription.unsubscribe();
          setError("Authentication timed out. Please try again.");
        }, 5000);
        return () => {
          clearTimeout(timeout);
          subscription.unsubscribe();
        };
      }
    }

    handleCallback();
  }, [router, searchParams]);

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
        <div className="flex flex-col items-center gap-4 max-w-md text-center">
          <p className="text-sm text-red-400">{error}</p>
          <button
            onClick={() => router.replace("/login")}
            className="px-4 py-2 text-sm bg-[var(--accent)] text-black rounded-lg hover:opacity-90"
          >
            Back to Login
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
      <div className="flex flex-col items-center gap-4">
        <span className="animate-spin h-10 w-10 border-4 border-[var(--border)] border-t-[var(--accent)] rounded-full" />
        <p className="text-sm font-mono text-[var(--text-muted)]">Signing you in...</p>
      </div>
    </div>
  );
}

// Next.js 16 requires useSearchParams() to be inside a Suspense boundary
// otherwise the page cannot be statically pre-rendered during build.
export default function AuthCallbackPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
          <div className="flex flex-col items-center gap-4">
            <span className="animate-spin h-10 w-10 border-4 border-[var(--border)] border-t-[var(--accent)] rounded-full" />
            <p className="text-sm font-mono text-[var(--text-muted)]">Loading...</p>
          </div>
        </div>
      }
    >
      <CallbackHandler />
    </Suspense>
  );
}
