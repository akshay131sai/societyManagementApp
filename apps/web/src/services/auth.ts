/**
 * Authentication.
 *
 * Firebase owns identity; NestFlow owns authorization and the session. This
 * module proves identity once, at sign-in, and hands the provider's token to
 * `/auth/login`, which returns NestFlow's access and refresh tokens (see
 * `services/tokens.ts`). Every access decision happens server-side.
 *
 * Three providers behind one interface, selected by `VITE_AUTH_PROVIDER` (it
 * must match the backend's `AUTH_PROVIDER`):
 *
 *   password — email and password, checked by the NestFlow API itself.
 *   firebase — the real Firebase Auth SDK, loaded lazily so its ~120 KB never
 *              lands in the entry chunk.
 *   dev      — sends `dev:<email>`, no password, for local work only. The
 *              backend refuses this in production.
 */

import { api } from "@/services/api";
import * as tokens from "@/services/tokens";

export type AuthProvider = "password" | "firebase" | "dev";

export const AUTH_PROVIDER: AuthProvider =
  (import.meta.env.VITE_AUTH_PROVIDER as AuthProvider) ?? "dev";

export const IS_DEV_AUTH = AUTH_PROVIDER === "dev";
export const IS_PASSWORD_AUTH = AUTH_PROVIDER === "password";
const IS_FIREBASE_AUTH = AUTH_PROVIDER === "firebase";

export interface AuthUser {
  uid: string;
  email: string;
  displayName: string | null;
  emailVerified: boolean;
}

type Listener = (user: AuthUser | null) => void;
const listeners = new Set<Listener>();
let currentUser: AuthUser | null = null;

function emit(user: AuthUser | null): void {
  currentUser = user;
  listeners.forEach((l) => l(user));
}

export function onAuthChange(listener: Listener): () => void {
  listeners.add(listener);
  listener(currentUser);
  return () => listeners.delete(listener);
}

/* -------------------------------------------------------------------------- */
/* Firebase (lazy)                                                            */
/* -------------------------------------------------------------------------- */

type FirebaseAuth = import("firebase/auth").Auth;
let firebaseAuthPromise: Promise<FirebaseAuth> | null = null;

async function getFirebaseAuth(): Promise<FirebaseAuth> {
  if (!firebaseAuthPromise) {
    firebaseAuthPromise = (async () => {
      const [{ initializeApp, getApps }, { getAuth }] = await Promise.all([
        import("firebase/app"),
        import("firebase/auth"),
      ]);

      const config = {
        apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
        authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
        projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
        storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
        messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
        appId: import.meta.env.VITE_FIREBASE_APP_ID,
      };

      const app = getApps().length ? getApps()[0] : initializeApp(config);
      // Firebase's own signed-in state is not followed: the NestFlow session
      // (services/tokens.ts) is what decides whether someone is signed in.
      return getAuth(app);
    })();
  }
  return firebaseAuthPromise;
}

/* -------------------------------------------------------------------------- */
/* Public API                                                                 */
/* -------------------------------------------------------------------------- */

function userFromClaims(claims: tokens.AccessClaims, displayName: string | null = null): AuthUser {
  return { uid: claims.sub, email: claims.email, displayName, emailVerified: true };
}

/** Start a NestFlow session and publish the user. */
async function startSession(
  credentials: tokens.LoginCredentials,
  displayName: string | null = null,
): Promise<AuthUser> {
  const user = userFromClaims(await tokens.login(credentials), displayName);
  emit(user);
  return user;
}

export async function signInWithEmail(email: string, password: string): Promise<AuthUser> {
  if (IS_PASSWORD_AUTH) {
    return startSession({ email: email.trim().toLowerCase(), password });
  }
  if (IS_DEV_AUTH) {
    return startSession({ id_token: `dev:${email.trim().toLowerCase()}` });
  }

  const { signInWithEmailAndPassword } = await import("firebase/auth");
  const auth = await getFirebaseAuth();
  const credential = await signInWithEmailAndPassword(auth, email, password);
  return startSession({ id_token: await credential.user.getIdToken() }, credential.user.displayName);
}

export async function signInWithGoogle(): Promise<AuthUser> {
  if (!IS_FIREBASE_AUTH) {
    throw new Error("Google sign-in requires a configured Firebase project.");
  }
  const { GoogleAuthProvider, signInWithPopup } = await import("firebase/auth");
  const auth = await getFirebaseAuth();
  const credential = await signInWithPopup(auth, new GoogleAuthProvider());
  return startSession({ id_token: await credential.user.getIdToken() }, credential.user.displayName);
}

/** Firebase only. With password sign-in an administrator resets passwords. */
export async function sendPasswordReset(email: string): Promise<void> {
  if (!IS_FIREBASE_AUTH) return;
  const { sendPasswordResetEmail } = await import("firebase/auth");
  const auth = await getFirebaseAuth();
  await sendPasswordResetEmail(auth, email);
}

export async function signOut(): Promise<void> {
  await tokens.logout();
  if (IS_FIREBASE_AUTH) {
    const { signOut: fbSignOut } = await import("firebase/auth");
    const auth = await getFirebaseAuth();
    await fbSignOut(auth);
  }
  emit(null);
}

/**
 * Change the signed-in user's own password. The server signs out every other
 * session and returns a fresh pair for this one.
 */
export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  const pair = await api.post<tokens.TokenResponse>("/auth/password", {
    current_password: currentPassword,
    new_password: newPassword,
  });
  tokens.acceptTokens(pair);
}

/** Current NestFlow access token, refreshed if about to expire; null when signed out. */
export const getAccessToken = tokens.getAccessToken;

/**
 * Restore a session on page load, before React renders.
 *
 * The stored refresh token is the session; the identity provider is not
 * consulted, so Firebase's SDK stays unloaded until someone signs in again.
 */
export async function restoreSession(): Promise<AuthUser | null> {
  let user: AuthUser | null = null;
  if (tokens.hasSession()) {
    const token = await tokens.getAccessToken().catch(() => null);
    const claims = token ? tokens.decodeAccessToken(token) : null;
    user = claims ? userFromClaims(claims) : null;
  }
  emit(user);
  return user;
}

// A refresh the server refused, or a sign-out in another tab, ends this tab's
// session too.
tokens.onSessionEnd(() => emit(null));

/** Firebase error codes rendered as something a person can act on. */
export function describeAuthError(error: unknown): string {
  if (error instanceof tokens.SessionError) return error.message;
  const code = (error as { code?: string })?.code ?? "";
  switch (code) {
    case "auth/invalid-credential":
    case "auth/wrong-password":
    case "auth/user-not-found":
      return "That email address or password is not correct.";
    case "auth/too-many-requests":
      return "Too many attempts. Please wait a few minutes and try again.";
    case "auth/user-disabled":
      return "This account has been disabled. Please contact your administrator.";
    case "auth/network-request-failed":
      return "Could not reach the sign-in service. Check your connection.";
    case "auth/popup-closed-by-user":
      return "The sign-in window was closed before completing.";
    case "auth/invalid-email":
      return "That does not look like a valid email address.";
    default:
      return (error as Error)?.message || "Sign-in failed. Please try again.";
  }
}
