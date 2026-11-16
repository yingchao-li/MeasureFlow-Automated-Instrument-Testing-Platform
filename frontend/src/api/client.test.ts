import { api } from '@/api';
import { buildUrl, request } from './client';
import { ApiError, parseErrorBody } from './errors';

function mockFetch(impl: (url: string, init?: RequestInit) => Promise<Response> | Response) {
  const fn = vi.fn(async (url: string, init?: RequestInit) => impl(url, init));
  vi.stubGlobal('fetch', fn);
  return fn;
}
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('unified error parsing', () => {
  it('turns the backend error body into an ApiError with code, message, status and details', async () => {
    mockFetch(() => json({ error: { code: 'INVALID_ARGUMENT', message: 'frequency_hz must be within [10, 20000]', details: { field: 'frequency_hz' } } }, 400));
    const err = (await request('/api/instruments/configure', { method: 'POST', body: {} }).catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ code: 'INVALID_ARGUMENT', message: 'frequency_hz must be within [10, 20000]', status: 400, details: { field: 'frequency_hz' } });
    expect(err.field).toBe('frequency_hz');
    expect(err.isOffline).toBe(false);
  });

  it.each([
    ['NOT_CONNECTED', 409],
    ['INSTRUMENT_BUSY', 409],
    ['CONFLICT', 409],
    ['NOT_FOUND', 404],
    ['FORBIDDEN_HOST', 403],
    ['TIMEOUT', 504],
    ['COMMUNICATION_ERROR', 502],
    ['INTERNAL', 500],
  ])('keeps %s (HTTP %i) as an instrument/domain error and never as offline', async (code, status) => {
    mockFetch(() => json({ error: { code, message: `m-${code}`, details: { kind: 'timeout' } } }, status));
    const err = (await request('/api/x').catch((e) => e)) as ApiError;
    expect(err.code).toBe(code);
    expect(err.status).toBe(status);
    expect(err.isOffline).toBe(false);
    expect(err.isUnreachable).toBe(false);
    expect(err.details).toEqual({ kind: 'timeout' });
  });

  it('parseErrorBody rejects malformed bodies', () => {
    expect(parseErrorBody(null)).toBeNull();
    expect(parseErrorBody({})).toBeNull();
    expect(parseErrorBody({ error: { code: 'NOPE', message: 'x' } })).toBeNull();
    expect(parseErrorBody({ error: { code: 'NOT_FOUND' } })).toBeNull();
    expect(parseErrorBody({ error: { code: 'NOT_FOUND', message: 'x', details: [1] } })?.details).toBeNull();
  });

  it('reports HTTP errors without an error body as BAD_RESPONSE (not offline)', async () => {
    mockFetch(() => new Response('<html>nope</html>', { status: 418 }));
    const err = (await request('/api/x').catch((e) => e)) as ApiError;
    expect(err.code).toBe('BAD_RESPONSE');
    expect(err.isOffline).toBe(false);
  });

  it('rejects a 200 response that is not JSON', async () => {
    mockFetch(() => new Response('hello', { status: 200 }));
    expect(await request('/api/x').catch((e) => e)).toMatchObject({ code: 'BAD_RESPONSE' });
  });
});

describe('offline detection', () => {
  it('a rejected fetch (connection refused) is NETWORK_ERROR and offline', async () => {
    mockFetch(() => Promise.reject(new TypeError('Failed to fetch')));
    const err = (await api.health().catch((e) => e)) as ApiError;
    expect(err.code).toBe('NETWORK_ERROR');
    expect(err.isOffline).toBe(true);
    expect(err.isUnreachable).toBe(true);
    expect(err.status).toBe(0);
  });

  it.each([500, 502, 503, 504])('an HTTP %i without the unified body (dev proxy, ECONNREFUSED) is offline', async (status) => {
    mockFetch(() => new Response('', { status }));
    const err = (await request('/api/health').catch((e) => e)) as ApiError;
    expect(err.code).toBe('NETWORK_ERROR');
    expect(err.isOffline).toBe(true);
  });

  it('a client timeout is CLIENT_TIMEOUT: unreachable but not "offline"', async () => {
    vi.useFakeTimers();
    mockFetch((_url, init) => new Promise((_res, rej) => init?.signal?.addEventListener('abort', () => rej(new DOMException('aborted', 'AbortError')))));
    const p = request('/api/health', { timeoutMs: 1500 }).catch((e) => e);
    await vi.advanceTimersByTimeAsync(1600);
    const err = (await p) as ApiError;
    expect(err.code).toBe('CLIENT_TIMEOUT');
    expect(err.isUnreachable).toBe(true);
    expect(err.isOffline).toBe(false);
  });

  it('a caller abort is ABORTED and is neither offline nor unreachable', async () => {
    mockFetch((_url, init) => new Promise((_res, rej) => init?.signal?.addEventListener('abort', () => rej(new DOMException('aborted', 'AbortError')))));
    const ctl = new AbortController();
    const p = request('/api/health', { signal: ctl.signal }).catch((e) => e);
    ctl.abort();
    const err = (await p) as ApiError;
    expect(err.code).toBe('ABORTED');
    expect(err.isAbort).toBe(true);
    expect(err.isUnreachable).toBe(false);
  });
});

describe('request building', () => {
  it('uses relative /api URLs and skips empty query values', () => {
    expect(buildUrl('/api/tests/runs', { limit: 50, offset: 0, status: '', sequence_id: undefined })).toBe('/api/tests/runs?limit=50&offset=0');
    expect(buildUrl('/api/health')).toBe('/api/health');
  });

  it('POSTs JSON with the right headers and returns the parsed body', async () => {
    const fetchMock = mockFetch(() => json({ id: 'siggen', command: 'OUTP?', is_query: true, response: '1', duration_ms: 1, timestamp: 't', error: null }));
    const res = await api.command('siggen', 'OUTP?');
    expect(res.response).toBe('1');
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/instruments/command');
    expect(init.method).toBe('POST');
    expect(init.body).toBe(JSON.stringify({ id: 'siggen', command: 'OUTP?' }));
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json');
  });

  it('endpoint helpers hit the documented paths', async () => {
    const fetchMock = mockFetch(() => json({}));
    await api.live({ points: 1024, bins: 512 });
    await api.testStatus({ run_id: 'run-1', log_tail: 100 });
    await api.logs({ source: 'scpi', since_seq: 7, limit: 50 });
    await api.testResults({ kind: 'gain', limit: 1 });
    const urls = fetchMock.mock.calls.map((c) => c[0]);
    expect(urls).toEqual(['/api/measurements/live?points=1024&bins=512', '/api/tests/status?run_id=run-1&log_tail=100', '/api/logs?source=scpi&since_seq=7&limit=50', '/api/tests/results?kind=gain&limit=1']);
  });
});
