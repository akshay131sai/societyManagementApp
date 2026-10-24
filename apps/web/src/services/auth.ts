/**
 * Authentication.
 *
 * Firebase owns identity; NestFlow owns authorization. This module deals only
 * with obtaining an ID token — every access decision happens server-side.
 *
 * Two providers behind one interface, selected by `VITE_AUTH_PROVIDER`:
 *
 *   firebase — the real Firebase Auth SDK, loaded lazily so its ~120 KB never
 *              lands in the entry chunk.
 *   dev      — mints a `dev:<email>` token for local work before a Firebase
 *              project exists. The backend refuses this in production.
 */

export type AuthProvider = "firebase" | "dev";

export const AUTH_PROVIDER: AuthProvider =
  (import.meta.env.VITE_AUTH_PROVIDER as AuthProvider) ?? "dev";

export const IS_DEV_AUTH = AUTH_PROVIDER === "dev";

export interface AuthUser {
  uid: string;
  email: string;
  displayName: string | null;
  emailVerified: boolean;
}

const DEV_SESSION_KEY = "nf.dev.session";

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
      const [{ initializeApp, getApps }, { getAuth, onAuthStateChanged }] = await Promise.all([
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
      const auth = getAuth(app);

      onAuthStateChanged(auth, (user) => {
        emit(
          user
            ? {
                uid: user.uid,
                email: user.email ?? "",
                displayName: user.displayName,
                emailVerified: user.emailVerified,
              }
            : null,
        );
      });

      return auth;
    })();
  }
  return firebaseAuthPromise;
}

/* -------------------------------------------------------------------------- */
/* Public API                                                                 */
/* -------------------------------------------------------------------------- */

export async function signInWithEmail(email: string, password: string): Promise<AuthUser> {
  if (IS_DEV_AUTH) {
    const user: AuthUser = {
      uid: `dev-uid-${email.toLowerCase()}`,
      email: email.toLowerCase(),
      displayName: null,
      emailVerified: true,
    };
    sessionStorage.setItem(DEV_SESSION_KEY, user.email);
    emit(user);
    return user;
  }

  const { signInWithEmailAndPassword } = await import("firebase/auth");
  const auth = await getFirebaseAuth();
  const credential = await signInWithEmailAndPassword(auth, email, password);
  return {
    uid: credential.user.uid,
    email: credential.user.email ?? "",
    displayName: credential.user.displayName,
    emailVerified: credential.user.emailVerified,
  };
}

export async function signInWithGoogle(): Promise<AuthUser> {
  if (IS_DEV_AUTH) {
    throw new Error("Google sign-in requires a configured Firebase project.");
  }
  const { GoogleAuthProvider, signInWithPopup } = await import("firebase/auth");
  const auth = await getFirebaseAuth();
  const credential = await signInWithPopup(auth, new GoogleAuthProvider());
  return {
    uid: credential.user.uid,
    email: credential.user.email ?? "",
    displayName: credential.user.displayName,
    emailVerified: credential.user.emailVerified,
  };
}

export async function sendPasswordReset(email: string): Promise<void> {
  if (IS_DEV_AUTH) return;
  const { sendPasswordResetEmail } = await import("firebase/auth");
  const auth = await getFirebaseAuth();
  await sendPasswordResetEmail(auth, email);
}

export async function signOut(): Promise<void> {
  if (IS_DEV_AUTH) {
    sessionStorage.removeItem(DEV_SESSION_KEY);
    emit(null);
    return;
  }
  const { signOut: fbSignOut } = await import("firebase/auth");
  const auth = await getFirebaseAuth();
  await fbSignOut(auth);
  emit(null);
}

/**
 * Current ID token, or null when signed out.
 *
 * The Firebase SDK refreshes automatically; `forceRefresh` is used by the API
 * client's single retry after a `TOKEN_EXPIRED`.
 */
export async function getIdToken(forceRefresh = false): Promise<string | null> {
  if (IS_DEV_AUTH) {
    const email = sessionStorage.getItem(DEV_SESSION_KEY);
    return email ? `dev:${email}` : null;
  }

  const auth = await getFirebaseAuth();
  const user = auth.currentUser;
  if (!user) return null;
  return user.getIdToken(forceRefresh);
}

/** Restore a session on page load, before React renders. */
export async function restoreSession(): Promise<AuthUser | null> {
  if (IS_DEV_AUTH) {
    const email = sessionStorage.getItem(DEV_SESSION_KEY);
    const user = email
      ? { uid: `dev-uid-${email}`, email, displayName: null, emailVerified: true }
      : null;
    emit(user);
    return user;
  }

  const auth = await getFirebaseAuth();
  // onAuthStateChanged fires once with the restored (or null) user.
  return new Promise((resolve) => {
    const unsubscribe = onAuthChange((user) => {
      unsubscribe();
      resolve(user);
    });
    void auth;
  });
}

/** Firebase error codes rendered as something a person can act on. */
export function describeAuthError(error: unknown): string {
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
