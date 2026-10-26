/**
 * NestFlow session tokens.
 *
 * The identity provider (Firebase, or dev) is used once, to sign in. Its token
 * is exchanged at `/auth/login` for NestFlow's own pair:
 *
 *   access token  — short-lived JWT, kept in memory only, sent as
 *                   `Authorization: Bearer` on every request.
 *   refresh token — long-lived, kept in localStorage so a reload or a new tab
 *                   stays signed in. Single use: every refresh returns a new one.
 *
 * Because a refresh token works exactly once, two tabs refreshing at the same
 * moment would make the server see a reuse and end the session. Refreshes are
 * therefore serialised across tabs with the Web Locks API, and the token is
 * re-read from storage inside the lock so each tab spends the latest one.
 */

export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

const REFRESH_KEY = "nf.session.refresh";
const LOCK_NAME = "nf.session.refresh";
/** Refresh this long before expiry, so a request never leaves with a dying token. */
const EXPIRY_MARGIN_MS = 30_000;

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  refresh_expires_in: number;
}

/** The server refused a login or refresh. `code` is the backend's error code. */
export class SessionError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "SessionError";
    this.status = status;
    this.code = code;
  }
}

export interface AccessClaims {
  sub: string;
  email: string;
  exp: number;
}

let access: { token: string; expiresAt: number } | null = null;
let inflight: Promise<string | null> | null = null;

/* -------------------------------------------------------------------------- */
/* Session-ended notifications                                                */
/* -------------------------------------------------------------------------- */

type EndListener = () => void;
const endListeners = new Set<EndListener>();

/** Called when the session ends without the user asking: refresh refused, or
 *  another tab signed out. */
export function onSessionEnd(listener: EndListener): () => void {
  endListeners.add(listener);
  return () => endListeners.delete(listener);
}

function endSession(): void {
  clearTokens();
  endListeners.forEach((l) => l());
}

if (typeof window !== "undefined") {
  window.addEventListener("storage", (event) => {
    if (event.key === REFRESH_KEY && event.newValue === null && access) {
      access = null;
      endListeners.forEach((l) => l());
    }
  });
}

/* -------------------------------------------------------------------------- */
/* Storage                                                                    */
/* -------------------------------------------------------------------------- */

function readRefresh(): string | null {
  try {
    return localStorage.getItem(REFRESH_KEY);
  } catch {
    return null;
  }
}

function store(pair: TokenResponse): void {
  access = { token: pair.access_token, expiresAt: Date.now() + pair.expires_in * 1000 };
  try {
    localStorage.setItem(REFRESH_KEY, pair.refresh_token);
  } catch {
    // Private mode with storage blocked: the session lasts as long as the tab.
  }
}

export function clearTokens(): void {
  access = null;
  try {
    localStorage.removeItem(REFRESH_KEY);
  } catch {
    // Nothing stored, nothing to clear.
  }
}

export function hasSession(): boolean {
  return access !== null || readRefresh() !== null;
}

/** Read the claims of an access token. Display only — the server verifies it. */
export function decodeAccessToken(token: string): AccessClaims | null {
  try {
    const payload = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(payload)) as AccessClaims;
  } catch {
    return null;
  }
}

/* -------------------------------------------------------------------------- */
/* Server calls                                                               */
/* -------------------------------------------------------------------------- */

async function post<T>(path: string, body: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new SessionError(0, "NETWORK_ERROR", "Could not reach the server. Check your connection.");
  }

  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload?.success) {
    throw new SessionError(
      response.status,
      payload?.code ?? "INTERNAL_ERROR",
      payload?.message ?? "Sign-in failed. Please try again.",
    );
  }
  return payload.data as T;
}

function withLock<T>(fn: () => Promise<T>): Promise<T> {
  if (typeof navigator !== "undefined" && navigator.locks?.request) {
    // request() resolves to the callback's own result; its typings nest the promise.
    return navigator.locks.request(LOCK_NAME, fn) as unknown as Promise<T>;
  }
  return fn();
}

export type LoginCredentials = { email: string; password: string } | { id_token: string };

/** Start a NestFlow session from an email and password, or an identity-provider token. */
export async function login(credentials: LoginCredentials): Promise<AccessClaims> {
  const pair = await post<TokenResponse>("/auth/login", credentials);
  store(pair);
  return decodeAccessToken(pair.access_token)!;
}

/** Adopt a pair the server issued outside login/refresh — e.g. after a password
 *  change, which signs out every other session and hands this one a new pair. */
export function acceptTokens(pair: TokenResponse): void {
  store(pair);
}

/**
 * Spend the refresh token for a new pair. Resolves to the new access token, or
 * null when there is no session or the server refused it (the session has then
 * ended and listeners have been told). Network failures reject, leaving the
 * session intact for the next attempt.
 */
export function refreshAccessToken(): Promise<string | null> {
  inflight ??= withLock(async () => {
    const refresh = readRefresh();
    if (!refresh) {
      access = null;
      return null;
    }
    try {
      const pair = await post<TokenResponse>("/auth/refresh", { refresh_token: refresh });
      store(pair);
      return pair.access_token;
    } catch (error) {
      if (error instanceof SessionError && error.status >= 400 && error.status < 500) {
        endSession();
        return null;
      }
      throw error;
    }
  }).finally(() => {
    inflight = null;
  });
  return inflight;
}

/** A valid access token, refreshing first if the current one is about to expire. */
export async function getAccessToken(): Promise<string | null> {
  if (access && access.expiresAt - EXPIRY_MARGIN_MS > Date.now()) return access.token;
  return refreshAccessToken();
}

/** Revoke the session on the server and forget it here. Never throws. */
export async function logout(): Promise<void> {
  const refresh = readRefresh();
  clearTokens();
  if (refresh) {
    await post("/auth/logout", { refresh_token: refresh }).catch(() => undefined);
  }
}
