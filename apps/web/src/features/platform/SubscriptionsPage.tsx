import { CalendarPlus, CreditCard, Plus, ShieldOff } from "lucide-react";
import * as React from "react";

import { NFDataTable, NFDialog, type Column } from "@/components/nestflow/data";
import {
  NFButton,
  NFCard,
  NFEmptyState,
  NFField,
  NFInput,
  NFPageHeader,
  NFSelect,
  NFStatusBadge,
  NFTextarea,
} from "@/components/nestflow/primitives";
import { ApiError, api, type Page } from "@/services/api";
import type { Society, Subscription, SubscriptionPlan, SubscriptionStatus } from "@/types";
import { formatCurrency, formatDate, formatNumber } from "@/utils/format";

type Mode = "assign" | "extend" | "suspend" | null;

const ASSIGN_STATUSES: SubscriptionStatus[] = ["ACTIVE", "TRIAL"];

/** Days between today and an ISO date, floored at zero. */
function daysLeft(endDate: string): number {
  const end = new Date(`${endDate}T00:00:00`);
  const diff = Math.ceil((end.getTime() - Date.now()) / 86_400_000);
  return Math.max(diff, 0);
}

export default function SubscriptionsPage() {
  const [societies, setSocieties] = React.useState<Society[]>([]);
  const [societyId, setSocietyId] = React.useState("");
  const [plans, setPlans] = React.useState<SubscriptionPlan[]>([]);

  const [rows, setRows] = React.useState<Subscription[] | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const [mode, setMode] = React.useState<Mode>(null);
  const [target, setTarget] = React.useState<Subscription | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [formError, setFormError] = React.useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});

  // Assign form
  const [planId, setPlanId] = React.useState("");
  const [status, setStatus] = React.useState<SubscriptionStatus>("ACTIVE");
  const [startDate, setStartDate] = React.useState("");
  const [endDate, setEndDate] = React.useState("");
  const [notes, setNotes] = React.useState("");
  // Extend / suspend
  const [extendDays, setExtendDays] = React.useState("365");
  const [newEndDate, setNewEndDate] = React.useState("");
  const [reason, setReason] = React.useState("");

  // Societies and plans are the pickers for every action here, so both load once.
  React.useEffect(() => {
    void (async () => {
      try {
        const [socs, pl] = await Promise.all([
          api.get<Page<Society>>("/platform/societies", { page: 1, limit: 100 }),
          api.get<SubscriptionPlan[]>("/platform/plans", { active_only: true }),
        ]);
        setSocieties(socs.items);
        setPlans(pl);
        if (socs.items.length > 0) setSocietyId((cur) => cur || socs.items[0].id);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Could not load societies.");
      }
    })();
  }, []);

  const load = React.useCallback(async () => {
    if (!societyId) return;
    setLoading(true);
    try {
      setRows(await api.get<Subscription[]>("/platform/subscriptions", { society_id: societyId }));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load subscriptions.");
      setRows(null);
    } finally {
      setLoading(false);
    }
  }, [societyId]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const society = societies.find((s) => s.id === societyId) ?? null;
  const current = rows?.find((r) => r.is_current) ?? null;

  function openAssign() {
    setTarget(null);
    setPlanId(plans[0]?.id ?? "");
    setStatus("ACTIVE");
    setStartDate("");
    setEndDate("");
    setNotes("");
    setFormError(null);
    setFieldErrors({});
    setMode("assign");
  }

  function openExtend(sub: Subscription) {
    setTarget(sub);
    setExtendDays("365");
    setNewEndDate("");
    setNotes("");
    setFormError(null);
    setFieldErrors({});
    setMode("extend");
  }

  function openSuspend(sub: Subscription) {
    setTarget(sub);
    setReason("");
    setFormError(null);
    setFieldErrors({});
    setMode("suspend");
  }

  async function submit() {
    setBusy(true);
    setFormError(null);
    setFieldErrors({});
    try {
      if (mode === "assign") {
        await api.post("/platform/subscriptions", {
          society_id: societyId,
          plan_id: planId,
          status,
          start_date: startDate || null,
          end_date: endDate || null,
          notes: notes.trim() || null,
        });
      } else if (mode === "extend" && target) {
        // An explicit end date wins; otherwise roll forward by day count.
        await api.post(`/platform/subscriptions/${target.id}/extend`, {
          days: newEndDate ? null : Number(extendDays || 0),
          new_end_date: newEndDate || null,
          notes: notes.trim() || null,
        });
      } else if (mode === "suspend" && target) {
        await api.post(
          `/platform/subscriptions/${target.id}/suspend`,
          undefined,
          reason.trim() ? { reason: reason.trim() } : undefined,
        );
      }
      setMode(null);
      await load();
    } catch (e) {
      if (e instanceof ApiError) {
        setFieldErrors(e.fieldErrors);
        setFormError(e.message);
      } else {
        setFormError("That action could not be completed.");
      }
    } finally {
      setBusy(false);
    }
  }

  const columns: Column<Subscription>[] = [
    {
      key: "plan",
      header: "Plan",
      render: (s) => (
        <div className="min-w-0">
          <p className="truncate font-medium text-[var(--nf-text)]">
            {s.plan_name ?? "Unknown plan"}
          </p>
          <p className="truncate text-xs text-[var(--nf-text-muted)]">
            {s.is_current ? "Current" : "Superseded"}
          </p>
        </div>
      ),
    },
    { key: "status", header: "Status", render: (s) => <NFStatusBadge status={s.status} /> },
    {
      key: "term",
      header: "Term",
      render: (s) => (
        <span className="text-[var(--nf-text-muted)] tabular-nums">
          {formatDate(s.start_date)} → {formatDate(s.end_date)}
        </span>
      ),
    },
    {
      key: "remaining",
      header: "Remaining",
      hideOnMobile: true,
      className: "tabular-nums",
      render: (s) =>
        s.is_current ? (
          <span
            className="font-medium"
            style={{
              color: daysLeft(s.end_date) <= 30 ? "var(--nf-danger)" : "var(--nf-text)",
            }}
          >
            {daysLeft(s.end_date)} days
          </span>
        ) : (
          <span className="text-[var(--nf-text-subtle)]">—</span>
        ),
    },
    {
      key: "price",
      header: "Sold at",
      hideOnMobile: true,
      className: "tabular-nums",
      render: (s) => (
        <div>
          <span className="text-[var(--nf-text)]">{formatCurrency(s.price_snapshot)}</span>
          <span className="ml-1 text-xs text-[var(--nf-text-muted)]">
            {s.max_flats_snapshot ? `· ${formatNumber(s.max_flats_snapshot)} flats` : "· unlimited"}
          </span>
        </div>
      ),
    },
    {
      key: "actions",
      header: "",
      render: (s) =>
        s.is_current ? (
          <div className="flex justify-end gap-1">
            <NFButton variant="ghost" size="sm" onClick={() => openExtend(s)}>
              <CalendarPlus /> Extend
            </NFButton>
            {s.status !== "SUSPENDED" && (
              <NFButton variant="ghost" size="sm" onClick={() => openSuspend(s)}>
                <ShieldOff /> Suspend
              </NFButton>
            )}
          </div>
        ) : null,
    },
  ];

  const dialogTitle =
    mode === "assign"
      ? `Assign a subscription${society ? ` to ${society.name}` : ""}`
      : mode === "extend"
        ? "Extend subscription"
        : "Suspend subscription";

  return (
    <>
      <NFPageHeader
        title="Subscriptions"
        description="One society's billing term at a time. Assigning a new subscription supersedes the current one and snapshots the plan's price."
        actions={
          <NFButton onClick={openAssign} disabled={!societyId || plans.length === 0}>
            <Plus /> Assign subscription
          </NFButton>
        }
      />

      {error && (
        <div
          role="alert"
          className="mb-4 rounded-[var(--nf-radius-sm)] border border-[var(--nf-danger)]/25 bg-[var(--nf-danger-subtle)] px-4 py-3 text-sm text-[var(--nf-danger)]"
        >
          {error}
        </div>
      )}

      <NFCard>
        <div className="flex flex-wrap items-center gap-3 border-b border-[var(--nf-border)] p-4">
          <NFField label="Society" htmlFor="sub-society" className="min-w-0 flex-1 sm:max-w-sm">
            <NFSelect
              id="sub-society"
              value={societyId}
              onChange={(e) => setSocietyId(e.target.value)}
            >
              {societies.length === 0 && <option value="">No societies</option>}
              {societies.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} — {s.city}
                </option>
              ))}
            </NFSelect>
          </NFField>

          {current && (
            <div className="text-[13px] text-[var(--nf-text-muted)]">
              <span className="font-medium text-[var(--nf-text)]">{current.plan_name}</span> ·{" "}
              {daysLeft(current.end_date)} days remaining
            </div>
          )}
        </div>

        <NFDataTable
          caption="Subscription history for the selected society"
          columns={columns}
          rows={rows ?? []}
          rowKey={(s) => s.id}
          loading={loading}
          empty={
            <NFEmptyState
              icon={<CreditCard />}
              title="No subscriptions for this society"
              description="Assign one to start the billing term. Provisioning normally creates a trial automatically."
              action={
                <NFButton onClick={openAssign} disabled={plans.length === 0}>
                  <Plus /> Assign subscription
                </NFButton>
              }
            />
          }
        />
      </NFCard>

      <NFDialog
        open={mode !== null}
        onOpenChange={(o) => !o && setMode(null)}
        title={dialogTitle}
        description={
          mode === "assign"
            ? "The plan's current price and limits are copied onto the subscription."
            : mode === "extend"
              ? "Push the end date out without changing the plan."
              : "The society keeps its data but is locked out until a new subscription is assigned."
        }
        footer={
          <>
            <NFButton variant="secondary" onClick={() => setMode(null)} disabled={busy}>
              Cancel
            </NFButton>
            <NFButton
              variant={mode === "suspend" ? "danger" : "primary"}
              onClick={() => void submit()}
              loading={busy}
            >
              {mode === "assign" ? "Assign" : mode === "extend" ? "Extend" : "Suspend"}
            </NFButton>
          </>
        }
      >
        {formError && (
          <p
            role="alert"
            className="mb-4 rounded-[var(--nf-radius-sm)] border border-[var(--nf-danger)]/25 bg-[var(--nf-danger-subtle)] px-3 py-2 text-[13px] font-medium text-[var(--nf-danger)]"
          >
            {formError}
          </p>
        )}

        {mode === "assign" && (
          <div className="grid gap-4 sm:grid-cols-2">
            <NFField
              label="Plan"
              htmlFor="assign-plan"
              required
              error={fieldErrors.plan_id}
              className="sm:col-span-2"
            >
              <NFSelect
                id="assign-plan"
                value={planId}
                onChange={(e) => setPlanId(e.target.value)}
              >
                {plans.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} — {formatCurrency(p.price)} /{" "}
                    {p.billing_cycle.replace(/_/g, " ").toLowerCase()}
                  </option>
                ))}
              </NFSelect>
            </NFField>

            <NFField label="Status" htmlFor="assign-status" error={fieldErrors.status}>
              <NFSelect
                id="assign-status"
                value={status}
                onChange={(e) => setStatus(e.target.value as SubscriptionStatus)}
              >
                {ASSIGN_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </NFSelect>
            </NFField>

            <NFField
              label="Start date"
              htmlFor="assign-start"
              error={fieldErrors.start_date}
              hint="Defaults to today."
            >
              <NFInput
                id="assign-start"
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
            </NFField>

            <NFField
              label="End date"
              htmlFor="assign-end"
              error={fieldErrors.end_date}
              hint="Defaults to one billing cycle out."
            >
              <NFInput
                id="assign-end"
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
              />
            </NFField>

            <NFField
              label="Notes"
              htmlFor="assign-notes"
              error={fieldErrors.notes}
              className="sm:col-span-2"
            >
              <NFTextarea
                id="assign-notes"
                rows={2}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Reference for the finance team."
              />
            </NFField>
          </div>
        )}

        {mode === "extend" && target && (
          <div className="grid gap-4 sm:grid-cols-2">
            <p className="text-[13px] text-[var(--nf-text-muted)] sm:col-span-2">
              Currently ends {formatDate(target.end_date)} ({daysLeft(target.end_date)} days left).
            </p>

            <NFField
              label="Extend by (days)"
              htmlFor="ext-days"
              error={fieldErrors.days}
              hint="Ignored if an end date is set."
            >
              <NFInput
                id="ext-days"
                type="number"
                min="1"
                max="3650"
                value={extendDays}
                onChange={(e) => setExtendDays(e.target.value)}
                disabled={newEndDate !== ""}
              />
            </NFField>

            <NFField label="Or set end date" htmlFor="ext-date" error={fieldErrors.new_end_date}>
              <NFInput
                id="ext-date"
                type="date"
                value={newEndDate}
                onChange={(e) => setNewEndDate(e.target.value)}
              />
            </NFField>

            <NFField
              label="Notes"
              htmlFor="ext-notes"
              error={fieldErrors.notes}
              className="sm:col-span-2"
            >
              <NFTextarea
                id="ext-notes"
                rows={2}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Why the term was extended."
              />
            </NFField>
          </div>
        )}

        {mode === "suspend" && target && (
          <NFField
            label="Reason"
            htmlFor="susp-reason"
            error={fieldErrors.reason}
            hint="Recorded in the platform audit log."
          >
            <NFTextarea
              id="susp-reason"
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Non-payment after three reminders."
            />
          </NFField>
        )}
      </NFDialog>
    </>
  );
}
