/**
 * Application root.
 *
 * Bootstraps the session once, applies the society theme as soon as it
 * arrives, and keeps the theme in sync when the OS light/dark setting flips.
 */

import * as React from "react";
import { BrowserRouter } from "react-router-dom";

import AppRoutes from "@/routes";
import { restoreSession } from "@/services/auth";
import { onSessionEnd } from "@/services/tokens";
import { useAppDispatch, useAppSelector } from "@/store";
import { bootstrapSession, setUnauthenticated } from "@/store/authSlice";
import { fromPayload, setTheme } from "@/store/themeSlice";
import { api } from "@/services/api";
import {
  DEFAULT_THEME,
  applyTheme,
  cacheTheme,
  readCachedTheme,
  watchSystemTheme,
} from "@/theme/deriveTokens";
import type { ThemePayload } from "@/types";

function ThemeBridge() {
  const dispatch = useAppDispatch();
  const societyId = useAppSelector((s) => s.auth.society?.id);
  const status = useAppSelector((s) => s.auth.status);
  const config = useAppSelector((s) => s.theme.config);
  const draft = useAppSelector((s) => s.theme.draft);

  // Re-derive on an OS light/dark change, but only while the society is on
  // "system" — an explicit choice must not be overridden.
  const configRef = React.useRef(config);
  configRef.current = draft ?? config;
  React.useEffect(() => watchSystemTheme(() => configRef.current), []);

  // Paint the cached theme immediately, then let /auth/me overwrite it.
  React.useEffect(() => {
    if (!societyId) return;
    const cached = readCachedTheme(societyId);
    if (cached) applyTheme(cached);
  }, [societyId]);

  React.useEffect(() => {
    if (status !== "authenticated" || !societyId) return;
    api
      .get<ThemePayload>("/theme")
      .then((payload) => {
        const next = fromPayload(payload);
        dispatch(setTheme(next));
        cacheTheme(societyId, next);
      })
      .catch(() => undefined);
  }, [status, societyId, dispatch]);

  // A platform admin has no society theme; keep the default.
  const isSuperAdmin = useAppSelector((s) => s.auth.principal?.is_super_admin);
  React.useEffect(() => {
    if (isSuperAdmin) applyTheme(DEFAULT_THEME);
  }, [isSuperAdmin]);

  return null;
}

export default function App() {
  const dispatch = useAppDispatch();

  React.useEffect(() => {
    (async () => {
      const user = await restoreSession();
      if (user) {
        await dispatch(bootstrapSession());
      } else {
        dispatch(setUnauthenticated());
      }
    })();
  }, [dispatch]);

  // The refresh token was refused (expired, revoked, account disabled) or
  // another tab signed out: drop to the login screen.
  React.useEffect(() => onSessionEnd(() => dispatch(setUnauthenticated())), [dispatch]);

  return (
    <BrowserRouter>
      <ThemeBridge />
      <AppRoutes />
    </BrowserRouter>
  );
}
