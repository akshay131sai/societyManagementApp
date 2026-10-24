/**
 * Route guards.
 *
 * These decide what the client *renders*. They are convenience, not
 * enforcement — the backend refuses regardless of what the router allows.
 */

import * as React from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";

import { Spinner } from "@/components/nestflow/primitives";
import { useAppSelector } from "@/store";
import { hasPermission, homePathFor } from "@/utils/permissions";

export function FullPageLoader({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-3 bg-[var(--nf-background)]">
      <Spinner className="size-7 text-[var(--nf-primary)]" />
      <p className="text-sm text-[var(--nf-text-muted)]">{label}</p>
    </div>
  );
}

/** Blocked-state codes get their own screen rather than a login redirect. */
const BLOCKED_ROUTES: Record<string, string> = {
  SUBSCRIPTION_EXPIRED: "/subscription-expired",
  SUBSCRIPTION_SUSPENDED: "/subscription-expired",
  SUBSCRIPTION_MISSING: "/subscription-expired",
  SOCIETY_LOCKED: "/society-locked",
  SOCIETY_SUSPENDED: "/society-locked",
  SOCIETY_ARCHIVED: "/society-locked",
  USER_DISABLED: "/society-locked",
  SOCIETY_PROVISIONING: "/provisioning",
};

export function RequireAuth() {
  const { status, errorCode } = useAppSelector((s) => s.auth);
  const location = useLocation();

  if (status === "idle" || status === "loading") return <FullPageLoader />;

  if (status === "error" && errorCode && BLOCKED_ROUTES[errorCode]) {
    return <Navigate to={BLOCKED_ROUTES[errorCode]} replace />;
  }

  if (status !== "authenticated") {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  return <Outlet />;
}

export function RequireSuperAdmin() {
  const principal = useAppSelector((s) => s.auth.principal);
  if (!principal?.is_super_admin) {
    return <Navigate to={homePathFor(principal)} replace />;
  }
  return <Outlet />;
}

export function RequireSociety() {
  const principal = useAppSelector((s) => s.auth.principal);
  if (!principal) return <Navigate to="/login" replace />;
  if (principal.is_super_admin) return <Navigate to="/admin/dashboard" replace />;
  return <Outlet />;
}

export function RequirePermission({
  permission,
  children,
}: {
  permission: string;
  children: React.ReactNode;
}) {
  const principal = useAppSelector((s) => s.auth.principal);
  if (!hasPermission(principal, permission)) {
    return <Navigate to="/unauthorized" replace />;
  }
  return <>{children}</>;
}

/** Send an already-signed-in user away from the login screen. */
export function RedirectIfAuthenticated() {
  const { status, principal } = useAppSelector((s) => s.auth);
  if (status === "loading" || status === "idle") return <FullPageLoader />;
  if (status === "authenticated") return <Navigate to={homePathFor(principal)} replace />;
  return <Outlet />;
}
