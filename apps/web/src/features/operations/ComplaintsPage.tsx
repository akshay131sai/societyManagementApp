/**
 * Complaints.
 *
 * The same screen serves two very different people, and the difference is
 * capability rather than role:
 *
 * - A resident sees their own tickets, raises new ones, and gets exactly two
 *   moves on a resolved one — accept it, or say it is not fixed.
 * - Someone holding `complaint.manage` sees the whole society, the SLA header,
 *   the unassigned queue and the internal notes.
 *
 * **The buttons come from the server.** `allowed_transitions` is computed by
 * the same transition table the API enforces, so this screen cannot offer a
 * move the backend would refuse — and adding a status to the workflow does not
 * require touching this file.
 */

import {
  AlertTriangle,
  Clock,
  Filter,
  Lock,
  MessageSquare,
  Plus,
  Send,
  Star,
  UserCog,
} from "lucide-react";
import * as React from "react";

import {
  NFConfirmDialog,
  NFDataTable,
  NFDialog,
  NFPagination,
  NFSearch,
  NFStatCard,
  type Column,
} from "@/components/nestflow/data";
import {
  NFButton,
  NFCard,
  NFCardBody,
  NFCardHeader,
  NFEmptyState,
  NFField,
  NFInput,
  NFPageHeader,
  NFSelect,
  NFStatusBadge,
  NFTextarea,
  type BadgeTone,
} from "@/components/nestflow/primitives";
import { ApiError, api, type Page } from "@/services/api";
import { useAppSelector } from "@/store";
import type {
  Complaint,
  ComplaintCategory,
  ComplaintDetail,
  ComplaintStatus,
  ComplaintSummary,
  Priority,
  TenantUser,
} from "@/types";
import { cn } from "@/utils/cn";
import { formatDateTime, formatRelative } from "@/utils/format";
import { hasPermission } from "@/utils/permissions";

const LIMIT = 20;

const CATEGORIES: { value: ComplaintCategory; label: string }[] = [
  { value: "PLUMBING", label: "Plumbing" },
  { value: "ELECTRICAL", label: "Electrical" },
  { value: "LIFT", label: "Lift" },
  { value: "WATER_SUPPLY", label: "Water supply" },
  { value: "HOUSEKEEPING", label: "Housekeeping" },
  { value: "COMMON_AREA", label: "Common area" },
  { value: "SECURITY", label: "Security" },
  { value: "PARKING", label: "Parking" },
  { value: "NOISE", label: "Noise" },
  { value: "BILLING", label: "Billing" },
  { value: "OTHER", label: "Other" },
];

const PRIORITIES: Priority[] = ["LOW", "MEDIUM", "HIGH", "URGENT"];

const PRIORITY_TONE: Record<Priority, BadgeTone> = {
  LOW: "neutral",
  MEDIUM: "info",
  HIGH: "warning",
  URGENT: "danger",
};

const STATUS_TONE: Record<ComplaintStatus, BadgeTone> = {
  OPEN: "warning",
  ACKNOWLEDGED: "info",
  IN_PROGRESS: "info",
  RESOLVED: "success",
  CLOSED: "neutral",
  REJECTED: "danger",
  REOPENED: "danger",
};

/** What a status move is called from the person's point of view. */
const TRANSITION_LABEL: Record<ComplaintStatus, string> = {
  OPEN: "Reopen queue",
  ACKNOWLEDGED: "Acknowledge",
  IN_PROGRESS: "Start work",
  RESOLVED: "Mark resolved",
  CLOSED: "Close ticket",
  REJECTED: "Reject",
  REOPENED: "Not fixed — reopen",
};

/** The API asks for a note on these, so the dialog must too. */
const NOTE_REQUIRED: ComplaintStatus[] = ["RESOLVED", "REJECTED"];

const categoryLabel = (value: string) =>
  CATEGORIES.find((c) => c.value === value)?.label ?? value.replace(/_/g, " ");

