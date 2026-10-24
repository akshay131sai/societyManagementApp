/**
 * The bell, its badge and its menu.
 *
 * One request fills all three (`/notifications/feed` returns the items and the
 * unread count together), so the badge can never disagree with the list a
 * second after the user opens it.
 *
 * The socket only ever *invalidates*: an incoming event refetches the feed
 * rather than trying to splice a notification into local state. A list built by
 * merging pushes drifts from the server the first time one is missed, and this
 * one cannot.
 */

import { Bell, Check, Inbox } from "lucide-react";
import * as React from "react";
import { useNavigate } from "react-router-dom";

import { NFButton } from "@/components/nestflow/primitives";
import { useRealtime } from "@/hooks/useRealtime";
import { api } from "@/services/api";
import { useAppSelector } from "@/store";
import type { NotificationFeed } from "@/types";
import { cn } from "@/utils/cn";
import { formatRelative } from "@/utils/format";
import { hasPermission } from "@/utils/permissions";

const EMPTY: NotificationFeed = { items: [], unread: 0, total: 0 };

export default function NotificationBell() {
  const principal = useAppSelector((s) => s.auth.principal);
  const enabled = hasPermission(principal, "notification.read");

  const [feed, setFeed] = React.useState<NotificationFeed>(EMPTY);
  const [open, setOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const navigate = useNavigate();
  const panelRef = React.useRef<HTMLDivElement>(null);

  const refresh = React.useCallback(() => {
    if (!enabled) return;
    api
      .get<NotificationFeed>("/notifications/feed", { limit: 15 })
      .then(setFeed)
      .catch(() => undefined);
  }, [enabled]);

  React.useEffect(refresh, [refresh]);

  const { connected } = useRealtime({
    enabled,
    onNotification: refresh,
    onReconnect: refresh,
  });

  // Without a socket the badge would be as stale as the last page load, so
  // fall back to a slow poll rather than showing a number nobody can trust.
  React.useEffect(() => {
    if (!enabled || connected) return;
    const timer = window.setInterval(refresh, 60_000);
    return () => window.clearInterval(timer);
  }, [enabled, connected, refresh]);

  // Close on an outside click or Escape. Radix is not used here because the
  // panel is a plain popover, not a focus-trapping dialog.
  React.useEffect(() => {
    if (!open) return;
    function onPointer(event: MouseEvent) {
      if (!panelRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!enabled) return null;

  async function markAllRead() {
    setBusy(true);
    try {
      await api.post("/notifications/read-all");
      refresh();
    } finally {
      setBusy(false);
    }
  }

  async function openNotification(id: string, link: string | null, isRead: boolean) {
    setOpen(false);
    if (!isRead) {
      await api.post("/notifications/read", { ids: [id] }).catch(() => undefined);
      refresh();
    }
    if (link) navigate(link);
  }

  const badge = feed.unread > 99 ? "99+" : String(feed.unread);

  return (
    <div className="relative" ref={panelRef}>
      <NFButton
        variant="ghost"
        size="icon-sm"
        aria-label={
          feed.unread > 0 ? `Notifications, ${feed.unread} unread` : "Notifications"
        }
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <Bell />
        {feed.unread > 0 && (
          <span
            className="absolute -right-0.5 -top-0.5 flex min-w-4 items-center justify-center rounded-full bg-[var(--nf-danger)] px-1 text-[10px] font-bold leading-4 text-white"
            aria-hidden
          >
            {badge}
          </span>
        )}
      </NFButton>

      {open && (
        <div
          role="dialog"
          aria-label="Notifications"
          className="absolute right-0 z-40 mt-2 w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-[var(--nf-radius-lg)] border border-[var(--nf-border)] bg-[var(--nf-surface)] nf-shadow-lg"
        >
          <div className="flex items-center justify-between gap-2 border-b border-[var(--nf-border)] px-4 py-3">
            <div className="flex items-center gap-2">
              <p className="text-sm font-semibold text-[var(--nf-text)]">Notifications</p>
              <span
                className={cn(
                  "size-1.5 rounded-full",
                  connected ? "bg-[var(--nf-success)]" : "bg-[var(--nf-text-subtle)]",
                )}
                title={connected ? "Live" : "Reconnecting — refreshing every minute"}
                aria-hidden
              />
            </div>
            {feed.unread > 0 && (
              <NFButton variant="ghost" size="sm" onClick={markAllRead} loading={busy}>
                <Check /> Mark all read
              </NFButton>
            )}
          </div>

          <div className="nf-scroll max-h-[26rem] overflow-y-auto">
            {feed.items.length === 0 ? (
              <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
                <Inbox className="size-6 text-[var(--nf-text-subtle)]" aria-hidden />
                <p className="text-[13px] text-[var(--nf-text-muted)]">
                  Nothing yet. Complaints, visitors and bookings show up here.
                </p>
              </div>
            ) : (
              <ul className="divide-y divide-[var(--nf-border)]">
                {feed.items.map((n) => (
                  <li key={n.id}>
                    <button
                      type="button"
                      onClick={() => openNotification(n.id, n.link, n.is_read)}
                      className={cn(
                        "flex w-full items-start gap-2.5 px-4 py-3 text-left transition-colors hover:bg-[var(--nf-primary-subtle)]",
                        !n.is_read && "bg-[var(--nf-primary-subtle)]/40",
                      )}
                    >
                      <span
                        className={cn(
                          "mt-1.5 size-1.5 shrink-0 rounded-full",
                          n.is_read ? "bg-transparent" : "bg-[var(--nf-primary)]",
                        )}
                        aria-hidden
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13px] font-medium text-[var(--nf-text)]">
                          {n.title}
                        </span>
                        {n.body && (
                          <span className="mt-0.5 block truncate text-xs text-[var(--nf-text-muted)]">
                            {n.body}
                          </span>
                        )}
                        <span className="mt-1 block text-[11px] text-[var(--nf-text-subtle)]">
                          {formatRelative(n.created_at)}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {feed.total > feed.items.length && (
            <div className="border-t border-[var(--nf-border)] px-4 py-2.5 text-center">
              <span className="text-[11px] text-[var(--nf-text-subtle)]">
                Showing the latest {feed.items.length} of {feed.total}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
