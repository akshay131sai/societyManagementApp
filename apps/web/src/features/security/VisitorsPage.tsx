/**
 * Visitors â€” the gate log, and the approvals behind it.
 *
 * Two people use this screen and want opposite things from it.
 *
 * - **A guard** is standing at a barrier with someone waiting. The first thing
 *   on their screen is the pass-code box, because typing six characters is
 *   faster than finding a name in a list, and the second is the "at the gate"
 *   queue of people waiting on a decision.
 * - **A resident** wants to pre-approve tomorrow's plumber and see who came to
 *   their flat. They never see a neighbour's visitors â€” the API scopes them
 *   out, and a direct id returns 404 rather than 403.
 *
 * The status flow is the server's; this screen renders the buttons its rules
 * allow and nothing else.
 */

import {
  Check,
  DoorOpen,
  LogOut,
  Phone,
  Plus,
  ShieldQuestion,
  Ticket,
  UserRoundCheck,
  X,
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
  Flat,
  FlatDetail,
  Visitor,
  VisitorStatus,
  VisitorSummary,
  VisitorType,
} from "@/types";
import { formatDateTime, formatRelative } from "@/utils/format";
import { hasPermission } from "@/utils/permissions";

const LIMIT = 20;

const STATUS_TONE: Record<VisitorStatus, BadgeTone> = {
  EXPECTED: "info",
  AWAITING_APPROVAL: "warning",
  APPROVED: "primary",
  DENIED: "danger",
  CHECKED_IN: "success",
  CHECKED_OUT: "neutral",
  EXPIRED: "neutral",
};

const TYPES: { value: VisitorType; label: string }[] = [
  { value: "GUEST", label: "Guest" },
  { value: "DELIVERY", label: "Delivery" },
  { value: "CAB", label: "Cab" },
  { value: "SERVICE", label: "Service â€” plumber, electrician" },
  { value: "DOMESTIC_HELP", label: "Domestic help" },
  { value: "VENDOR", label: "Vendor" },
  { value: "OTHER", label: "Other" },
];