export default function ComplaintsPage() {
  const principal = useAppSelector((s) => s.auth.principal);
  const canManage = hasPermission(principal, "complaint.manage");
  const canRaise = hasPermission(principal, "complaint.create");

  const [page, setPage] = React.useState(1);
  const [q, setQ] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [category, setCategory] = React.useState("");
  const [scope, setScope] = React.useState<"all" | "open" | "overdue" | "unassigned" | "mine">(
    "open",
  );
  const [rows, setRows] = React.useState<Page<Complaint> | null>(null);
  const [summary, setSummary] = React.useState<ComplaintSummary | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [openId, setOpenId] = React.useState<string | null>(null);
  const [raising, setRaising] = React.useState(false);
  const [reload, setReload] = React.useState(0);

  React.useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    api
      .get<Page<Complaint>>(
        "/complaints",
        {
          page,
          limit: LIMIT,
          q: q || undefined,
          status: status || undefined,
          category: category || undefined,
          open_only: scope === "open" || undefined,
          overdue_only: scope === "overdue" || undefined,
          unassigned_only: scope === "unassigned" || undefined,
          mine_only: scope === "mine" || undefined,
        },
        controller.signal,
      )
      .then(setRows)
      .catch(() => undefined)
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [page, q, status, category, scope, reload]);

  React.useEffect(() => {
    if (!canManage) return;
    const controller = new AbortController();
    api
      .get<ComplaintSummary>("/complaints/summary", undefined, controller.signal)
      .then(setSummary)
      .catch(() => undefined);
    return () => controller.abort();
  }, [canManage, reload]);

  const columns: Column<Complaint>[] = [
    {
      key: "ticket",
      header: "Ticket",
      render: (c) => (
        <div className="min-w-0">
          <p className="truncate font-medium text-[var(--nf-text)]">{c.title}</p>
          <p className="mt-0.5 font-mono text-[11px] text-[var(--nf-text-subtle)]">
            {c.ticket_number}
            {c.flat_number ? ` · ${c.flat_number}` : " · Common area"}
          </p>
        </div>
      ),
    },
    {
      key: "category",
      header: "Category",
      hideOnMobile: true,
      render: (c) => categoryLabel(c.category),
    },
    {
      key: "priority",
      header: "Priority",
      hideOnMobile: true,
      render: (c) => <NFStatusBadge status={c.priority} tone={PRIORITY_TONE[c.priority]} />,
    },
    {
      key: "status",
      header: "Status",
      render: (c) => (
        <div className="flex flex-wrap items-center gap-1.5">
          <NFStatusBadge status={c.status} tone={STATUS_TONE[c.status]} />
          {c.is_overdue && (
            <span
              className="inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--nf-danger)]"
              title={c.due_by ? `Target was ${formatDateTime(c.due_by)}` : undefined}
            >
              <AlertTriangle className="size-3" aria-hidden /> Overdue
            </span>
          )}
        </div>
      ),
    },
    ...(canManage
      ? [
          {
            key: "assignee",
            header: "Assigned to",
            hideOnMobile: true,
            render: (c: Complaint) =>
              c.assignee_name ?? (
                <span className="text-[var(--nf-warning)]">Unassigned</span>
              ),
          },
        ]
      : []),
    {
      key: "age",
      header: "Raised",
      hideOnMobile: true,
      render: (c) => formatRelative(c.created_at),
    },
  ];

  return (
    <>
      <NFPageHeader
        title="Complaints"
        description={
          canManage
            ? "Every ticket in the society, with the promise made when it was raised."
            : "Tickets you have raised, and anything affecting the common areas."
        }
        actions={
          canRaise ? (
            <NFButton onClick={() => setRaising(true)}>
              <Plus /> Raise a complaint
            </NFButton>
          ) : undefined
        }
      />

      {canManage && summary && (
        <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <NFStatCard label="Open" value={summary.open} icon={<MessageSquare />} tone="info" />
          <NFStatCard
            label="Past their target"
            value={summary.overdue}
            icon={<AlertTriangle />}
            tone={summary.overdue > 0 ? "danger" : "success"}
            hint={summary.overdue > 0 ? "These need someone today" : "Nothing is late"}
          />
          <NFStatCard
            label="Unassigned"
            value={summary.unassigned}
            icon={<UserCog />}
            tone={summary.unassigned > 0 ? "warning" : "success"}
          />
          <NFStatCard
            label="Average resolution"
            value={
              summary.average_resolution_hours
                ? `${Number(summary.average_resolution_hours).toFixed(1)} h`
                : "—"
            }
            icon={<Clock />}
            tone="primary"
            hint={
              summary.satisfaction
                ? `${Number(summary.satisfaction).toFixed(1)} / 5 from residents`
                : "No ratings yet"
            }
          />
        </div>
      )}

      <NFCard>
        <NFCardHeader
          title="Tickets"
          action={
            <div className="flex flex-wrap items-center gap-2">
              <NFSearch
                value={q}
                onChange={(value) => {
                  setQ(value);
                  setPage(1);
                }}
                placeholder="Title or ticket number"
              />
              <NFSelect
                aria-label="Scope"
                value={scope}
                onChange={(e) => {
                  setScope(e.target.value as typeof scope);
                  setPage(1);
                }}
                className="sm:w-40"
              >
                <option value="open">Open</option>
                <option value="overdue">Overdue</option>
                {canManage && <option value="unassigned">Unassigned</option>}
                {canManage && <option value="mine">Assigned to me</option>}
                <option value="all">All</option>
              </NFSelect>
              <NFSelect
                aria-label="Category"
                value={category}
                onChange={(e) => {
                  setCategory(e.target.value);
                  setPage(1);
                }}
                className="hidden sm:inline-flex sm:w-40"
              >
                <option value="">All categories</option>
                {CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </NFSelect>
              <NFSelect
                aria-label="Status"
                value={status}
                onChange={(e) => {
                  setStatus(e.target.value);
                  setPage(1);
                }}
                className="hidden lg:inline-flex lg:w-40"
              >
                <option value="">Any status</option>
                {Object.keys(STATUS_TONE).map((s) => (
                  <option key={s} value={s}>
                    {s.replace(/_/g, " ")}
                  </option>
                ))}
              </NFSelect>
            </div>
          }
        />
        <NFCardBody className="px-0 pb-0">
          <NFDataTable
            caption="Complaints"
            columns={columns}
            rows={rows?.items ?? []}
            rowKey={(c) => c.id}
            loading={loading}
            onRowClick={(c) => setOpenId(c.id)}
            empty={
              <div className="px-5 pb-5">
                <NFEmptyState
                  icon={<Filter />}
                  title={scope === "all" ? "No complaints" : "Nothing here"}
                  description={
                    canRaise
                      ? "Raise a ticket and it will appear here with a number you can quote."
                      : "No tickets match this filter."
                  }
                />
              </div>
            }
          />
          {rows && rows.total > 0 && (
            <div className="px-5 py-4">
              <NFPagination
                page={rows.page}
                pages={rows.pages}
                total={rows.total}
                limit={rows.limit}
                onPageChange={setPage}
              />
            </div>
          )}
        </NFCardBody>
      </NFCard>

      {openId && (
        <ComplaintDialog
          complaintId={openId}
          canManage={canManage}
          onClose={() => setOpenId(null)}
          onChanged={() => setReload((n) => n + 1)}
        />
      )}

      {canRaise && (
        <RaiseDialog
          open={raising}
          onOpenChange={setRaising}
          onSaved={() => {
            setRaising(false);
            setReload((n) => n + 1);
          }}
        />
      )}
    </>
  );
}

