/**
 * API Client
 * Typed HTTP client for ARTH backend communication
 */

import { API_BASE_URL } from './constants';

interface ApiResponse<T> {
  data: T;
  status: number;
  timestamp: string;
}

interface ApiError {
  message: string;
  status: number;
  code: string;
  traceId?: string;
}

class ApiClientError extends Error {
  status: number;
  code: string;
  traceId?: string;

  constructor(error: ApiError) {
    super(error.message);
    this.name = 'ApiClientError';
    this.status = error.status;
    this.code = error.code;
    this.traceId = error.traceId;
  }
}

function generateTraceId(): string {
  return `ARTH-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
}

function logRequest(method: string, url: string, traceId: string): void {
  if (process.env.NODE_ENV === 'development') {
    console.log(`[API] ${method} ${url} [trace: ${traceId}]`);
  }
}

function logResponse(method: string, url: string, status: number, durationMs: number): void {
  if (process.env.NODE_ENV === 'development') {
    console.log(`[API] ${method} ${url} → ${status} (${durationMs}ms)`);
  }
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let errorBody: ApiError;
    try {
      errorBody = await response.json() as ApiError;
    } catch {
      errorBody = {
        message: `HTTP ${response.status}: ${response.statusText}`,
        status: response.status,
        code: 'UNKNOWN_ERROR',
      };
    }
    throw new ApiClientError(errorBody);
  }

  return response.json() as Promise<T>;
}

export const apiClient = {
  /**
   * GET request with typed response
   */
  async get<T>(endpoint: string, params?: Record<string, string>): Promise<T> {
    const traceId = generateTraceId();
    const url = new URL(`${API_BASE_URL}${endpoint}`);

    if (params) {
      Object.entries(params).forEach(([key, value]) => {
        url.searchParams.set(key, value);
      });
    }

    const urlString = url.toString();
    logRequest('GET', urlString, traceId);
    const start = performance.now();

    const response = await fetch(urlString, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
        'X-Trace-Id': traceId,
      },
    });

    logResponse('GET', urlString, response.status, performance.now() - start);
    return handleResponse<T>(response);
  },

  /**
   * POST request with typed request/response
   */
  async post<T, B = unknown>(endpoint: string, body: B): Promise<T> {
    const traceId = generateTraceId();
    const urlString = `${API_BASE_URL}${endpoint}`;
    logRequest('POST', urlString, traceId);
    const start = performance.now();

    const response = await fetch(urlString, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Trace-Id': traceId,
      },
      body: JSON.stringify(body),
    });

    logResponse('POST', urlString, response.status, performance.now() - start);
    return handleResponse<T>(response);
  },

  /**
   * Server-Sent Events (SSE) stream connection
   * Returns an async generator that yields parsed events
   */
  async *stream<T>(endpoint: string, params?: Record<string, string>): AsyncGenerator<T> {
    const traceId = generateTraceId();
    const url = new URL(`${API_BASE_URL}${endpoint}`);

    if (params) {
      Object.entries(params).forEach(([key, value]) => {
        url.searchParams.set(key, value);
      });
    }

    const urlString = url.toString();
    logRequest('SSE', urlString, traceId);

    const response = await fetch(urlString, {
      headers: {
        'Accept': 'text/event-stream',
        'X-Trace-Id': traceId,
      },
    });

    if (!response.ok || !response.body) {
      throw new ApiClientError({
        message: `SSE connection failed: ${response.status}`,
        status: response.status,
        code: 'SSE_CONNECT_FAILED',
        traceId,
      });
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6).trim();
            if (data && data !== '[DONE]') {
              try {
                yield JSON.parse(data) as T;
              } catch {
                if (process.env.NODE_ENV === 'development') {
                  console.warn('[API] Failed to parse SSE data:', data);
                }
              }
            }
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  },
};

export { ApiClientError };
export type { ApiResponse, ApiError };
