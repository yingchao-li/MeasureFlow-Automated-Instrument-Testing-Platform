import { ApiError, parseErrorBody } from './errors';

export interface RequestOptions {
  method?: 'GET' | 'POST';
  body?: unknown;
  query?: object;
  signal?: AbortSignal;
  /** Client-side timeout in ms (default 8000). */
  timeoutMs?: number;
}

export const DEFAULT_TIMEOUT_MS = 8000;

/** Gateway-ish statuses that, without a unified error body, mean "the backend is not there" (e.g. Vite proxy ECONNREFUSED). */
const GATEWAY_STATUSES = new Set([0, 500, 502, 503, 504]);

export function buildUrl(path: string, query?: object): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query as Record<string, unknown>)) {
    if (value === undefined || value === null || value === '') continue;
    params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

/**
 * Minimal typed fetch wrapper.
 *  - always relative URLs (`/api/...`)
 *  - AbortController with a client timeout, merged with a caller-supplied signal
 *  - non-2xx responses are parsed as the unified error body into an ApiError
 *  - transport failures become `NETWORK_ERROR` (offline), timeouts `CLIENT_TIMEOUT`, caller aborts `ABORTED`
 */
export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, query, signal, timeoutMs = DEFAULT_TIMEOUT_MS } = opts;
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const onExternalAbort = () => controller.abort();
  if (signal) {
    if (signal.aborted) controller.abort();
    else signal.addEventListener('abort', onExternalAbort, { once: true });
  }

  const url = buildUrl(path, query);
  const init: RequestInit = {
    method,
    signal: controller.signal,
    headers: { Accept: 'application/json', ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
    cache: 'no-store',
  };
  if (body !== undefined) init.body = JSON.stringify(body);

  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (e) {
    clearTimeout(timer);
    signal?.removeEventListener('abort', onExternalAbort);
    if (controller.signal.aborted) {
      if (timedOut) throw new ApiError('CLIENT_TIMEOUT', `No response from the backend within ${Math.round(timeoutMs / 1000)} s`, 0);
      throw new ApiError('ABORTED', 'Request was cancelled', 0);
    }
    const reason = e instanceof Error ? e.message : 'network error';
    throw new ApiError('NETWORK_ERROR', `Cannot reach the backend (${reason})`, 0);
  }

  let text: string;
  try {
    text = await response.text();
  } catch {
    clearTimeout(timer);
    signal?.removeEventListener('abort', onExternalAbort);
    if (controller.signal.aborted && !timedOut) throw new ApiError('ABORTED', 'Request was cancelled', 0);
    throw new ApiError(timedOut ? 'CLIENT_TIMEOUT' : 'NETWORK_ERROR', 'Connection lost while reading the response', response.status);
  }
  clearTimeout(timer);
  signal?.removeEventListener('abort', onExternalAbort);

  let json: unknown = undefined;
  if (text.length > 0) {
    try {
      json = JSON.parse(text);
    } catch {
      json = undefined;
    }
  }

  if (!response.ok) {
    const parsed = parseErrorBody(json);
    if (parsed) throw new ApiError(parsed.code, parsed.message, response.status, parsed.details);
    if (GATEWAY_STATUSES.has(response.status)) {
      throw new ApiError('NETWORK_ERROR', `Backend unreachable (HTTP ${response.status})`, response.status);
    }
    throw new ApiError('BAD_RESPONSE', `Unexpected HTTP ${response.status} without an error body`, response.status);
  }

  if (json === undefined) {
    throw new ApiError('BAD_RESPONSE', 'The backend returned a response that is not valid JSON', response.status);
  }
  return json as T;
}
