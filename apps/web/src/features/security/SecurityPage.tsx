/**
 * Security — the gate board and the incident log.
 *
 * The board is a single request. A guard's tablet is on society wi-fi at the
 * barrier, and six round trips is six spinners while somebody waits; assembled
 * server-side, the numbers also cannot disagree with each other.
 *
 * `occurred_at` is a separate field from "now" on purpose: a night guard writes
 * up the 2 a.m. incident when the shift ends, and a report of incidents by hour
 * that used the entry time would be wrong.
 */

import {
  AlertOctagon,
  DoorOpen,
  Plus,
  ShieldAlert,
  ShieldCheck,
  UserRoundCheck,
} from "lucide-react";
import * as React from "react";

import {
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
  IncidentSeverity,
  IncidentStatus,
  SecurityDashboard,
  SecurityIncident,
} from "@/types";
import { formatDateTime, formatRelative } from "@/utils/format";
import { hasPermission } from "@/utils/permissions";

const LIMIT = 20;

const SEVERITY_TONE: Record<IncidentSeverity, BadgeTone> = {
  INFO: "neutral",
  MINOR: "info",
  MAJOR: "warning",
  CRITICAL: "danger",
};

const STATUS_TONE: Record<IncidentStatus, BadgeTone> = {
  REPORTED: "warning",
  INVESTIGATING: "info",
  RESOLVED: "success",
  CLOSED: "neutral",
};

const SEVERITIES: IncidentSeverity[] = ["INFO", "MINOR", "MAJOR", "CRITICAL"];
const STATUSES: IncidentStatus[] = ["REPORTED", "INVESTIGATING", "RESOLVED", "CLOSED"];

const humanise = (v: string) => v.charAt(0) + v.slice(1).toLowerCase();

