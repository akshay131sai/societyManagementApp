/**
 * Authentication and session state.
 *
 * Holds the principal, society context, subscription and navigation — all
 * small, session-shaped values. Server datasets (residents, bills, visitors)
 * are never kept here; those are server-paginated and fetched per page.
 */

import { createAsyncThunk, createSlice, type PayloadAction } from "@reduxjs/toolkit";

import { ApiError, api } from "@/services/api";
import * as authService from "@/services/auth";
import type {
  MeResponse,
  NavItem,
  Principal,
  SocietyContext,
  SubscriptionContext,
} from "@/types";

export type AuthStatus = "idle" | "loading" | "authenticated" | "unauthenticated" | "error";

export interface AuthState {
  status: AuthStatus;
  principal: Principal | null;
  society: SocietyContext | null;
  subscription: SubscriptionContext | null;
  navigation: NavItem[];
  authProvider: string;
  /** Machine code from the backend — drives which blocked screen is shown. */
  errorCode: string | null;
  errorMessage: string | null;
}

const initialState: AuthState = {
  status: "idle",
  principal: null,
  society: null,
  subscription: null,
  navigation: [],
  authProvider: authService.AUTH_PROVIDER,
  errorCode: null,
  errorMessage: null,
};

/** Load the full session in one call. */
export const bootstrapSession = createAsyncThunk<
  MeResponse,
  void,
  { rejectValue: { code: string; message: string } }
>("auth/bootstrap", async (_, { rejectWithValue }) => {
  try {
    return await api.get<MeResponse>("/auth/me");
  } catch (error) {
    if (error instanceof ApiError) {
      return rejectWithValue({ code: error.code, message: error.message });
    }
    return rejectWithValue({ code: "INTERNAL_ERROR", message: "Could not load your session." });
  }
});

export const signIn = createAsyncThunk<
  MeResponse,
  { email: string; password: string },
  { rejectValue: { code: string; message: string } }
>("auth/signIn", async ({ email, password }, { rejectWithValue }) => {
  try {
    await authService.signInWithEmail(email, password);
  } catch (error) {
    return rejectWithValue({
      code: "SIGN_IN_FAILED",
      message: authService.describeAuthError(error),
    });
  }

  try {
    const me = await api.get<MeResponse>("/auth/me");
    // Fire-and-forget: recording the login must never block entry to the app.
    void api.post("/auth/session").catch(() => undefined);
    return me;
  } catch (error) {
    // The identity is valid but NestFlow refused (not registered, locked,
    // expired). Drop the credential so the UI is not stuck half signed-in.
    await authService.signOut().catch(() => undefined);
    if (error instanceof ApiError) {
      return rejectWithValue({ code: error.code, message: error.message });
    }
    return rejectWithValue({ code: "INTERNAL_ERROR", message: "Could not load your session." });
  }
});

export const signOut = createAsyncThunk("auth/signOut", async () => {
  const { clearThemeCache } = await import("@/theme/deriveTokens");
  await authService.signOut();
  clearThemeCache();
});

const authSlice = createSlice({
  name: "auth",
  initialState,
  reducers: {
    setUnauthenticated(state) {
      state.status = "unauthenticated";
      state.principal = null;
      state.society = null;
      state.subscription = null;
      state.navigation = [];
    },
    clearError(state) {
      state.errorCode = null;
      state.errorMessage = null;
    },
    applySession(state, action: PayloadAction<MeResponse>) {
      hydrate(state, action.payload);
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(bootstrapSession.pending, (state) => {
        state.status = "loading";
      })
      .addCase(bootstrapSession.fulfilled, (state, action) => {
        hydrate(state, action.payload);
      })
      .addCase(bootstrapSession.rejected, (state, action) => {
        applyFailure(state, action.payload);
      })
      .addCase(signIn.pending, (state) => {
        state.status = "loading";
        state.errorCode = null;
        state.errorMessage = null;
      })
      .addCase(signIn.fulfilled, (state, action) => {
        hydrate(state, action.payload);
      })
      .addCase(signIn.rejected, (state, action) => {
        applyFailure(state, action.payload);
      })
      .addCase(signOut.fulfilled, (state) => {
        state.status = "unauthenticated";
        state.principal = null;
        state.society = null;
        state.subscription = null;
        state.navigation = [];
        state.errorCode = null;
        state.errorMessage = null;
      });
  },
});

function hydrate(state: AuthState, me: MeResponse): void {
  state.status = "authenticated";
  state.principal = me.principal;
  state.society = me.society;
  state.subscription = me.subscription;
  state.navigation = me.navigation;
  state.authProvider = me.auth_provider;
  state.errorCode = null;
  state.errorMessage = null;
}

function applyFailure(
  state: AuthState,
  payload: { code: string; message: string } | undefined,
): void {
  // 401s mean "not signed in"; 402/403 mean "signed in but blocked", which the
  // router renders as a billing wall or lock screen rather than a login page.
  const blocked = new Set([
    "SUBSCRIPTION_EXPIRED",
    "SUBSCRIPTION_SUSPENDED",
    "SUBSCRIPTION_MISSING",
    "SOCIETY_LOCKED",
    "SOCIETY_SUSPENDED",
    "SOCIETY_ARCHIVED",
    "SOCIETY_PROVISIONING",
    "USER_DISABLED",
  ]);
  state.status = payload && blocked.has(payload.code) ? "error" : "unauthenticated";
  state.errorCode = payload?.code ?? null;
  state.errorMessage = payload?.message ?? null;
  state.principal = null;
  state.society = null;
  state.subscription = null;
  state.navigation = [];
}

export const { setUnauthenticated, clearError, applySession } = authSlice.actions;
export default authSlice.reducer;
