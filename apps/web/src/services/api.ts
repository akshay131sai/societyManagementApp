/**
 * API client.
 *
 * One place that knows about the response envelope, the error taxonomy and
 * token attachment — so every screen has exactly one error path and no
 * component ever touches `fetch` directly.
 */

import { API_BASE_URL as BASE_URL, getAccessToken, refreshAccessToken } from "@/services/tokens";

export interface Envelope<T> {
  success: true;
  data: T;
  message: string;
}

export interface ErrorEnvelope {
  success: false;
  code: string;
  message: string;
  details?: { fields?: { field: string; message: string }[] } & Record<string, unknown>;
  request_id?: string;
}

export interface Page<T> {
  items: T[];
  page: number;
  limit: number;
  total: number;
  pages: number;
  has_next: boolean;
  has_prev: boolean;
}

/** A failure the backend described. Carries the machine code so callers can branch. */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details?: ErrorEnvelope["details"];
  readonly requestId?: string;

  constructor(status: number, body: ErrorEnvelope) {
    super(body.message || "Something went wrong.");
    this.name = "ApiError";
    this.code = body.code ?? "INTERNAL_ERROR";
    this.status = status;
    this.details = body.details;
    this.requestId = body.request_id;
  }

  /** Field errors keyed by field name, for React Hook Form. */
  get fieldErrors(): Record<string, string> {
    const fields = this.details?.fields ?? [];
    return Object.fromEntries(fields.map((f) => [f.field, f.message]));
  }

  get isAuthError(): boolean {
    return this.status === 401;
  }

  get isEntitlementError(): boolean {
    return this.status === 402;
  }
}

type Query = Record<string, string | number | boolean | undefined | null>;

interface RequestOptions {
  method?: string;
  body?: unknown;
  query?: Query;
  signal?: AbortSignal;
  /** Internal: prevents an infinite refresh loop on repeated 401s. */
  _retried?: boolean;
}

function buildUrl(path: string, query?: Query): string {
  const url = `${BASE_URL}${path}`;
  if (!query) return url;

  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") {
      params.append(key, String(value));
    }
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, query, signal } = options;

  const token = await getAccessToken().catch(() => null);
  const headers: Record<string, string> = { Accept: "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let response: Response;
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (cause) {
    if ((cause as Error).name === "AbortError") throw cause;
    throw new ApiError(0, {
      success: false,
      code: "NETWORK_ERROR",
      message: "Could not reach the server. Check your connection and try again.",
    });
  }

  if (response.status === 204) return undefined as T;

  let payload: Envelope<T> | ErrorEnvelope;
  try {
    payload = await response.json();
  } catch {
    throw new ApiError(response.status, {
      success: false,
      code: "INTERNAL_ERROR",
      message: "The server returned an unreadable response.",
    });
  }

  if (!response.ok || payload.success === false) {
    const error = new ApiError(response.status, payload as ErrorEnvelope);

    // A single retry after refreshing: the access token can expire between
    // the check in getAccessToken and the server reading it (clock skew, a
    // laptop waking from sleep), and the user should not see that. If the
    // refresh itself is refused, the session has ended and the error stands.
    const staleToken = error.code === "TOKEN_EXPIRED" || error.code === "TOKEN_INVALID";
    if (error.isAuthError && staleToken && token && !options._retried) {
      const fresh = await refreshAccessToken().catch(() => null);
      if (fresh) return request<T>(path, { ...options, _retried: true });
    }
    throw error;
  }

  return (payload as Envelope<T>).data;
}

export const api = {
  get: <T>(path: string, query?: Query, signal?: AbortSignal) =>
    request<T>(path, { method: "GET", query, signal }),
  post: <T>(path: string, body?: unknown, query?: Query) =>
    request<T>(path, { method: "POST", body, query }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: "PUT", body }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: "PATCH", body }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};