/** `datetime-local` wants `YYYY-MM-DDTHH:mm` in *local* time, not an ISO UTC. */
function localInput(offsetHours: number): string {
  const d = new Date(Date.now() + offsetHours * 3_600_000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function VisitorsPage() {
  const principal = useAppSelector((s) => s.auth.principal);
  const isGuard = hasPermission(principal, "security.read");
  const canApprove = hasPermission(principal, "visitor.approve");
  const canCreate = hasPermission(principal, "visitor.create");

  const [page, setPage] = React.useState(1);
  const [q, setQ] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [rows, setRows] = React.useState<Page<Visitor> | null>(null);
  const [summary, setSummary] = React.useState<VisitorSummary | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [preApproving, setPreApproving] = React.useState(false);
  const [logging, setLogging] = React.useState(false);
  const [deciding, setDeciding] = React.useState<Visitor | null>(null);
  const [calling, setCalling] = React.useState<Visitor | null>(null);
  const [code, setCode] = React.useState("");
  const [codeError, setCodeError] = React.useState<string | null>(null);
  const [codeBusy, setCodeBusy] = React.useState(false);
  const [reload, setReload] = React.useState(0);

  React.useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    api
      .get<Page<Visitor>>(
        "/visitors",
        { page, limit: LIMIT, q: q || undefined, status: status || undefined },
        controller.signal,
      )
      .then(setRows)
      .catch(() => undefined)
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [page, q, status, reload]);

  React.useEffect(() => {
    if (!isGuard) return;
    const controller = new AbortController();
    api
      .get<VisitorSummary>("/visitors/summary", undefined, controller.signal)
      .then(setSummary)
      .catch(() => undefined);
    return () => controller.abort();
  }, [isGuard, reload]);

  async function act(request: Promise<unknown>) {
    try {
      await request;
      setReload((n) => n + 1);
    } catch {
      /* The row keeps its old state; the list refresh will show the truth. */
    }
  }

  async function checkInByCode() {
    setCodeBusy(true);
    setCodeError(null);
    try {
      await api.post("/visitors/check-in", { pass_code: code.trim().toUpperCase() });
      setCode("");
      setReload((n) => n + 1);
    } catch (e) {
      setCodeError(e instanceof ApiError ? e.message : "That code did not work.");
    } finally {
      setCodeBusy(false);
    }
  }

  const columns: Column<Visitor>[] = [
    {
      key: "visitor",
      header: "Visitor",
      render: (v) => (
        <div className="min-w-0">
          <p className="truncate font-medium text-[var(--nf-text)]">{v.visitor_name}</p>
          <p className="mt-0.5 truncate text-[11px] text-[var(--nf-text-subtle)]">
            {[
              TYPES.find((t) => t.value === v.visitor_type)?.label.split(" â€” ")[0],
              v.company,
              v.accompanying_count > 0 ? `+${v.accompanying_count}` : null,
            ]
              .filter(Boolean)
              .join(" Â· ")}
          </p>
        </div>
      ),
    },
    { key: "flat", header: "Flat", render: (v) => v.flat_number ?? "â€”" },
    {
      key: "pass",
      header: "Pass",
      hideOnMobile: true,
      render: (v) =>
        v.pass_code ? (
          <span className="font-mono text-[13px] tracking-wider">{v.pass_code}</span>
        ) : (
          "â€”"
        ),
    },
    {
      key: "status",
      header: "Status",
      render: (v) => (
        <div>
          <NFStatusBadge status={v.status} tone={STATUS_TONE[v.status]} />
          {v.approved_via === "PHONE" && v.confirmed_with && (
            <p className="mt-1 text-[11px] text-[var(--nf-text-subtle)]">
              By phone Â· {v.confirmed_with}
            </p>
          )}
          {v.approved_via === "GUARD" && (
            <p className="mt-1 text-[11px] text-[var(--nf-text-subtle)]">By security</p>
          )}
        </div>
      ),
    },
    {
      key: "when",
      header: "When",
      hideOnMobile: true,
      render: (v) => {
        if (v.checked_out_at)
          return `Left ${formatRelative(v.checked_out_at)}${
            v.duration_minutes !== null ? ` Â· ${v.duration_minutes} min` : ""
          }`;
        if (v.checked_in_at) return `In since ${formatRelative(v.checked_in_at)}`;
        if (v.expected_from) return `Expected ${formatDateTime(v.expected_from)}`;
        return formatRelative(v.created_at);
      },
    },
    {
      key: "actions",
      header: "",
      className: "text-right",
      render: (v) => (
        <div className="flex justify-end gap-1.5">
          {canApprove && v.status === "AWAITING_APPROVAL" && (
            <>
              <NFButton
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  act(api.post(`/visitors/${v.id}/decision`, { approved: true }));
                }}
              >
                <Check /> Allow
              </NFButton>
              <NFButton
                size="sm"
                variant="secondary"
                onClick={(e) => {
                  e.stopPropagation();
                  setDeciding(v);
                }}
              >
                <X /> Deny
              </NFButton>
            </>
          )}
          {isGuard && !canApprove && v.status === "AWAITING_APPROVAL" && (
            <NFButton
              size="sm"
              variant="secondary"
              onClick={(e) => {
                e.stopPropagation();
                setCalling(v);
              }}
            >
              <Phone /> Call flat
            </NFButton>
          )}
          {isGuard && (v.status === "APPROVED" || v.status === "EXPECTED") && (
            <NFButton
              size="sm"
              onClick={(e) => {
                e.stopPropagation();
                act(api.post(`/visitors/${v.id}/check-in`, {}));
              }}
            >
              <DoorOpen /> Check in
            </NFButton>
          )}
          {isGuard && v.status === "CHECKED_IN" && (
            <NFButton
              size="sm"
              variant="secondary"
              onClick={(e) => {
                e.stopPropagation();
                act(api.post(`/visitors/${v.id}/check-out`));
              }}
            >
              <LogOut /> Check out
            </NFButton>
          )}
        </div>
      ),
    },
  ];

  return (
    <>
      <NFPageHeader
        title="Visitors"
        description={
          isGuard
            ? "The gate log. Nobody is admitted until the flat says yes â€” in the app, by a pre-approval, or on a call you record here."
            : "People expected at your flat, and everyone who has come to it."
        }
        actions={
          canCreate ? (
            <div className="flex gap-2">
              {isGuard && (
                <NFButton variant="secondary" onClick={() => setLogging(true)}>
                  <Plus /> Log at gate
                </NFButton>
              )}
              {/* Pre-approval is the flat's promise, not the gate's â€” and the
                  dialog has no flat picker, so a guard could not use it anyway. */}
              {!isGuard && (
                <NFButton onClick={() => setPreApproving(true)}>
                  <Ticket /> Pre-approve
                </NFButton>
              )}
            </div>
          ) : undefined
        }
      />

      {isGuard && (
        <>
          <NFCard className="mb-6 p-5">
            <div className="flex flex-wrap items-end gap-3">
              <div className="min-w-0 flex-1">
                <NFField
                  label="Pass code"
                  htmlFor="gate-code"
                  hint="Six characters, read out by the visitor at the barrier."
                >
                  <NFInput
                    id="gate-code"
                    value={code}
                    onChange={(e) => setCode(e.target.value.toUpperCase())}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && code.trim()) void checkInByCode();
                    }}
                    placeholder="7K4M2P"
                    autoComplete="off"
                    className="font-mono tracking-[0.3em]"
                  />
                </NFField>
              </div>
              <NFButton onClick={checkInByCode} loading={codeBusy} disabled={!code.trim()}>
                <DoorOpen /> Check in
              </NFButton>
            </div>
            {codeError && (
              <p role="alert" className="mt-2 text-[13px] text-[var(--nf-danger)]">
                {codeError}
              </p>
            )}
          </NFCard>

          {summary && (
            <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <NFStatCard
                label="On the premises"
                value={summary.on_premises}
                icon={<UserRoundCheck />}
                tone="success"
              />
              <NFStatCard
                label="Waiting at the gate"
                value={summary.awaiting_approval}
                icon={<ShieldQuestion />}
                tone={summary.awaiting_approval > 0 ? "warning" : "info"}
                hint="The flat has not answered yet"
              />
              <NFStatCard
                label="Expected today"
                value={summary.expected_today}
                icon={<Ticket />}
                tone="info"
              />
              <NFStatCard
                label="Entries today"
                value={summary.entries_today}
                icon={<DoorOpen />}
                tone="primary"
                hint={summary.denied_today > 0 ? `${summary.denied_today} turned away` : undefined}
              />
            </div>
          )}
        </>
      )}

      <NFCard>
        <NFCardHeader
          title="Gate log"
          action={
            <div className="flex flex-wrap items-center gap-2">
              <NFSearch
                value={q}
                onChange={(value) => {
                  setQ(value);
                  setPage(1);
                }}
                placeholder="Name, vehicle or pass"
              />
              <NFSelect
                aria-label="Status"
                value={status}
                onChange={(e) => {
                  setStatus(e.target.value);
                  setPage(1);
                }}
                className="sm:w-44"
              >
                <option value="">Everyone</option>
                <option value="AWAITING_APPROVAL">Waiting at the gate</option>
                <option value="CHECKED_IN">On the premises</option>
                <option value="EXPECTED">Expected</option>
                <option value="CHECKED_OUT">Left</option>
                <option value="DENIED">Turned away</option>
              </NFSelect>
            </div>
          }
        />
        <NFCardBody className="px-0 pb-0">
          <NFDataTable
            caption="Visitors"
            columns={columns}
            rows={rows?.items ?? []}
            rowKey={(v) => v.id}
            loading={loading}
            empty={
              <div className="px-5 pb-5">
                <NFEmptyState
                  icon={<UserRoundCheck />}
                  title="Nobody yet"
                  description={
                    canCreate
                      ? "Pre-approve a visitor and share the pass code with them."
                      : "No visitors match this filter."
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

      <PreApproveDialog
        open={preApproving}
        onOpenChange={setPreApproving}
        onSaved={() => {
          setPreApproving(false);
          setReload((n) => n + 1);
        }}
      />

      {isGuard && (
        <GateEntryDialog
          open={logging}
          onOpenChange={setLogging}
          onSaved={() => {
            setLogging(false);
            setReload((n) => n + 1);
          }}
        />
      )}

      {calling && (
        <CallFlatDialog
          visitor={calling}
          onClose={() => setCalling(null)}
          onSaved={() => {
            setCalling(null);
            setReload((n) => n + 1);
          }}
        />
      )}

      {deciding && (
        <DenyDialog
          visitor={deciding}
          onClose={() => setDeciding(null)}
          onSaved={() => {
            setDeciding(null);
            setReload((n) => n + 1);
          }}
        />
      )}
    </>
  );
}

