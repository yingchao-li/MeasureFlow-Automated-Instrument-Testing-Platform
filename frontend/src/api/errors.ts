import type { ApiErrorCode, BackendErrorCode } from './types';

const BACKEND_CODES: ReadonlySet<string> = new Set<BackendErrorCode>([
  'INVALID_ARGUMENT',
  'FORBIDDEN_HOST',
  'NOT_FOUND',
  'NOT_CONNECTED',
  'INSTRUMENT_BUSY',
  'CONFLICT',
  'COMMUNICATION_ERROR',
  'TIMEOUT',
  'INTERNAL',
]);

export function isBackendCode(code: unknown): code is BackendErrorCode {
  return typeof code === 'string' && BACKEND_CODES.has(code);
}

/**
 * Error raised by the API client. Mirrors the unified backend error body
 * (`{error:{code,message,details}}`) and adds client-side codes for transport failures.
 */
export class ApiError extends Error {
  readonly code: ApiErrorCode;
  readonly status: number;
  readonly details: Record<string, unknown> | null;

  constructor(code: ApiErrorCode, message: string, status = 0, details: Record<string, unknown> | null = null) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.details = details;
  }

  /** The backend could not be reached at all (connection refused, proxy 5xx without error body, ...). */
  get isOffline(): boolean {
    return this.code === 'NETWORK_ERROR';
  }

  /** Offline, or the backend did not answer within the client timeout. */
  get isUnreachable(): boolean {
    return this.code === 'NETWORK_ERROR' || this.code === 'CLIENT_TIMEOUT';
  }

  get isAbort(): boolean {
    return this.code === 'ABORTED';
  }

  /** Field name for INVALID_ARGUMENT errors (`details.field`). */
  get field(): string | null {
    const f = this.details?.['field'];
    return typeof f === 'string' ? f : null;
  }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}

/** Message suitable for showing to a user, for any thrown value. */
export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return typeof e === 'string' ? e : 'Unexpected error';
}

/** Parse a response body that should follow the unified error format. Returns null when it does not. */
export function parseErrorBody(body: unknown): { code: BackendErrorCode; message: string; details: Record<string, unknown> | null } | null {
  if (typeof body !== 'object' || body === null) return null;
  const err = (body as { error?: unknown }).error;
  if (typeof err !== 'object' || err === null) return null;
  const { code, message, details } = err as { code?: unknown; message?: unknown; details?: unknown };
  if (!isBackendCode(code) || typeof message !== 'string') return null;
  const det = typeof details === 'object' && details !== null && !Array.isArray(details) ? (details as Record<string, unknown>) : null;
  return { code, message, details: det };
}

/** Short, human title for an error code (used in ErrorState headings and toasts). */
export function errorTitle(e: unknown): string {
  if (!(e instanceof ApiError)) return 'Something went wrong';
  switch (e.code) {
    case 'NETWORK_ERROR':
      return 'Backend unreachable';
    case 'CLIENT_TIMEOUT':
      return 'Backend did not respond in time';
    case 'NOT_CONNECTED':
      return 'Instrument not connected';
    case 'INSTRUMENT_BUSY':
      return 'Instrument busy';
    case 'COMMUNICATION_ERROR':
      return 'Instrument communication error';
    case 'TIMEOUT':
      return 'Instrument timed out';
    case 'INVALID_ARGUMENT':
      return 'Invalid input';
    case 'CONFLICT':
      return 'Request conflicts with current state';
    case 'NOT_FOUND':
      return 'Not found';
    case 'FORBIDDEN_HOST':
      return 'Host not allowed';
    case 'BAD_RESPONSE':
      return 'Unexpected response';
    case 'ABORTED':
      return 'Request cancelled';
    default:
      return 'Backend error';
  }
}
