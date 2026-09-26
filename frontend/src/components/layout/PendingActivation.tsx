'use client';

import React, { useState } from 'react';
import { useAuthenticatedApi } from '@/lib/auth/useAuthenticatedApi';
import { Key, Loader2, CheckCircle, AlertCircle } from 'lucide-react';

export default function PendingActivation() {
  const api = useAuthenticatedApi();
  const [code, setCode] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const handleRedeem = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!code.trim()) return;
    setLoading(true);
    setError(null);
    try {
      await api.post('/api/v1/auth/invite/redeem', { code: code.trim() });
      setSuccess(true);
      setTimeout(() => window.location.reload(), 1500);
    } catch (err: any) {
      setError(err.message || 'Invalid or expired invite code.');
    } finally {
      setLoading(false);
    }
  };

  if (success) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg)] p-4">
        <div className="card p-8 max-w-md w-full text-center">
          <CheckCircle className="w-12 h-12 text-emerald-400 mx-auto mb-4" />
          <h2 className="text-xl font-bold text-white mb-2">Account Activated!</h2>
          <p className="text-sm text-[var(--text-muted)]">Redirecting...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--bg)] p-4">
      <div className="card p-8 max-w-md w-full">
        <div className="flex items-center gap-3 mb-6">
          <Key className="w-8 h-8 text-[var(--accent)]" />
          <div>
            <h2 className="text-xl font-bold text-white">Account Pending</h2>
            <p className="text-xs text-[var(--text-muted)]">
              Enter an invite code to activate your account.
            </p>
          </div>
        </div>

        <form onSubmit={handleRedeem} className="space-y-4">
          <input
            type="text"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="Enter invite code"
            className="w-full px-4 py-3 rounded-lg bg-[var(--surface)] border border-[var(--border)] text-white placeholder:text-[var(--text-dim)] focus:border-[var(--accent)] focus:outline-none font-mono"
            disabled={loading}
          />
          {error && (
            <div className="flex items-center gap-2 text-red-400 text-xs">
              <AlertCircle className="w-3.5 h-3.5" />
              {error}
            </div>
          )}
          <button
            type="submit"
            disabled={loading || !code.trim()}
            className="w-full py-3 rounded-lg bg-[var(--accent)] text-black font-bold text-sm hover:opacity-90 transition-opacity disabled:opacity-50 cursor-pointer flex items-center justify-center gap-2"
          >
            {loading ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> Redeeming...</>
            ) : (
              'Activate Account'
            )}
          </button>
        </form>
      </div>
    </div>
  );
}
