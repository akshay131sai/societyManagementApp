import { Package, Pencil, Plus } from "lucide-react";
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
import { ApiError, api } from "@/services/api";
import type { BillingCycle, SubscriptionPlan } from "@/types";
import { formatCurrency, formatNumber } from "@/utils/format";

const CYCLES: BillingCycle[] = ["MONTHLY", "QUARTERLY", "HALF_YEARLY", "YEARLY"];

/** Blank form. `code` and cycle are immutable after creation, so edit hides them. */
const EMPTY = {
  name: "",
  code: "",
  description: "",
  price: "",
  billing_cycle: "MONTHLY" as BillingCycle,
  max_flats: "",
  max_users: "",
  trial_days: "14",
  sort_order: "0",
  is_active: true,
};

type FormState = typeof EMPTY;

export default function PlansPage() {
  const [plans, setPlans] = React.useState<SubscriptionPlan[] | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [loadError, setLoadError] = React.useState<string | null>(null);

  const [editing, setEditing] = React.useState<SubscriptionPlan | null>(null);
  const [open, setOpen] = React.useState(false);
  const [form, setForm] = React.useState<FormState>(EMPTY);
  const [saving, setSaving] = React.useState(false);
  const [formError, setFormError] = React.useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      setPlans(await api.get<SubscriptionPlan[]>("/platform/plans"));
      setLoadError(null);
    } catch (e) {
      setLoadError(e instanceof ApiError ? e.message : "Could not load plans.");
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  function openCreate() {
    setEditing(null);
    setForm(EMPTY);
    setFormError(null);
    setFieldErrors({});
    setOpen(true);
  }

  function openEdit(plan: SubscriptionPlan) {
    setEditing(plan);
    setForm({
      name: plan.name,
      code: plan.code,
      description: plan.description ?? "",
      price: plan.price,
      billing_cycle: plan.billing_cycle,
      max_flats: plan.max_flats?.toString() ?? "",
      max_users: plan.max_users?.toString() ?? "",
      trial_days: plan.trial_days.toString(),
      sort_order: plan.sort_order.toString(),
      is_active: plan.is_active,
    });
    setFormError(null);
    setFieldErrors({});
    setOpen(true);
  }

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  /** Optional numerics go as null, not "", so the server reads "unlimited". */
  const num = (v: string) => (v.trim() === "" ? null : Number(v));

  async function save() {
    setSaving(true);
    setFormError(null);
    setFieldErrors({});
    try {
      const shared = {
        name: form.name.trim(),
        description: form.description.trim() || null,
        price: form.price.trim(),
        max_flats: num(form.max_flats),
        max_users: num(form.max_users),
        trial_days: Number(form.trial_days || 0),
        sort_order: Number(form.sort_order || 0),
      };

      if (editing) {
        await api.patch(`/platform/plans/${editing.id}`, { ...shared, is_active: form.is_active });
      } else {
        await api.post("/platform/plans", {
          ...shared,
          code: form.code.trim().toUpperCase(),
          billing_cycle: form.billing_cycle,
          features: {},
        });
      }
      setOpen(false);
      await load();
    } catch (e) {
      if (e instanceof ApiError) {
        setFieldErrors(e.fieldErrors);
        setFormError(e.message);
      } else {
        setFormError("The plan could not be saved.");
      }
    } finally {
      setSaving(false);
    }
  }

  /** Retiring a plan leaves existing subscriptions on their price snapshot. */
  async function toggleActive(plan: SubscriptionPlan) {
    try {
      await api.patch(`/platform/plans/${plan.id}`, { is_active: !plan.is_active });
      await load();
    } catch (e) {
      setLoadError(e instanceof ApiError ? e.message : "Could not update the plan.");
    }
  }

  const columns: Column<SubscriptionPlan>[] = [
    {
      key: "name",
      header: "Plan",
      render: (p) => (
        <div className="min-w-0">
          <p className="truncate font-medium text-[var(--nf-text)]">{p.name}</p>
          <p className="truncate font-mono text-xs text-[var(--nf-text-muted)]">{p.code}</p>
        </div>
      ),
    },
    {
      key: "price",
      header: "Price",
      className: "tabular-nums",
      render: (p) => (
        <div>
          <span className="font-medium text-[var(--nf-text)]">{formatCurrency(p.price)}</span>
          <span className="ml-1 text-xs text-[var(--nf-text-muted)]">
            / {p.billing_cycle.replace(/_/g, " ").toLowerCase()}
          </span>
        </div>
      ),
    },
    {
      key: "limits",
      header: "Limits",
      hideOnMobile: true,
      className: "tabular-nums",
      render: (p) => (
        <span className="text-[var(--nf-text-muted)]">
          {p.max_flats ? `${formatNumber(p.max_flats)} flats` : "Unlimited flats"}
          {" · "}
          {p.max_users ? `${formatNumber(p.max_users)} users` : "Unlimited users"}
        </span>
      ),
    },
    {
      key: "trial",
      header: "Trial",
      hideOnMobile: true,
      className: "tabular-nums",
      render: (p) => (
        <span className="text-[var(--nf-text-muted)]">
          {p.trial_days > 0 ? `${p.trial_days} days` : "None"}
        </span>
      ),
    },
    {
      key: "status",
      header: "Status",
      render: (p) => <NFStatusBadge status={p.is_active ? "ACTIVE" : "ARCHIVED"} />,
    },
    {
      key: "actions",
      header: "",
      render: (p) => (
        <div className="flex justify-end gap-1">
          <NFButton
            variant="ghost"
            size="icon-sm"
            aria-label={`Edit ${p.name}`}
            onClick={() => openEdit(p)}
          >
            <Pencil />
          </NFButton>
          <NFButton variant="ghost" size="sm" onClick={() => void toggleActive(p)}>
            {p.is_active ? "Retire" : "Restore"}
          </NFButton>
        </div>
      ),
    },
  ];

  return (
    <>
      <NFPageHeader
        title="Subscription Plans"
        description="What a society can buy. Price and limits are snapshotted onto a subscription when it is assigned, so editing a plan never rewrites history."
        actions={
          <NFButton onClick={openCreate}>
            <Plus /> New plan
          </NFButton>
        }
      />

      {loadError && (
        <div
          role="alert"
          className="mb-4 rounded-[var(--nf-radius-sm)] border border-[var(--nf-danger)]/25 bg-[var(--nf-danger-subtle)] px-4 py-3 text-sm text-[var(--nf-danger)]"
        >
          {loadError}
        </div>
      )}

      <NFCard>
        <NFDataTable
          caption="Subscription plans offered on the platform"
          columns={columns}
          rows={plans ?? []}
          rowKey={(p) => p.id}
          loading={loading}
          empty={
            <NFEmptyState
              icon={<Package />}
              title="No plans yet"
              description="Create a plan before onboarding a society — provisioning assigns the first active plan by sort order."
              action={
                <NFButton onClick={openCreate}>
                  <Plus /> Create a plan
                </NFButton>
              }
            />
          }
        />
      </NFCard>

      <NFDialog
        open={open}
        onOpenChange={setOpen}
        title={editing ? `Edit ${editing.name}` : "New plan"}
        description={
          editing
            ? "Existing subscriptions keep the price they were sold at."
            : "The code identifies the plan in the API and cannot be changed later."
        }
        size="lg"
        footer={
          <>
            <NFButton variant="secondary" onClick={() => setOpen(false)} disabled={saving}>
              Cancel
            </NFButton>
            <NFButton onClick={() => void save()} loading={saving}>
              {editing ? "Save changes" : "Create plan"}
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

        <div className="grid gap-4 sm:grid-cols-2">
          <NFField label="Name" htmlFor="plan-name" required error={fieldErrors.name}>
            <NFInput
              id="plan-name"
              value={form.name}
              onChange={(e) => set("name", e.target.value)}
              placeholder="Growth"
            />
          </NFField>

          {!editing && (
            <NFField
              label="Code"
              htmlFor="plan-code"
              required
              error={fieldErrors.code}
              hint="Uppercase letters, digits and underscores."
            >
              <NFInput
                id="plan-code"
                value={form.code}
                onChange={(e) => set("code", e.target.value.toUpperCase())}
                placeholder="GROWTH"
                className="font-mono"
              />
            </NFField>
          )}

          <NFField label="Price" htmlFor="plan-price" required error={fieldErrors.price}>
            <NFInput
              id="plan-price"
              type="number"
              min="0"
              step="0.01"
              value={form.price}
              onChange={(e) => set("price", e.target.value)}
              placeholder="4999.00"
            />
          </NFField>

          {!editing && (
            <NFField
              label="Billing cycle"
              htmlFor="plan-cycle"
              required
              error={fieldErrors.billing_cycle}
            >
              <NFSelect
                id="plan-cycle"
                value={form.billing_cycle}
                onChange={(e) => set("billing_cycle", e.target.value as BillingCycle)}
              >
                {CYCLES.map((c) => (
                  <option key={c} value={c}>
                    {c.replace(/_/g, " ")}
                  </option>
                ))}
              </NFSelect>
            </NFField>
          )}

          <NFField
            label="Max flats"
            htmlFor="plan-flats"
            error={fieldErrors.max_flats}
            hint="Leave blank for unlimited."
          >
            <NFInput
              id="plan-flats"
              type="number"
              min="1"
              value={form.max_flats}
              onChange={(e) => set("max_flats", e.target.value)}
              placeholder="Unlimited"
            />
          </NFField>

          <NFField
            label="Max users"
            htmlFor="plan-users"
            error={fieldErrors.max_users}
            hint="Leave blank for unlimited."
          >
            <NFInput
              id="plan-users"
              type="number"
              min="1"
              value={form.max_users}
              onChange={(e) => set("max_users", e.target.value)}
              placeholder="Unlimited"
            />
          </NFField>

          <NFField label="Trial days" htmlFor="plan-trial" error={fieldErrors.trial_days}>
            <NFInput
              id="plan-trial"
              type="number"
              min="0"
              max="365"
              value={form.trial_days}
              onChange={(e) => set("trial_days", e.target.value)}
            />
          </NFField>

          <NFField
            label="Sort order"
            htmlFor="plan-sort"
            error={fieldErrors.sort_order}
            hint="The lowest active plan is the provisioning default."
          >
            <NFInput
              id="plan-sort"
              type="number"
              value={form.sort_order}
              onChange={(e) => set("sort_order", e.target.value)}
            />
          </NFField>

          <NFField
            label="Description"
            htmlFor="plan-desc"
            error={fieldErrors.description}
            className="sm:col-span-2"
          >
            <NFTextarea
              id="plan-desc"
              rows={3}
              value={form.description}
              onChange={(e) => set("description", e.target.value)}
              placeholder="What this plan includes."
            />
          </NFField>

          {editing && (
            <label className="flex items-center gap-2 text-[13px] text-[var(--nf-text)] sm:col-span-2">
              <input
                type="checkbox"
                checked={form.is_active}
                onChange={(e) => set("is_active", e.target.checked)}
                className="size-4 accent-[var(--nf-primary)]"
              />
              Available for new subscriptions
            </label>
          )}
        </div>
      </NFDialog>
    </>
  );
}