function localNow(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function SecurityPage() {
  const principal = useAppSelector((s) => s.auth.principal);
  const canManage = hasPermission(principal, "security.manage");

  const [board, setBoard] = React.useState<SecurityDashboard | null>(null);
  const [rows, setRows] = React.useState<Page<SecurityIncident> | null>(null);
  const [page, setPage] = React.useState(1);
  const [q, setQ] = React.useState("");
  const [severity, setSeverity] = React.useState("");
  const [openOnly, setOpenOnly] = React.useState(true);
  const [loading, setLoading] = React.useState(true);
  const [reporting, setReporting] = React.useState(false);
  const [editing, setEditing] = React.useState<SecurityIncident | null>(null);
  const [reload, setReload] = React.useState(0);

  React.useEffect(() => {
    const controller = new AbortController();
    api
      .get<SecurityDashboard>("/security/dashboard", undefined, controller.signal)
      .then(setBoard)
      .catch(() => undefined);
    return () => controller.abort();
  }, [reload]);

  React.useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    api
      .get<Page<SecurityIncident>>(
        "/security/incidents",
        {
          page,
          limit: LIMIT,
          q: q || undefined,
          severity: severity || undefined,
          open_only: openOnly || undefined,
        },
        controller.signal,
      )
      .then(setRows)
      .catch(() => undefined)
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [page, q, severity, openOnly, reload]);

  const columns: Column<SecurityIncident>[] = [
    {
      key: "title",
      header: "Incident",
      render: (i) => (
        <div className="min-w-0">
          <p className="truncate font-medium text-[var(--nf-text)]">{i.title}</p>
          <p className="mt-0.5 truncate text-[11px] text-[var(--nf-text-subtle)]">
            {[i.location, i.building_name, i.flat_number].filter(Boolean).join(" · ") ||
              "Location not recorded"}
          </p>
        </div>
      ),
    },
    {
      key: "severity",
      header: "Severity",
      render: (i) => <NFStatusBadge status={i.severity} tone={SEVERITY_TONE[i.severity]} />,
    },
    {
      key: "status",
      header: "Status",
      render: (i) => <NFStatusBadge status={i.status} tone={STATUS_TONE[i.status]} />,
    },
    {
      key: "when",
      header: "Happened",
      hideOnMobile: true,
      render: (i) => (
        <span title={formatDateTime(i.occurred_at)}>{formatRelative(i.occurred_at)}</span>
      ),
    },
    {
      key: "by",
      header: "Reported by",
      hideOnMobile: true,
      render: (i) => i.reported_by_name,
    },
  ];

  return (
    <>
      <NFPageHeader
        title="Security"
        description="Who is on the premises right now, and everything worth putting on record."
        actions={
          <NFButton onClick={() => setReporting(true)}>
            <Plus /> Report an incident
          </NFButton>
        }
      />

      {board && (
        <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <NFStatCard
            label="On the premises"
            value={board.visitors.on_premises}
            icon={<UserRoundCheck />}
            tone="success"
            hint={`${board.visitors.entries_today} entries today`}
          />
          <NFStatCard
            label="Waiting at the gate"
            value={board.visitors.awaiting_approval}
            icon={<DoorOpen />}
            tone={board.visitors.awaiting_approval > 0 ? "warning" : "info"}
          />
          <NFStatCard
            label="Open incidents"
            value={board.open_incidents}
            icon={<ShieldAlert />}
            tone={board.open_incidents > 0 ? "warning" : "success"}
            hint={`${board.incidents_this_month} this month`}
          />
          <NFStatCard
            label="Critical"
            value={board.critical_incidents}
            icon={<AlertOctagon />}
            tone={board.critical_incidents > 0 ? "danger" : "success"}
            hint={board.critical_incidents > 0 ? "Needs attention now" : "Nothing critical"}
          />
        </div>
      )}

      {board && board.on_premises.length > 0 && (
        <NFCard className="mb-6">
          <NFCardHeader
            title="Inside right now"
            description="Everyone checked in and not yet checked out."
          />
          <NFCardBody className="pt-4">
            <ul className="flex flex-wrap gap-2">
              {board.on_premises.map((v) => (
                <li
                  key={v.id}
                  className="rounded-full border border-[var(--nf-border)] bg-[var(--nf-background)] px-3 py-1.5 text-[13px]"
                >
                  <span className="font-medium text-[var(--nf-text)]">{v.visitor_name}</span>
                  <span className="text-[var(--nf-text-muted)]">
                    {" · "}
                    {v.flat_number ?? "—"}
                    {v.checked_in_at ? ` · ${formatRelative(v.checked_in_at)}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          </NFCardBody>
        </NFCard>
      )}

      <NFCard>
        <NFCardHeader
          title="Incident log"
          action={
            <div className="flex flex-wrap items-center gap-2">
              <NFSearch
                value={q}
                onChange={(value) => {
                  setQ(value);
                  setPage(1);
                }}
                placeholder="Search incidents"
              />
              <NFSelect
                aria-label="Severity"
                value={severity}
                onChange={(e) => {
                  setSeverity(e.target.value);
                  setPage(1);
                }}
                className="sm:w-36"
              >
                <option value="">Any severity</option>
                {SEVERITIES.map((s) => (
                  <option key={s} value={s}>
                    {humanise(s)}
                  </option>
                ))}
              </NFSelect>
              <label className="flex items-center gap-2 text-[13px] text-[var(--nf-text-muted)]">
                <input
                  type="checkbox"
                  checked={openOnly}
                  onChange={(e) => {
                    setOpenOnly(e.target.checked);
                    setPage(1);
                  }}
                  className="accent-[var(--nf-primary)]"
                />
                Open only
              </label>
            </div>
          }
        />
        <NFCardBody className="px-0 pb-0">
          <NFDataTable
            caption="Security incidents"
            columns={columns}
            rows={rows?.items ?? []}
            rowKey={(i) => i.id}
            loading={loading}
            onRowClick={canManage ? setEditing : undefined}
            empty={
              <div className="px-5 pb-5">
                <NFEmptyState
                  icon={<ShieldCheck />}
                  title="Nothing on record"
                  description="A quiet log is the good outcome. Report anything worth remembering."
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

      <ReportDialog
        open={reporting}
        onOpenChange={setReporting}
        onSaved={() => {
          setReporting(false);
          setReload((n) => n + 1);
        }}
      />

      {editing && canManage && (
        <ResolveDialog
          incident={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            setReload((n) => n + 1);
          }}
        />
      )}
    </>
  );
}

/* -------------------------------------------------------------------------- */

function ReportDialog({
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
  const [severity, setSeverity] = React.useState<IncidentSeverity>("MINOR");
  const [occurredAt, setOccurredAt] = React.useState(localNow);
  const [location, setLocation] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    setTitle("");
    setDescription("");
    setLocation("");
    setOccurredAt(localNow());
    setError(null);
  }, [open]);

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      await api.post("/security/incidents", {
        title,
        description,
        severity,
        occurred_at: new Date(occurredAt).toISOString(),
        location: location || null,
      });
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not record this incident.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <NFDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Report an incident"
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
            Record
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
        <NFField label="What happened?" htmlFor="i-title" required>
          <NFInput
            id="i-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Gate barrier struck"
            autoFocus
          />
        </NFField>
        <NFField label="Tell it in full" htmlFor="i-desc" required>
          <NFTextarea
            id="i-desc"
            rows={4}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </NFField>
        <div className="grid gap-4 sm:grid-cols-3">
          <NFField label="Severity" htmlFor="i-sev">
            <NFSelect
              id="i-sev"
              value={severity}
              onChange={(e) => setSeverity(e.target.value as IncidentSeverity)}
            >
              {SEVERITIES.map((s) => (
                <option key={s} value={s}>
                  {humanise(s)}
                </option>
              ))}
            </NFSelect>
          </NFField>
          <NFField
            label="When"
            htmlFor="i-when"
            required
            hint="When it happened, not when you are writing it up."
          >
            <NFInput
              id="i-when"
              type="datetime-local"
              value={occurredAt}
              onChange={(e) => setOccurredAt(e.target.value)}
            />
          </NFField>
          <NFField label="Where" htmlFor="i-loc" hint="Optional">
            <NFInput
              id="i-loc"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder="Main gate"
            />
          </NFField>
        </div>
      </div>
    </NFDialog>
  );
}

function ResolveDialog({
  incident,
  onClose,
  onSaved,
}: {
  incident: SecurityIncident;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [status, setStatus] = React.useState<IncidentStatus>(incident.status);
  const [action, setAction] = React.useState(incident.action_taken ?? "");
  const [reference, setReference] = React.useState(incident.police_reference ?? "");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  return (
    <NFDialog
      open
      onOpenChange={(open) => !open && onClose()}
      title={incident.title}
      description={`Reported by ${incident.reported_by_name} · ${formatDateTime(incident.occurred_at)}`}
      footer={
        <div className="flex justify-end gap-2">
          <NFButton variant="secondary" onClick={onClose}>
            Cancel
          </NFButton>
          <NFButton
            loading={saving}
            onClick={async () => {
              setSaving(true);
              setError(null);
              try {
                await api.patch(`/security/incidents/${incident.id}`, {
                  status,
                  action_taken: action || null,
                  police_reference: reference || null,
                });
                onSaved();
              } catch (e) {
                setError(e instanceof ApiError ? e.message : "Could not update this.");
              } finally {
                setSaving(false);
              }
            }}
          >
            Save
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
        <p className="whitespace-pre-wrap text-sm text-[var(--nf-text)]">
          {incident.description}
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          <NFField label="Status" htmlFor="r-status">
            <NFSelect
              id="r-status"
              value={status}
              onChange={(e) => setStatus(e.target.value as IncidentStatus)}
            >
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {humanise(s)}
                </option>
              ))}
            </NFSelect>
          </NFField>
          <NFField label="Police reference" htmlFor="r-ref" hint="Optional">
            <NFInput
              id="r-ref"
              value={reference}
              onChange={(e) => setReference(e.target.value)}
            />
          </NFField>
        </div>
        <NFField label="What was done about it?" htmlFor="r-action">
          <NFTextarea
            id="r-action"
            rows={3}
            value={action}
            onChange={(e) => setAction(e.target.value)}
          />
        </NFField>
      </div>
    </NFDialog>
  );
}
