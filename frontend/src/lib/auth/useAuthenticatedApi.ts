'use client';

import { useAuth } from './AuthProvider';
import { useCallback, useMemo } from 'react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'https://arth-rdd5.onrender.com';

interface RequestOptions {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
}

/**
 * Hook that returns an authenticated API client.
 * Automatically attaches Authorization: Bearer <token> to every request.
 * Returns null if user is not authenticated.
 */
export function useAuthenticatedApi() {
  const { session } = useAuth();

  const authFetch = useCallback(
    async <T = unknown>(path: string, options: RequestOptions = {}): Promise<T> => {
      const token = session?.access_token;
      if (!token) {
        throw new Error('Not authenticated');
      }

      const { method = 'GET', body, headers = {} } = options;

      const resp = await fetch(`${API_URL}${path}`, {
        method,
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
          ...headers,
        },
        ...(body ? { body: JSON.stringify(body) } : {}),
      });

      if (!resp.ok) {
        const errorBody = await resp.json().catch(() => ({ detail: resp.statusText }));
        const error = new Error(errorBody.detail || `HTTP ${resp.status}`);
        (error as Error & { status: number }).status = resp.status;
        throw error;
      }

      // Handle 204 No Content
      if (resp.status === 204) return undefined as unknown as T;

      return resp.json();
    },
    [session?.access_token]
  );

  const isAuthenticated = !!session?.access_token;

  return useMemo(
    () => ({
      /** Make an authenticated GET request */
      get: <T = unknown>(path: string) => authFetch<T>(path),
      /** Make an authenticated POST request */
      post: <T = unknown>(path: string, body?: unknown) =>
        authFetch<T>(path, { method: 'POST', body }),
      /** Make an authenticated PUT request */
      put: <T = unknown>(path: string, body?: unknown) =>
        authFetch<T>(path, { method: 'PUT', body }),
      /** Make an authenticated PATCH request */
      patch: <T = unknown>(path: string, body?: unknown) =>
        authFetch<T>(path, { method: 'PATCH', body }),
      /** Make an authenticated DELETE request */
      del: <T = unknown>(path: string) => authFetch<T>(path, { method: 'DELETE' }),
      /** Whether the user has a valid session token */
      isAuthenticated,
    }),
    [authFetch, isAuthenticated]
  );
}
