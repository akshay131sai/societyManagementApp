/**
 * Notices.
 *
 * Rendered as cards rather than a table: a notice is something to *read*, and
 * a 200-word AGM announcement squeezed into a table row is a notice nobody
 * reads.
 *
 * Two things the server decides and this screen only reflects:
 *
 * - **Who sees what.** A reader gets society-wide notices, their own building's
 *   and block's, and their owner/tenant group. There is no client-side filter
 *   for this, because there is no client-side list to filter.
 * - **The read count.** It comes back as zero for a resident. Who else opened
 *   the AGM notice is not a neighbour's business.
 */

import {
  CalendarClock,
  Eye,
  Megaphone,
  Pin,
  Plus,
  Trash2,
  Users,
} from "lucide-react";
import * as React from "react";
import { useSearchParams } from "react-router-dom";

import { NFConfirmDialog, NFDialog, NFPagination, NFSearch } from "@/components/nestflow/data";
import {
  NFButton,
  NFCard,
  NFEmptyState,
  NFField,
  NFInput,
  NFPageHeader,
  NFSelect,
  NFSkeleton,
  NFStatusBadge,
  NFTextarea,
  type BadgeTone,
} from "@/components/nestflow/primitives";
import { ApiError, api, type Page } from "@/services/api";
import { useAppSelector } from "@/store";
import type {
  AudienceScope,
  Building,
  Notice,
  NoticeCategory,
  Priority,
} from "@/types";
import { cn } from "@/utils/cn";
import { formatDateTime, formatRelative } from "@/utils/format";
import { hasPermission } from "@/utils/permissions";

const LIMIT = 10;

const CATEGORIES: NoticeCategory[] = [
  "GENERAL",
  "URGENT",
  "MAINTENANCE",
  "EVENT",
  "MEETING",
  "BILLING",
  "SECURITY",
];

const CATEGORY_TONE: Record<NoticeCategory, BadgeTone> = {
  GENERAL: "neutral",
  URGENT: "danger",
  MAINTENANCE: "warning",
  EVENT: "primary",
  MEETING: "info",
  BILLING: "info",
  SECURITY: "danger",
};

const AUDIENCES: { value: AudienceScope; label: string; hint: string }[] = [
  { value: "ALL", label: "Everyone", hint: "Every resident and every member of staff" },
  { value: "BUILDING", label: "One building", hint: "Only that tower" },
  { value: "BLOCK", label: "One block", hint: "Only that wing" },
  { value: "OWNERS", label: "Owners only", hint: "Tenants will not see it" },
  { value: "TENANTS", label: "Tenants only", hint: "Owners will not see it" },
  { value: "STAFF", label: "Staff only", hint: "Guards, housekeeping, maintenance" },
];

const humanise = (v: string) => v.charAt(0) + v.slice(1).toLowerCase().replace(/_/g, " ");

