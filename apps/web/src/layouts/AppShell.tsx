/**
 * Application shell — sidebar, topbar, content, mobile navigation.
 *
 * Serves both the platform (Super Admin) and society scopes; the navigation
 * items come from the server, already filtered by the principal's permissions.
 *
 * Responsive behaviour:
 *   ≥1024px  fixed 264px sidebar
 *   768px    64px icon rail
 *   <768px   sheet drawer + bottom navigation bar
 */

import * as Dialog from "@radix-ui/react-dialog";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import {
  ChevronsLeft,
  LogOut,
  Menu,
  MoreHorizontal,
  Sparkles,
  User,
  X,
} from "lucide-react";
import * as React from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { NavIcon } from "@/components/nestflow/NavIcon";
import { NFAvatar, NFButton } from "@/components/nestflow/primitives";
import NotificationBell from "@/features/notifications/NotificationBell";
import { useAppDispatch, useAppSelector } from "@/store";
import { signOut } from "@/store/authSlice";
import { setMobileNav, toggleSidebar } from "@/store/uiSlice";
import type { NavItem } from "@/types";
import { cn } from "@/utils/cn";

/* -------------------------------------------------------------------------- */

function SidebarContent({
  navigation,
  collapsed,
  onNavigate,
}: {
  navigation: NavItem[];
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  const society = useAppSelector((s) => s.auth.society);
  const principal = useAppSelector((s) => s.auth.principal);
  const logoUrl = useAppSelector((s) => s.theme.config.logoUrl);

  const title = principal?.is_super_admin ? "NestFlow" : (society?.name ?? "NestFlow");
  const subtitle = principal?.is_super_admin ? "Platform" : society?.city;

  return (
    <div className="flex h-full flex-col bg-[var(--nf-sidebar)]">
      {/* Brand */}
      <div
        className={cn(
          "flex h-16 shrink-0 items-center gap-3 border-b border-white/10 px-4",
          collapsed && "justify-center px-2",
        )}
      >
        {logoUrl ? (
          <img src={logoUrl} alt="" className="size-9 shrink-0 rounded-[var(--nf-radius-sm)] object-cover" />
        ) : (
          <span
            className="flex size-9 shrink-0 items-center justify-center rounded-[var(--nf-radius-sm)] font-bold text-[var(--nf-primary-foreground)]"
            style={{ backgroundColor: "var(--nf-primary)" }}
            aria-hidden
          >
            N
          </span>
        )}
        {!collapsed && (
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-white">{title}</p>
            {subtitle && (
              <p className="truncate text-[11px] text-[var(--nf-sidebar-foreground)]">{subtitle}</p>
            )}
          </div>
        )}
      </div>

      {/* Navigation */}
      <nav
        aria-label="Main navigation"
        className="nf-scroll flex-1 space-y-0.5 overflow-y-auto px-2 py-3"
      >
        {navigation.map((item) => {
          const comingSoon = item.badge === "coming_soon";
          return (
            <NavLink
              key={item.key}
              to={item.path}
              onClick={(e) => {
                if (comingSoon) {
                  e.preventDefault();
                  return;
                }
                onNavigate?.();
              }}
              aria-disabled={comingSoon || undefined}
              title={collapsed ? item.label : undefined}
              className={({ isActive }) =>
                cn(
                  "group flex items-center gap-3 rounded-[var(--nf-radius-sm)] px-3 py-2 text-sm font-medium transition-colors",
                  collapsed && "justify-center px-2",
                  comingSoon
                    ? "cursor-not-allowed text-[var(--nf-sidebar-foreground)]/40"
                    : isActive
                      ? "bg-[var(--nf-sidebar-active)] text-white"
                      : "text-[var(--nf-sidebar-foreground)] hover:bg-white/5 hover:text-white",
                )
              }
            >
              <NavIcon name={item.icon} className="size-[18px] shrink-0" />
              {!collapsed && (
                <>
                  <span className="flex-1 truncate">{item.label}</span>
                  {comingSoon && (
                    <span className="rounded-full bg-white/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide">
                      Soon
                    </span>
                  )}
                </>
              )}
            </NavLink>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="shrink-0 border-t border-white/10 p-3">
        {!collapsed && (
          <p className="px-1 text-[11px] text-[var(--nf-sidebar-foreground)]/60">
            NestFlow · v0.1.0
          </p>
        )}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */

function UserMenu() {
  const principal = useAppSelector((s) => s.auth.principal);
  const dispatch = useAppDispatch();
  const navigate = useNavigate();

  if (!principal) return null;

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          className="flex items-center gap-2 rounded-[var(--nf-radius-sm)] p-1 pr-2 transition-colors hover:bg-[var(--nf-primary-subtle)]"
          aria-label="Account menu"
        >
          <NFAvatar name={principal.display_name} size={32} />
          <span className="hidden text-left sm:block">
            <span className="block max-w-36 truncate text-[13px] font-medium text-[var(--nf-text)]">
              {principal.display_name}
            </span>
            <span className="block text-[11px] text-[var(--nf-text-muted)]">
              {principal.roles[0]?.replace(/_/g, " ") ?? ""}
            </span>
          </span>
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={8}
          className="z-50 min-w-56 rounded-[var(--nf-radius)] border border-[var(--nf-border)] bg-[var(--nf-surface-raised)] p-1.5 nf-shadow-lg data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95"
        >
          <div className="border-b border-[var(--nf-border)] px-3 py-2.5">
            <p className="truncate text-sm font-medium text-[var(--nf-text)]">
              {principal.display_name}
            </p>
            <p className="truncate text-xs text-[var(--nf-text-muted)]">{principal.email}</p>
          </div>

          <DropdownMenu.Item asChild>
            <Link
              to="/app/profile"
              className="flex cursor-pointer items-center gap-2 rounded-[var(--nf-radius-sm)] px-3 py-2 text-sm text-[var(--nf-text)] outline-none data-[highlighted]:bg-[var(--nf-primary-subtle)]"
            >
              <User className="size-4" aria-hidden /> Profile
            </Link>
          </DropdownMenu.Item>

          <DropdownMenu.Separator className="my-1 h-px bg-[var(--nf-border)]" />

          <DropdownMenu.Item
            onSelect={async () => {
              await dispatch(signOut());
              navigate("/login", { replace: true });
            }}
            className="flex cursor-pointer items-center gap-2 rounded-[var(--nf-radius-sm)] px-3 py-2 text-sm text-[var(--nf-danger)] outline-none data-[highlighted]:bg-[var(--nf-danger-subtle)]"
          >
            <LogOut className="size-4" aria-hidden /> Sign out
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

/* -------------------------------------------------------------------------- */

/** Bottom bar for small screens. The first four items plus a "More" sheet. */
function MobileNavigation({ navigation }: { navigation: NavItem[] }) {
  const [moreOpen, setMoreOpen] = React.useState(false);
  const primary = navigation.filter((n) => n.badge !== "coming_soon").slice(0, 4);
  const rest = navigation.filter((n) => !primary.includes(n));

  return (
    <>
      <nav
        aria-label="Primary"
        className="fixed inset-x-0 bottom-0 z-40 flex border-t border-[var(--nf-border)] bg-[var(--nf-surface)] pb-[env(safe-area-inset-bottom)] md:hidden"
      >
        {primary.map((item) => (
          <NavLink
            key={item.key}
            to={item.path}
            className={({ isActive }) =>
              cn(
                "flex flex-1 flex-col items-center gap-1 py-2.5 text-[10px] font-medium transition-colors",
                isActive ? "text-[var(--nf-primary)]" : "text-[var(--nf-text-muted)]",
              )
            }
          >
            <NavIcon name={item.icon} className="size-5" />
            <span className="max-w-full truncate px-1">{item.label}</span>
          </NavLink>
        ))}

        {rest.length > 0 && (
          <button
            onClick={() => setMoreOpen(true)}
            className="flex flex-1 flex-col items-center gap-1 py-2.5 text-[10px] font-medium text-[var(--nf-text-muted)]"
          >
            <MoreHorizontal className="size-5" aria-hidden />
            <span>More</span>
          </button>
        )}
      </nav>

      <Dialog.Root open={moreOpen} onOpenChange={setMoreOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-black/45 md:hidden" />
          <Dialog.Content className="fixed inset-x-0 bottom-0 z-50 max-h-[75vh] overflow-y-auto nf-scroll rounded-t-[var(--nf-radius-xl)] border-t border-[var(--nf-border)] bg-[var(--nf-surface)] p-4 pb-[calc(1rem+env(safe-area-inset-bottom))] md:hidden data-[state=open]:animate-in data-[state=open]:slide-in-from-bottom">
            <Dialog.Title className="mb-3 text-sm font-semibold text-[var(--nf-text)]">
              All sections
            </Dialog.Title>
            <Dialog.Description className="sr-only">
              Navigate to any section of the app
            </Dialog.Description>
            <div className="grid grid-cols-3 gap-2">
              {rest.map((item) => {
                const comingSoon = item.badge === "coming_soon";
                return (
                  <Link
                    key={item.key}
                    to={comingSoon ? "#" : item.path}
                    onClick={(e) => {
                      if (comingSoon) e.preventDefault();
                      else setMoreOpen(false);
                    }}
                    aria-disabled={comingSoon || undefined}
                    className={cn(
                      "flex flex-col items-center gap-2 rounded-[var(--nf-radius)] border border-[var(--nf-border)] p-3 text-center text-[11px] font-medium",
                      comingSoon
                        ? "opacity-40"
                        : "text-[var(--nf-text)] active:bg-[var(--nf-primary-subtle)]",
                    )}
                  >
                    <NavIcon name={item.icon} className="size-5 text-[var(--nf-primary)]" />
                    <span className="line-clamp-2">{item.label}</span>
                  </Link>
                );
              })}
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}

/* -------------------------------------------------------------------------- */

export default function AppShell() {
  const dispatch = useAppDispatch();
  const location = useLocation();
  const { sidebarCollapsed, mobileNavOpen } = useAppSelector((s) => s.ui);
  const navigation = useAppSelector((s) => s.auth.navigation);
  const subscription = useAppSelector((s) => s.auth.subscription);
  const authProvider = useAppSelector((s) => s.auth.authProvider);

  // Close the drawer whenever the route changes.
  React.useEffect(() => {
    dispatch(setMobileNav(false));
  }, [location.pathname, dispatch]);

  const current = navigation.find((n) => location.pathname.startsWith(n.path));

  return (
    <div className="flex min-h-dvh bg-[var(--nf-background)]">
      {/* Desktop sidebar */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-30 hidden shrink-0 transition-[width] duration-200 md:block",
          sidebarCollapsed ? "w-16" : "w-16 lg:w-[264px]",
        )}
      >
        <SidebarContent navigation={navigation} collapsed={sidebarCollapsed} />
      </aside>

      {/* Mobile drawer */}
      <Dialog.Root open={mobileNavOpen} onOpenChange={(o) => dispatch(setMobileNav(o))}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-black/50 md:hidden" />
          <Dialog.Content className="fixed inset-y-0 left-0 z-50 w-[264px] md:hidden data-[state=open]:animate-in data-[state=open]:slide-in-from-left">
            <Dialog.Title className="sr-only">Navigation</Dialog.Title>
            <Dialog.Description className="sr-only">Main application navigation</Dialog.Description>
            <Dialog.Close asChild>
              <button
                className="absolute right-2 top-4 z-10 rounded-[var(--nf-radius-sm)] p-2 text-white/70 hover:bg-white/10"
                aria-label="Close navigation"
              >
                <X className="size-5" />
              </button>
            </Dialog.Close>
            <SidebarContent navigation={navigation} collapsed={false} />
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      {/* Main column */}
      <div
        className={cn(
          "flex min-w-0 flex-1 flex-col transition-[padding] duration-200",
          sidebarCollapsed ? "md:pl-16" : "md:pl-16 lg:pl-[264px]",
        )}
      >
        <header className="sticky top-0 z-20 flex h-16 shrink-0 items-center gap-3 border-b border-[var(--nf-border)] bg-[var(--nf-surface)]/85 px-4 backdrop-blur-md">
          <NFButton
            variant="ghost"
            size="icon-sm"
            className="md:hidden"
            onClick={() => dispatch(setMobileNav(true))}
            aria-label="Open navigation"
          >
            <Menu />
          </NFButton>

          <NFButton
            variant="ghost"
            size="icon-sm"
            className="hidden lg:inline-flex"
            onClick={() => dispatch(toggleSidebar())}
            aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            <ChevronsLeft className={cn("transition-transform", sidebarCollapsed && "rotate-180")} />
          </NFButton>

          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-[var(--nf-text)]">
              {current?.label ?? "Dashboard"}
            </p>
          </div>

          {authProvider === "dev" && (
            <span
              className="hidden items-center gap-1.5 rounded-full border border-[var(--nf-warning)]/30 bg-[var(--nf-warning-subtle)] px-2.5 py-1 text-[11px] font-semibold text-[var(--nf-warning)] sm:inline-flex"
              title="Development authentication is active — tokens are not verified against Firebase."
            >
              <Sparkles className="size-3" aria-hidden /> DEV AUTH
            </span>
          )}

          {subscription?.is_trial && (
            <span className="hidden rounded-full border border-[var(--nf-info)]/30 bg-[var(--nf-info-subtle)] px-2.5 py-1 text-[11px] font-semibold text-[var(--nf-info)] sm:inline-block">
              Trial · {subscription.days_remaining}d left
            </span>
          )}

          <NotificationBell />

          <UserMenu />
        </header>

        <main className="mx-auto w-full max-w-[1440px] flex-1 px-4 py-6 pb-24 sm:px-6 md:pb-6">
          <Outlet />
        </main>
      </div>

      <MobileNavigation navigation={navigation} />
    </div>
  );
}