/* -------------------------------------------------------------------------- */

function PreApproveDialog({
  open,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}) {
  const [name, setName] = React.useState("");
  const [type, setType] = React.useState<VisitorType>("GUEST");
  const [from, setFrom] = React.useState(() => localInput(0));
  const [to, setTo] = React.useState(() => localInput(4));
  const [phone, setPhone] = React.useState("");
  const [company, setCompany] = React.useState("");
  const [purpose, setPurpose] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [issued, setIssued] = React.useState<Visitor | null>(null);
  const codeless = type === "DELIVERY" || type === "CAB";

  React.useEffect(() => {
    if (!open) return;
    setName("");
    setPhone("");
    setCompany("");
    setPurpose("");
    setFrom(localInput(0));
    setTo(localInput(4));
    setError(null);
    setIssued(null);
  }, [open]);

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      const visitor = await api.post<Visitor>("/visitors/pre-approvals", {
        visitor_name: name,
        visitor_type: type,
        expected_from: new Date(from).toISOString(),
        expected_to: new Date(to).toISOString(),
        visitor_phone: phone || null,
        company: company.trim() || null,
        purpose: purpose || null,
      });
      setIssued(visitor);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not create this pass.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <NFDialog
      open={open}
      onOpenChange={(next) => {
        if (!next && issued) onSaved();
        else onOpenChange(next);
      }}
      title={issued ? "Pass created" : "Pre-approve a visitor"}
      description={
        issued
          ? "Share this code with your visitor. The guard types it at the gate."
          : "They walk straight in during the window you choose."
      }
      footer={
        issued ? (
          <NFButton onClick={onSaved}>Done</NFButton>
        ) : (
          <div className="flex justify-end gap-2">
            <NFButton variant="secondary" onClick={() => onOpenChange(false)}>
              Cancel
            </NFButton>
            <NFButton onClick={submit} loading={saving} disabled={!name.trim()}>
              Create pass
            </NFButton>
          </div>
        )
      }
    >
      {issued ? (
        <div className="py-4 text-center">
          <p className="font-mono text-4xl font-bold tracking-[0.35em] text-[var(--nf-primary)]">
            {issued.pass_code}
          </p>
          <p className="mt-3 text-[13px] text-[var(--nf-text-muted)]">
            {issued.visitor_name} Â· valid until {formatDateTime(issued.expected_to)}
          </p>
          {(issued.visitor_type === "DELIVERY" || issued.visitor_type === "CAB") && (
            <p className="mt-2 text-[13px] text-[var(--nf-text-muted)]">
              No need to share the code â€” security will let{" "}
              {issued.company ? `the ${issued.company} rider` : "them"} up when they arrive in
              this window.
            </p>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          {error && (
            <p
              role="alert"
              className="rounded-[var(--nf-radius-sm)] border border-[var(--nf-danger)]/30 bg-[var(--nf-danger-subtle)] px-3 py-2 text-[13px] text-[var(--nf-danger)]"
            >
              {error}
            </p>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <NFField label="Who is coming?" htmlFor="v-name" required>
              <NFInput
                id="v-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={codeless ? "Food order, parcelâ€¦" : undefined}
                autoFocus
              />
            </NFField>
            <NFField label="Why?" htmlFor="v-type">
              <NFSelect
                id="v-type"
                value={type}
                onChange={(e) => setType(e.target.value as VisitorType)}
              >
                {TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </NFSelect>
            </NFField>
          </div>
          {codeless && (
            <NFField
              label="Company"
              htmlFor="v-company"
              hint="Optional. If you name one, only that company is let in â€” leave blank for any."
            >
              <NFInput
                id="v-company"
                value={company}
                onChange={(e) => setCompany(e.target.value)}
                placeholder="Swiggy, Zomato, Amazonâ€¦"
              />
            </NFField>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <NFField label="From" htmlFor="v-from" required>
              <NFInput
                id="v-from"
                type="datetime-local"
                value={from}
                onChange={(e) => setFrom(e.target.value)}
              />
            </NFField>
            <NFField
              label="Until"
              htmlFor="v-to"
              required
              hint="The pass stops working after this."
            >
              <NFInput
                id="v-to"
                type="datetime-local"
                value={to}
                onChange={(e) => setTo(e.target.value)}
              />
            </NFField>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <NFField label="Their phone" htmlFor="v-phone" hint="Optional">
              <NFInput
                id="v-phone"
                inputMode="numeric"
                maxLength={10}
                value={phone}
                onChange={(e) => setPhone(e.target.value.replace(/\D/g, ""))}
              />
            </NFField>
            <NFField label="Note for the gate" htmlFor="v-purpose" hint="Optional">
              <NFInput
                id="v-purpose"
                value={purpose}
                onChange={(e) => setPurpose(e.target.value)}
              />
            </NFField>
          </div>
        </div>
      )}
    </NFDialog>
  );
}

function GateEntryDialog({
  open,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}) {
  const [flats, setFlats] = React.useState<Flat[]>([]);
  const [flatId, setFlatId] = React.useState("");
  const [name, setName] = React.useState("");
  const [type, setType] = React.useState<VisitorType>("DELIVERY");
  const [company, setCompany] = React.useState("");
  const [phone, setPhone] = React.useState("");
  const [vehicle, setVehicle] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  /** Set when the flat had already pre-approved this delivery or cab. */
  const [preApproved, setPreApproved] = React.useState<Visitor | null>(null);

  React.useEffect(() => {
    if (!open) return;
    setName("");
    setCompany("");
    setPhone("");
    setVehicle("");
    setError(null);
    setPreApproved(null);
    const controller = new AbortController();
    api
      .get<Page<Flat>>("/flats", { limit: 100 }, controller.signal)
      .then((r) => {
        setFlats(r.items);
        setFlatId((current) => current || r.items[0]?.id || "");
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [open]);

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      const visitor = await api.post<Visitor>("/visitors/gate-entries", {
        flat_id: flatId,
        visitor_name: name,
        visitor_type: type,
        company: company.trim() || null,
        visitor_phone: phone || null,
        vehicle_number: vehicle || null,
      });
      if (visitor.status === "APPROVED") setPreApproved(visitor);
      else onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not log this visitor.");
    } finally {
      setSaving(false);
    }
  }

  async function checkInNow() {
    if (!preApproved) return;
    setSaving(true);
    setError(null);
    try {
      await api.post(`/visitors/${preApproved.id}/check-in`, {});
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not check this visitor in.");
    } finally {
      setSaving(false);
    }
  }

  const errorBox = error && (
    <p
      role="alert"
      className="rounded-[var(--nf-radius-sm)] border border-[var(--nf-danger)]/30 bg-[var(--nf-danger-subtle)] px-3 py-2 text-[13px] text-[var(--nf-danger)]"
    >
      {error}
    </p>
  );

  if (preApproved) {
    return (
      <NFDialog
        open={open}
        onOpenChange={(next) => (next ? onOpenChange(next) : onSaved())}
        title="Already approved by the flat"
        description={`${preApproved.flat_number ?? "The flat"} pre-approved this ${
          TYPES.find((t) => t.value === preApproved.visitor_type)?.label.toLowerCase() ??
          "visitor"
        }. No need to call.`}
        footer={
          <div className="flex justify-end gap-2">
            <NFButton variant="secondary" onClick={onSaved}>
              Later
            </NFButton>
            <NFButton onClick={checkInNow} loading={saving}>
              <DoorOpen /> Check in now
            </NFButton>
          </div>
        }
      >
        <div className="space-y-3">
          {errorBox}
          <p className="text-[14px] font-medium text-[var(--nf-text)]">
            {preApproved.visitor_name}
            {preApproved.company ? ` Â· ${preApproved.company}` : ""}
          </p>
          {preApproved.notes && (
            <p className="whitespace-pre-line text-[13px] text-[var(--nf-text-muted)]">
              {preApproved.notes}
            </p>
          )}
          {preApproved.expected_to && (
            <p className="text-[12px] text-[var(--nf-text-subtle)]">
              Approval valid until {formatDateTime(preApproved.expected_to)}
            </p>
          )}
        </div>
      </NFDialog>
    );
  }

  return (
    <NFDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Log a visitor at the gate"
      description="If the flat pre-approved this delivery or cab, they go straight in. Otherwise the flat is asked, and nobody is admitted before they say yes."
      footer={
        <div className="flex justify-end gap-2">
          <NFButton variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </NFButton>
          <NFButton onClick={submit} loading={saving} disabled={!flatId || !name.trim()}>
            Ask the flat
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
        <div className="grid gap-4 sm:grid-cols-2">
          <NFField label="Visiting which flat?" htmlFor="g-flat" required>
            <NFSelect id="g-flat" value={flatId} onChange={(e) => setFlatId(e.target.value)}>
              {flats.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.flat_number}
                </option>
              ))}
            </NFSelect>
          </NFField>
          <NFField label="Name" htmlFor="g-name" required>
            <NFInput
              id="g-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
            />
          </NFField>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <NFField label="Type" htmlFor="g-type">
            <NFSelect
              id="g-type"
              value={type}
              onChange={(e) => setType(e.target.value as VisitorType)}
            >
              {TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </NFSelect>
          </NFField>
          <NFField
            label="Company"
            htmlFor="g-company"
            hint={type === "DELIVERY" || type === "CAB" ? "Swiggy, Amazon, Uberâ€¦" : "Optional"}
          >
            <NFInput
              id="g-company"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
            />
          </NFField>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <NFField label="Their phone" htmlFor="g-phone" hint="Optional">
            <NFInput
              id="g-phone"
              inputMode="numeric"
              maxLength={10}
              value={phone}
              onChange={(e) => setPhone(e.target.value.replace(/\D/g, ""))}
            />
          </NFField>
          <NFField label="Vehicle" htmlFor="g-veh" hint="Optional">
            <NFInput
              id="g-veh"
              value={vehicle}
              onChange={(e) => setVehicle(e.target.value.toUpperCase())}
              placeholder="MH 12 AB 1234"
            />
          </NFField>
        </div>
      </div>
    </NFDialog>
  );
}

/**
 * The flat has not answered in the app â€” at midnight, nobody is looking at
 * their phone's notifications. The guard rings them, and records what they
 * said. Admitting needs the name of whoever said yes; the flat is told either
 * way, so a "yes" nobody gave is noticed.
 */
function CallFlatDialog({
  visitor,
  onClose,
  onSaved,
}: {
  visitor: Visitor;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [flat, setFlat] = React.useState<FlatDetail | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [answeredBy, setAnsweredBy] = React.useState("");
  const [reason, setReason] = React.useState("");
  const [mode, setMode] = React.useState<"call" | "deny">("call");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    const controller = new AbortController();
    api
      .get<FlatDetail>(`/flats/${visitor.flat_id}`, undefined, controller.signal)
      .then((f) => {
        setFlat(f);
        const first = f.residents.find((r) => r.is_primary) ?? f.residents[0];
        if (first) setAnsweredBy(first.full_name);
      })
      .catch(() => undefined)
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [visitor.flat_id]);

  async function decide(approved: boolean) {
    setSaving(true);
    setError(null);
    try {
      await api.post(`/visitors/${visitor.id}/guard-decision`, {
        approved,
        confirmed_with: answeredBy.trim() || null,
        reason: approved ? null : reason,
      });
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not record this decision.");
    } finally {
      setSaving(false);
    }
  }

  const reachable = flat?.residents.filter((r) => r.phone) ?? [];

  return (
    <NFDialog
      open
      onOpenChange={(open) => !open && onClose()}
      title={`Call ${visitor.flat_number ?? "the flat"} about ${visitor.visitor_name}`}
      description="Admit them only if someone in the flat says yes. If nobody answers, they wait or are turned away."
      footer={
        mode === "call" ? (
          <div className="flex flex-wrap justify-end gap-2">
            <NFButton variant="secondary" onClick={() => setMode("deny")}>
              <X /> Turn away
            </NFButton>
            <NFButton
              onClick={() => decide(true)}
              loading={saving}
              disabled={!answeredBy.trim()}
            >
              <Check /> They said yes
            </NFButton>
          </div>
        ) : (
          <div className="flex justify-end gap-2">
            <NFButton variant="secondary" onClick={() => setMode("call")}>
              Back
            </NFButton>
            <NFButton
              variant="danger"
              onClick={() => decide(false)}
              loading={saving}
              disabled={!reason.trim()}
            >
              Turn away
            </NFButton>
          </div>
        )
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

        {loading ? (
          <p className="text-[13px] text-[var(--nf-text-muted)]">Loading the flat's contactsâ€¦</p>
        ) : reachable.length === 0 ? (
          <p className="rounded-[var(--nf-radius-sm)] border border-[var(--nf-warning)]/30 bg-[var(--nf-warning-subtle)] px-3 py-2 text-[13px] text-[var(--nf-text)]">
            No phone number is on record for this flat. Do not admit the visitor â€” ask the
            society office to add one.
          </p>
        ) : (
          <ul className="divide-y divide-[var(--nf-border)] rounded-[var(--nf-radius)] border border-[var(--nf-border)]">
            {reachable.map((r) => (
              <li key={r.id} className="flex items-center justify-between gap-3 px-3 py-2.5">
                <div className="min-w-0">
                  <p className="truncate text-[14px] font-medium text-[var(--nf-text)]">
                    {r.full_name}
                  </p>
                  <p className="text-[12px] text-[var(--nf-text-subtle)]">
                    {r.resident_type.replace(/_/g, " ").toLowerCase()}
                    {r.is_primary ? " Â· primary" : ""}
                  </p>
                </div>
                <a
                  href={`tel:+91${r.phone}`}
                  className="inline-flex shrink-0 items-center gap-1.5 rounded-[var(--nf-radius-sm)] border border-[var(--nf-border)] px-3 py-1.5 font-mono text-[13px] text-[var(--nf-primary)] hover:border-[var(--nf-primary)]"
                >
                  <Phone className="size-3.5" aria-hidden /> {r.phone}
                </a>
              </li>
            ))}
          </ul>
        )}

        {mode === "call" ? (
          <NFField
            label="Who said yes?"
            htmlFor="c-who"
            required
            hint="The flat is told who approved, so a yes nobody gave gets noticed."
          >
            <NFInput
              id="c-who"
              list="c-who-options"
              value={answeredBy}
              onChange={(e) => setAnsweredBy(e.target.value)}
            />
            <datalist id="c-who-options">
              {flat?.residents.map((r) => <option key={r.id} value={r.full_name} />)}
            </datalist>
          </NFField>
        ) : (
          <NFField
            label="Why are they being turned away?"
            htmlFor="c-reason"
            required
            hint="For example: the flat said no, or nobody answered."
          >
            <NFTextarea
              id="c-reason"
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              autoFocus
            />
          </NFField>
        )}
      </div>
    </NFDialog>
  );
}

function DenyDialog({
  visitor,
  onClose,
  onSaved,
}: {
  visitor: Visitor;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [reason, setReason] = React.useState("");
  const [saving, setSaving] = React.useState(false);

  return (
    <NFDialog
      open
      onOpenChange={(open) => !open && onClose()}
      title={`Turn away ${visitor.visitor_name}?`}
      size="sm"
      footer={
        <div className="flex justify-end gap-2">
          <NFButton variant="secondary" onClick={onClose}>
            Cancel
          </NFButton>
          <NFButton
            variant="danger"
            loading={saving}
            disabled={!reason.trim()}
            onClick={async () => {
              setSaving(true);
              try {
                await api.post(`/visitors/${visitor.id}/decision`, {
                  approved: false,
                  reason,
                });
                onSaved();
              } finally {
                setSaving(false);
              }
            }}
          >
            Turn away
          </NFButton>
        </div>
      }
    >
      <NFField
        label="Why?"
        htmlFor="d-reason"
        required
        hint="The guard sees this, and it stays on the gate log."
      >
        <NFTextarea
          id="d-reason"
          rows={3}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          autoFocus
        />
      </NFField>
    </NFDialog>
  );
}