export default function NoticesPage() {
  const principal = useAppSelector((s) => s.auth.principal);
  const canManage = hasPermission(principal, "notice.manage");

  const [params, setParams] = useSearchParams();
  const [page, setPage] = React.useState(1);
  const [q, setQ] = React.useState("");
  const [category, setCategory] = React.useState("");
  const [rows, setRows] = React.useState<Page<Notice> | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [composing, setComposing] = React.useState(false);
  const [reading, setReading] = React.useState<Notice | null>(null);
  const [deleting, setDeleting] = React.useState<Notice | null>(null);
  const [reload, setReload] = React.useState(0);

  React.useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    api
      .get<Page<Notice>>(
        "/notices",
        {
          page,
          limit: LIMIT,
          q: q || undefined,
          category: category || undefined,
          include_unpublished: canManage || undefined,
        },
        controller.signal,
      )
      .then(setRows)
      .catch(() => undefined)
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [page, q, category, canManage, reload]);

  // A notification links here with `?id=…`; open that notice straight away.
  const deepLink = params.get("id");
  React.useEffect(() => {
    if (!deepLink) return;
    api
      .get<Notice>(`/notices/${deepLink}`)
      .then((notice) => {
        setReading(notice);
        setReload((n) => n + 1);
      })
      .catch(() => undefined)
      .finally(() => {
        params.delete("id");
        setParams(params, { replace: true });
      });
  }, [deepLink, params, setParams]);

  async function open(notice: Notice) {
    setReading(notice);
    if (!notice.is_read) {
      await api.post(`/notices/${notice.id}/read`).catch(() => undefined);
      setReload((n) => n + 1);
    }
  }

  return (
    <>
      <NFPageHeader
        title="Notices"
        description={
          canManage
            ? "Announcements, and who each one reaches."
            : "Announcements from the committee."
        }
        actions={
          canManage ? (
            <NFButton onClick={() => setComposing(true)}>
              <Plus /> Post a notice
            </NFButton>
          ) : undefined
        }
      />

      <div className="mb-5 flex flex-wrap items-center gap-2">
        <NFSearch
          value={q}
          onChange={(value) => {
            setQ(value);
            setPage(1);
          }}
          placeholder="Search notices"
        />
        <NFSelect
          aria-label="Category"
          value={category}
          onChange={(e) => {
            setCategory(e.target.value);
            setPage(1);
          }}
          className="sm:w-44"
        >
          <option value="">All categories</option>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {humanise(c)}
            </option>
          ))}
        </NFSelect>
      </div>

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <NFCard key={i} className="p-5">
              <NFSkeleton className="h-5 w-2/3" />
              <NFSkeleton className="mt-3 h-4 w-full" />
              <NFSkeleton className="mt-2 h-4 w-4/5" />
            </NFCard>
          ))}
        </div>
      ) : (rows?.items.length ?? 0) === 0 ? (
        <NFEmptyState
          icon={<Megaphone />}
          title="No notices"
          description={
            canManage
              ? "Post one and it reaches the audience you choose, immediately or at a time you set."
              : "Nothing has been announced yet."
          }
        />
      ) : (
        <div className="space-y-3">
          {rows!.items.map((n) => (
            <NFCard
              key={n.id}
              className={cn(
                "cursor-pointer p-5 transition-colors hover:border-[var(--nf-primary)]/40",
                !n.is_read && "border-l-2 border-l-[var(--nf-primary)]",
              )}
              onClick={() => open(n)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  open(n);
                }
              }}
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    {n.is_pinned && (
                      <Pin className="size-3.5 text-[var(--nf-primary)]" aria-label="Pinned" />
                    )}
                    <h3 className="text-[15px] font-semibold text-[var(--nf-text)]">
                      {n.title}
                    </h3>
                    {!n.is_read && (
                      <span className="rounded-full bg-[var(--nf-primary)] px-1.5 py-0.5 text-[10px] font-bold text-white">
                        NEW
                      </span>
                    )}
                  </div>
                  <p className="mt-2 line-clamp-2 text-[13px] text-[var(--nf-text-muted)]">
                    {n.body}
                  </p>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-2">
                  <NFStatusBadge status={n.category} tone={CATEGORY_TONE[n.category]} />
                  {canManage && !n.is_published && (
                    <NFStatusBadge status="DRAFT" tone="neutral" />
                  )}
                </div>
              </div>

              <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-[var(--nf-text-subtle)]">
                <span>{n.author_name}</span>
                <span>·</span>
                <span>{formatRelative(n.publish_at ?? n.created_at)}</span>
                {n.audience !== "ALL" && (
                  <>
                    <span>·</span>
                    <span className="inline-flex items-center gap-1">
                      <Users className="size-3" aria-hidden />
                      {n.building_name ??
                        n.block_name ??
                        AUDIENCES.find((a) => a.value === n.audience)?.label}
                    </span>
                  </>
                )}
                {canManage && n.is_published && (
                  <>
                    <span>·</span>
                    <span className="inline-flex items-center gap-1">
                      <Eye className="size-3" aria-hidden />
                      {n.read_count} read
                    </span>
                  </>
                )}
                {n.expires_at && (
                  <>
                    <span>·</span>
                    <span className={n.is_expired ? "text-[var(--nf-danger)]" : undefined}>
                      {n.is_expired ? "Expired" : `Expires ${formatRelative(n.expires_at)}`}
                    </span>
                  </>
                )}
                {canManage && (
                  <button
                    type="button"
                    className="ml-auto inline-flex items-center gap-1 text-[var(--nf-danger)]"
                    onClick={(e) => {
                      e.stopPropagation();
                      setDeleting(n);
                    }}
                  >
                    <Trash2 className="size-3" aria-hidden /> Delete
                  </button>
                )}
              </div>
            </NFCard>
          ))}
        </div>
      )}

      {rows && rows.total > LIMIT && (
        <div className="mt-5">
          <NFPagination
            page={rows.page}
            pages={rows.pages}
            total={rows.total}
            limit={rows.limit}
            onPageChange={setPage}
          />
        </div>
      )}

      {reading && (
        <NFDialog
          open
          onOpenChange={(open) => !open && setReading(null)}
          title={reading.title}
          description={`${reading.author_name} · ${formatDateTime(reading.publish_at ?? reading.created_at)}`}
          size="lg"
          footer={<NFButton onClick={() => setReading(null)}>Close</NFButton>}
        >
          <div className="space-y-4">
            <div className="flex flex-wrap gap-2">
              <NFStatusBadge
                status={reading.category}
                tone={CATEGORY_TONE[reading.category]}
              />
              <NFStatusBadge status={reading.priority} tone="neutral" />
            </div>
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-[var(--nf-text)]">
              {reading.body}
            </p>
            {reading.attachments.length > 0 && (
              <ul className="space-y-1.5">
                {reading.attachments.map((a) => (
                  <li key={a.url}>
                    <a
                      href={a.url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-[13px] text-[var(--nf-primary)] underline"
                    >
                      {a.name}
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </NFDialog>
      )}

      {canManage && (
        <>
          <ComposeDialog
            open={composing}
            onOpenChange={setComposing}
            onSaved={() => {
              setComposing(false);
              setReload((n) => n + 1);
            }}
          />
          <NFConfirmDialog
            open={deleting !== null}
            onOpenChange={(open) => !open && setDeleting(null)}
            title="Delete this notice?"
            description={
              deleting
                ? `“${deleting.title}” will disappear for everyone, along with its read receipts.`
                : ""
            }
            confirmLabel="Delete"
            destructive
            onConfirm={async () => {
              if (!deleting) return;
              await api.delete(`/notices/${deleting.id}`);
              setDeleting(null);
              setReload((n) => n + 1);
            }}
          />
        </>
      )}
    </>
  );
}

/* -------------------------------------------------------------------------- */

function ComposeDialog({
  open,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}) {
  const [buildings, setBuildings] = React.useState<Building[]>([]);
  const [title, setTitle] = React.useState("");
  const [body, setBody] = React.useState("");
  const [category, setCategory] = React.useState<NoticeCategory>("GENERAL");
  const [priority, setPriority] = React.useState<Priority>("MEDIUM");
  const [audience, setAudience] = React.useState<AudienceScope>("ALL");
  const [buildingId, setBuildingId] = React.useState("");
  const [pinned, setPinned] = React.useState(false);
  const [publishNow, setPublishNow] = React.useState(true);
  const [publishAt, setPublishAt] = React.useState("");
  const [expiresAt, setExpiresAt] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    setTitle("");
    setBody("");
    setAudience("ALL");
    setBuildingId("");
    setPinned(false);
    setPublishNow(true);
    setPublishAt("");
    setExpiresAt("");
    setError(null);

    const controller = new AbortController();
    api
      .get<Building[]>("/buildings", undefined, controller.signal)
      .then(setBuildings)
      .catch(() => undefined);
    return () => controller.abort();
  }, [open]);

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      await api.post("/notices", {
        title,
        body,
        category,
        priority,
        audience,
        building_id: audience === "BUILDING" ? buildingId || null : null,
        is_pinned: pinned,
        publish_now: publishNow,
        publish_at: publishNow || !publishAt ? null : new Date(publishAt).toISOString(),
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
      });
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not post this notice.");
    } finally {
      setSaving(false);
    }
  }

  const audienceHint = AUDIENCES.find((a) => a.value === audience)?.hint;

  return (
    <NFDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Post a notice"
      size="lg"
      footer={
        <div className="flex justify-end gap-2">
          <NFButton variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </NFButton>
          <NFButton
            onClick={submit}
            loading={saving}
            disabled={
              !title.trim() ||
              !body.trim() ||
              (audience === "BUILDING" && !buildingId) ||
              (!publishNow && !publishAt)
            }
          >
            {publishNow ? "Publish" : "Schedule"}
          </NFButton>
        </div>
      }
    >
      <div className="space-y-4">
        {error && (
          <p
            role="alert"
            className="rounded-[var(--nf-radius-sm)] border border-[var(--nf-danger)]/30 bg-[var(--nf-danger-subtle)] px-3 py-2 text-[13px] text-[var(--nf-danger)]"
          >
            {error}
          </p>
        )}

        <NFField label="Title" htmlFor="no-title" required>
          <NFInput
            id="no-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Water tanker on Thursday"
            autoFocus
          />
        </NFField>

        <NFField label="Notice" htmlFor="no-body" required>
          <NFTextarea
            id="no-body"
            rows={6}
            value={body}
            onChange={(e) => setBody(e.target.value)}
          />
        </NFField>

        <div className="grid gap-4 sm:grid-cols-3">
          <NFField label="Category" htmlFor="no-cat">
            <NFSelect
              id="no-cat"
              value={category}
              onChange={(e) => setCategory(e.target.value as NoticeCategory)}
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {humanise(c)}
                </option>
              ))}
            </NFSelect>
          </NFField>
          <NFField label="Priority" htmlFor="no-pri">
            <NFSelect
              id="no-pri"
              value={priority}
              onChange={(e) => setPriority(e.target.value as Priority)}
            >
              {(["LOW", "MEDIUM", "HIGH", "URGENT"] as Priority[]).map((p) => (
                <option key={p} value={p}>
                  {humanise(p)}
                </option>
              ))}
            </NFSelect>
          </NFField>
          <NFField label="Who sees it" htmlFor="no-aud" hint={audienceHint}>
            <NFSelect
              id="no-aud"
              value={audience}
              onChange={(e) => setAudience(e.target.value as AudienceScope)}
            >
              {AUDIENCES.filter((a) => a.value !== "BLOCK").map((a) => (
                <option key={a.value} value={a.value}>
                  {a.label}
                </option>
              ))}
            </NFSelect>
          </NFField>
        </div>

        {audience === "BUILDING" && (
          <NFField label="Which building?" htmlFor="no-bldg" required>
            <NFSelect
              id="no-bldg"
              value={buildingId}
              onChange={(e) => setBuildingId(e.target.value)}
            >
              <option value="">Choose…</option>
              {buildings.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </NFSelect>
          </NFField>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <NFField
            label="When"
            htmlFor="no-when"
            hint="Leave as now, or set a time and it posts itself."
          >
            <div className="space-y-2">
              <label className="flex items-center gap-2 text-[13px] text-[var(--nf-text)]">
                <input
                  type="checkbox"
                  checked={publishNow}
                  onChange={(e) => setPublishNow(e.target.checked)}
                  className="accent-[var(--nf-primary)]"
                />
                Publish now
              </label>
              {!publishNow && (
                <NFInput
                  id="no-when"
                  type="datetime-local"
                  value={publishAt}
                  onChange={(e) => setPublishAt(e.target.value)}
                />
              )}
            </div>
          </NFField>
          <NFField
            label="Take it down"
            htmlFor="no-exp"
            hint="Optional — it disappears on its own."
          >
            <NFInput
              id="no-exp"
              type="datetime-local"
              value={expiresAt}
              onChange={(e) => setExpiresAt(e.target.value)}
            />
          </NFField>
        </div>

        <label className="flex items-center gap-2 text-[13px] text-[var(--nf-text)]">
          <input
            type="checkbox"
            checked={pinned}
            onChange={(e) => setPinned(e.target.checked)}
            className="accent-[var(--nf-primary)]"
          />
          <Pin className="size-3.5" aria-hidden /> Pin to the top
        </label>

        {!publishNow && (
          <p className="flex items-center gap-1.5 text-[11px] text-[var(--nf-text-subtle)]">
            <CalendarClock className="size-3" aria-hidden />
            A scheduled notice is invisible to residents until its moment arrives.
          </p>
        )}
      </div>
    </NFDialog>
  );
}
