import type { Principal } from "@/types";

/**
 * Client-side permission helpers.
 *
 * These drive what the UI *offers*. They are never the enforcement point — the
 * backend refuses regardless of what the client chooses to render.
 */

export function hasPermission(principal: Principal | null, permission: string): boolean {
  return principal?.permissions.includes(permission) ?? false;
}

export function hasAnyPermission(principal: Principal | null, ...permissions: string[]): boolean {
  return permissions.some((p) => hasPermission(principal, p));
}

export function hasRole(principal: Principal | null, role: string): boolean {
  return principal?.roles.includes(role as never) ?? false;
}

export function homePathFor(principal: Principal | null): string {
  if (!principal) return "/login";
  return principal.is_super_admin ? "/admin/dashboard" : "/app/dashboard";
}