/* -------------------------------------------------------------------------- */
/* Detail                                                                     */
/* -------------------------------------------------------------------------- */

function ComplaintDialog({
  complaintId,
  canManage,
  onClose,
  onChanged,
}: {
  complaintId: string;
  canManage: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [detail, setDetail] = React.useState<ComplaintDetail | null>(null);
  const [staff, setStaff] = React.useState<TenantUser[]>([]);
  const [comment, setComment] = React.useState("");
  const [internal, setInternal] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [moving, setMoving] = React.useState<ComplaintStatus | null>(null);
  const [rating, setRating] = React.useState(0);

  const load = React.useCallback(() => {
    api
      .get<ComplaintDetail>(`/complaints/${complaintId}`)
      .then(setDetail)
      .catch(() => onClose());
  }, [complaintId, onClose]);

  React.useEffect(load, [load]);

  React.useEffect(() => {
    if (!canManage) return;
    api
      .get<Page<TenantUser>>("/users", { limit: 100 })
      .then((r) => setStaff(r.items))
      .catch(() => undefined);
  }, [canManage]);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      load();
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "That did not work.");
    } finally {
      setBusy(false);
    }
  }

  if (!detail) {
    return (
      <NFDialog open onOpenChange={onClose} title="Loading…" size="lg">
        <p className="py-8 text-center text-sm text-[var(--nf-text-muted)]">
          Fetching the ticket…
        </p>
      </NFDialog>
    );
  }

  const canRate =
    detail.rating === null && (detail.status === "RESOLVED" || detail.status === "CLOSED");

  return (
    <>
      <NFDialog
        open
        onOpenChange={(open) => !open && onClose()}
        title={detail.title}
        description={`${detail.ticket_number} · raised by ${detail.raised_by_name} ${formatRelative(detail.created_at)}`}
        size="lg"
        footer={
          <div className="flex w-full flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap gap-2">
              {/* Straight from the server's transition table — this screen
                  never invents a move the API would refuse. */}
              {detail.allowed_transitions.map((next) => (
                <NFButton
                  key={next}
                  size="sm"
                  variant={next === "REJECTED" || next === "REOPENED" ? "secondary" : "primary"}
                  onClick={() => setMoving(next)}
                  disabled={busy}
                >
                  {TRANSITION_LABEL[next]}
                </NFButton>
              ))}
            </div>
            <NFButton variant="secondary" onClick={onClose}>
              Close
            </NFButton>
          </div>
        }
      >
        <div className="space-y-5">
          {error && (
            <p
              role="alert"
              className="rounded-[var(--nf-radius-sm)] border border-[var(--nf-danger)]/30 bg-[var(--nf-danger-subtle)] px-3 py-2 text-[13px] text-[var(--nf-danger)]"
            >
              {error}
            </p>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <NFStatusBadge status={detail.status} tone={STATUS_TONE[detail.status]} />
            <NFStatusBadge status={detail.priority} tone={PRIORITY_TONE[detail.priority]} />
            <span className="text-[13px] text-[var(--nf-text-muted)]">
              {categoryLabel(detail.category)}
              {detail.flat_number ? ` · ${detail.flat_number}` : " · Common area"}
              {detail.location ? ` · ${detail.location}` : ""}
            </span>
          </div>

          {detail.due_by && (
            <p
              className={cn(
                "flex items-center gap-1.5 text-[13px]",
                detail.is_overdue ? "text-[var(--nf-danger)]" : "text-[var(--nf-text-muted)]",
              )}
            >
              <Clock className="size-3.5" aria-hidden />
              {detail.is_overdue ? "Target passed " : "Target "}
              {formatRelative(detail.due_by)}
              {detail.reopen_count > 0 && ` · reopened ${detail.reopen_count}×`}
            </p>
          )}

          <p className="whitespace-pre-wrap text-sm text-[var(--nf-text)]">
            {detail.description}
          </p>

          {canManage && (
            <NFField label="Assigned to" htmlFor="c-assignee">
              <NFSelect
                id="c-assignee"
                value={detail.assigned_to ?? ""}
                disabled={busy}
                onChange={(e) =>
                  run(() =>
                    api.post(`/complaints/${detail.id}/assignment`, {
                      assigned_to: e.target.value || null,
                    }),
                  )
                }
              >
                <option value="">Unassigned</option>
                {staff.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.full_name}
                  </option>
                ))}
              </NFSelect>
            </NFField>
          )}

          {detail.resolution_notes && (
            <div className="rounded-[var(--nf-radius-sm)] border border-[var(--nf-success)]/25 bg-[var(--nf-success-subtle)] px-3 py-2.5">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--nf-success)]">
                Resolution
              </p>
              <p className="mt-1 text-[13px] text-[var(--nf-text)]">{detail.resolution_notes}</p>
            </div>
          )}

          {canRate && (
            <div className="rounded-[var(--nf-radius-sm)] border border-[var(--nf-border)] px-3 py-2.5">
              <p className="text-[13px] font-medium text-[var(--nf-text)]">
                How did that go?
              </p>
              <div className="mt-2 flex items-center gap-1">
                {[1, 2, 3, 4, 5].map((n) => (
                  <button
                    key={n}
                    type="button"
                    aria-label={`${n} star${n === 1 ? "" : "s"}`}
                    onClick={() => {
                      setRating(n);
                      run(() => api.post(`/complaints/${detail.id}/rating`, { rating: n }));
                    }}
                    className="rounded p-0.5 focus-visible:ring-2 focus-visible:ring-[var(--nf-ring)]"
                  >
                    <Star
                      className={cn(
                        "size-5",
                        n <= rating
                          ? "fill-[var(--nf-warning)] text-[var(--nf-warning)]"
                          : "text-[var(--nf-text-subtle)]",
                      )}
                    />
                  </button>
                ))}
              </div>
            </div>
          )}

          {detail.rating !== null && (
            <p className="text-[13px] text-[var(--nf-text-muted)]">
              Rated {detail.rating}/5 by the resident
              {detail.rating_comment ? ` — “${detail.rating_comment}”` : ""}
            </p>
          )}

          {/* Timeline */}
          <div>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--nf-text-muted)]">
              Activity
            </p>
            <ul className="space-y-3">
              {detail.comments.map((c) => (
                <li key={c.id} className="flex gap-2.5">
                  <span
                    className={cn(
                      "mt-1.5 size-1.5 shrink-0 rounded-full",
                      c.is_system ? "bg-[var(--nf-text-subtle)]" : "bg-[var(--nf-primary)]",
                    )}
                    aria-hidden
                  />
                  <div className="min-w-0 flex-1">
                    <p
                      className={cn(
                        "text-[13px]",
                        c.is_system
                          ? "text-[var(--nf-text-muted)]"
                          : "text-[var(--nf-text)]",
                      )}
                    >
                      {c.body}
                      {c.is_internal && (
                        <span className="ml-1.5 inline-flex items-center gap-1 rounded bg-[var(--nf-warning-subtle)] px-1.5 py-0.5 text-[10px] font-semibold text-[var(--nf-warning)]">
                          <Lock className="size-2.5" aria-hidden /> Staff only
                        </span>
                      )}
                    </p>
                    <p className="mt-0.5 text-[11px] text-[var(--nf-text-subtle)]">
                      {c.author_name} · {formatDateTime(c.created_at)}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          </div>

          <div className="space-y-2">
            <NFTextarea
              aria-label="Add a comment"
              rows={2}
              placeholder="Add a reply…"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
            <div className="flex flex-wrap items-center justify-between gap-2">
              {canManage ? (
                <label className="flex items-center gap-2 text-[13px] text-[var(--nf-text-muted)]">
                  <input
                    type="checkbox"
                    checked={internal}
                    onChange={(e) => setInternal(e.target.checked)}
                    className="accent-[var(--nf-primary)]"
                  />
                  Internal note — the resident will not see this
                </label>
              ) : (
                <span />
              )}
              <NFButton
                size="sm"
                disabled={!comment.trim() || busy}
                onClick={() =>
                  run(async () => {
                    await api.post(`/complaints/${detail.id}/comments`, {
                      body: comment,
                      is_internal: internal,
                    });
                    setComment("");
                  })
                }
              >
                <Send /> Post
              </NFButton>
            </div>
          </div>
        </div>
      </NFDialog>

      {moving && (
        <TransitionDialog
          status={moving}
          busy={busy}
          onCancel={() => setMoving(null)}
          onConfirm={(note) =>
            run(async () => {
              await api.post(`/complaints/${detail.id}/transition`, {
                status: moving,
                note: note || null,
              });
              setMoving(null);
            })
          }
        />
      )}
    </>
  );
}

function TransitionDialog({
  status,
  busy,
  onCancel,
  onConfirm,
}: {
  status: ComplaintStatus;
  busy: boolean;
  onCancel: () => void;
  onConfirm: (note: string) => void;
}) {
  const [note, setNote] = React.useState("");
  const required = NOTE_REQUIRED.includes(status);

  return (
    <NFConfirmDialog
      open
      onOpenChange={(open) => !open && onCancel()}
      title={TRANSITION_LABEL[status]}
      confirmLabel={TRANSITION_LABEL[status]}
      destructive={status === "REJECTED"}
      loading={busy}
      onConfirm={() => onConfirm(note)}
    >
      <NFField
        label={required ? "What was done?" : "Note"}
        htmlFor="t-note"
        required={required}
        hint={
          required
            ? "A resolution without an explanation is what gets a ticket reopened."
            : "Optional — it goes on the ticket's timeline."
        }
      >
        <NFTextarea
          id="t-note"
          rows={3}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          autoFocus
        />
      </NFField>
    </NFConfirmDialog>
  );
}

/* -------------------------------------------------------------------------- */
/* Raise                                                                      */
/* -------------------------------------------------------------------------- */

function RaiseDialog({
  open,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}) {
  const [title, setTitle] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [category, setCategory] = React.useState<ComplaintCategory>("PLUMBING");
  const [priority, setPriority] = React.useState<Priority>("MEDIUM");
  const [location, setLocation] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    setTitle("");
    setDescription("");
    setLocation("");
    setError(null);
  }, [open]);

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      await api.post("/complaints", {
        title,
        description,
        category,
        priority,
        location: location || null,
      });
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not raise this complaint.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <NFDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Raise a complaint"
      description="You will get a ticket number you can quote to the office."
      footer={
        <div className="flex justify-end gap-2">
          <NFButton variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </NFButton>
          <NFButton
            onClick={submit}
            loading={saving}
            disabled={!title.trim() || !description.trim()}
          >
            Raise
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

        <NFField label="What is wrong?" htmlFor="n-title" required>
          <NFInput
            id="n-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Tap dripping in the kitchen"
            autoFocus
          />
        </NFField>

        <NFField
          label="Tell us more"
          htmlFor="n-desc"
          required
          hint="When it started, and anything that has been tried already."
        >
          <NFTextarea
            id="n-desc"
            rows={4}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </NFField>

        <div className="grid gap-4 sm:grid-cols-2">
          <NFField label="Category" htmlFor="n-cat">
            <NFSelect
              id="n-cat"
              value={category}
              onChange={(e) => setCategory(e.target.value as ComplaintCategory)}
            >
              {CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </NFSelect>
          </NFField>
          <NFField
            label="Priority"
            htmlFor="n-pri"
            hint="Urgent shortens the target the society works to."
          >
            <NFSelect
              id="n-pri"
              value={priority}
              onChange={(e) => setPriority(e.target.value as Priority)}
            >
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>
                  {p.charAt(0) + p.slice(1).toLowerCase()}
                </option>
              ))}
            </NFSelect>
          </NFField>
        </div>

        <NFField label="Where?" htmlFor="n-loc" hint="Optional">
          <NFInput
            id="n-loc"
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            placeholder="Kitchen sink, basement 2, lobby…"
          />
        </NFField>
      </div>
    </NFDialog>
  );
}
