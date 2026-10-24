import { Blocks, Play, Plus, Settings2, Trash2 } from "lucide-react";
import * as React from "react";
import { Link, useNavigate } from "react-router-dom";

import { NFConfirmDialog, NFDialog } from "@/components/nestflow/data";
import {
  NFButton,
  NFCard,
  NFCardBody,
  NFCardHeader,
  NFEmptyState,
  NFField,
  NFPageHeader,
  NFSelect,
  NFSkeleton,
  NFStatusBadge,
} from "@/components/nestflow/primitives";
import { ApiError, api } from "@/services/api";
import type { BillingRun, BillTemplate, PeriodOption } from "@/types";
import { formatDate } from "@/utils/format";

const FREQUENCY_LABELS: Record<string, string> = {
  MONTHLY: "Monthly",
  QUARTERLY: "Quarterly",
  HALF_YEARLY: "Half-yearly",
  YEARLY: "Yearly",
  ONE_TIME: "One-time",
};

export default function TemplatesPage() {
  const navigate = useNavigate();
  const [templates, setTemplates] = React.useState<BillTemplate[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [deleting, setDeleting] = React.useState<BillTemplate | null>(null);
  const [running, setRunning] = React.useState<BillTemplate | null>(null);
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      setTemplates(await api.get<BillTemplate[]>("/bill-templates", { include_inactive: true }));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load templates.");
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function runDelete() {
    if (!deleting) return;
    setBusy(true);
    try {
      await api.delete(`/bill-templates/${deleting.id}`);
      setDeleting(null);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "This template could not be deleted.");
      setDeleting(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <NFPageHeader
        title="Bill templates"
        description="A template holds the formula. Versions keep history intact when rates change."
        actions={
          <NFButton asChild>
            <Link to="/app/bill-builder">
              <Plus /> New template
            </Link>
          </NFButton>
        }
      />

      {error && (
        <div
          role="alert"
          className="mb-5 rounded-[var(--nf-radius)] border border-[var(--nf-danger)]/30 bg-[var(--nf-danger-subtle)] p-3.5 text-sm text-[var(--nf-text)]"
        >
          {error}
        </div>
      )}

      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <NFSkeleton key={i} className="h-40" />
          ))}
        </div>
      ) : templates.length === 0 ? (
        <NFCard>
          <NFEmptyState
            icon={<Blocks />}
            title="No bill templates yet"
            description="Build the maintenance formula once — base amount, per-square-foot rate, water slabs, rebates — and every billing run reuses it."
            action={
              <NFButton asChild>
                <Link to="/app/bill-builder">
                  <Plus /> Build the first template
                </Link>
              </NFButton>
            }
          />
        </NFCard>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {templates.map((t) => (
            <NFCard key={t.id} className="flex flex-col">
              <NFCardHeader
                title={t.name}
                description={FREQUENCY_LABELS[t.frequency] ?? t.frequency}
                action={<NFStatusBadge status={t.is_active ? "ACTIVE" : "SUSPENDED"} />}
              />
              <NFCardBody className="flex-1">
                <p className="line-clamp-2 min-h-10 text-[13px] text-[var(--nf-text-muted)]">
                  {t.description || "No description."}
                </p>
                <dl className="mt-4 grid grid-cols-2 gap-3 text-[13px]">
                  <div>
                    <dt className="text-[var(--nf-text-muted)]">Versions</dt>
                    <dd className="font-medium text-[var(--nf-text)]">{t.version_count}</dd>
                  </div>
                  <div>
                    <dt className="text-[var(--nf-text-muted)]">Billing runs</dt>
                    <dd className="font-medium text-[var(--nf-text)]">{t.run_count}</dd>
                  </div>
                </dl>
              </NFCardBody>
              <div className="flex items-center gap-1 border-t border-[var(--nf-border)] p-2">
                <NFButton variant="ghost" size="sm" asChild className="flex-1">
                  <Link to={`/app/bill-builder/${t.id}`}>
                    <Settings2 /> Edit formula
                  </Link>
                </NFButton>
                <NFButton
                  variant="secondary"
                  size="sm"
                  onClick={() => setRunning(t)}
                  disabled={!t.is_active}
                >
                  <Play /> Bill
                </NFButton>
                <NFButton
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Delete ${t.name}`}
                  onClick={() => setDeleting(t)}
                >
                  <Trash2 />
                </NFButton>
              </div>
            </NFCard>
          ))}
        </div>
      )}

      <RunDialog
        template={running}
        onClose={() => setRunning(null)}
        onCreated={(run) => {
          setRunning(null);
          navigate(`/app/bills?run_id=${run.id}`);
        }}
      />

      <NFConfirmDialog
        open={deleting !== null}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={`Delete ${deleting?.name ?? ""}?`}
        description="A template with billing runs cannot be deleted — historical bills must keep their formula. Deactivate it instead."
        confirmLabel="Delete template"
        destructive
        loading={busy}
        onConfirm={runDelete}
      />
    </>
  );
}

/* -------------------------------------------------------------------------- */

function RunDialog({
  template,
  onClose,
  onCreated,
}: {
  template: BillTemplate | null;
  onClose: () => void;
  onCreated: (run: BillingRun) => void;
}) {
  const [periods, setPeriods] = React.useState<PeriodOption[]>([]);
  const [periodKey, setPeriodKey] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!template) return;
    setError(null);
    api
      .get<PeriodOption[]>(`/billing/periods/${template.id}`)
      .then((p) => {
        setPeriods(p);
        setPeriodKey(p.filter((x) => !x.already_billed).at(-1)?.key ?? p.at(-1)?.key ?? "");
      })
      .catch(() => setPeriods([]));
  }, [template]);

  async function generate() {
    if (!template) return;
    setBusy(true);
    setError(null);
    try {
      onCreated(
        await api.post<BillingRun>("/billing/runs", {
          template_id: template.id,
          period_key: periodKey,
        }),
      );
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not generate bills.");
    } finally {
      setBusy(false);
    }
  }

  const chosen = periods.find((p) => p.key === periodKey);

  return (
    <NFDialog
      open={template !== null}
      onOpenChange={(o) => !o && onClose()}
      title="Generate bills"
      description="Creates draft bills for every applicable flat. Nothing is sent to residents until you publish."
      footer={
        <>
          <NFButton variant="secondary" onClick={onClose}>
            Cancel
          </NFButton>
          <NFButton onClick={generate} loading={busy} disabled={!periodKey || chosen?.already_billed}>
            Generate drafts
          </NFButton>
        </>
      }
    >
      <div className="space-y-4">
        {error && (
          <p
            role="alert"
            className="rounded-[var(--nf-radius-sm)] bg-[var(--nf-danger-subtle)] px-3 py-2 text-[13px] text-[var(--nf-danger)]"
          >
            {error}
          </p>
        )}

        <NFField label="Billing period" htmlFor="run-period">
          <NFSelect
            id="run-period"
            value={periodKey}
            onChange={(e) => setPeriodKey(e.target.value)}
          >
            {periods.map((p) => (
              <option key={p.key} value={p.key}>
                {p.label}
                {p.already_billed ? " — already billed" : ""}
              </option>
            ))}
          </NFSelect>
        </NFField>

        {chosen && (
          <dl className="space-y-2 rounded-[var(--nf-radius)] bg-[var(--nf-background)] p-3 text-[13px]">
            <div className="flex justify-between">
              <dt className="text-[var(--nf-text-muted)]">Covers</dt>
              <dd className="text-[var(--nf-text)]">
                {formatDate(chosen.start)} – {formatDate(chosen.end)}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-[var(--nf-text-muted)]">Template</dt>
              <dd className="text-[var(--nf-text)]">{template?.name}</dd>
            </div>
          </dl>
        )}

        {chosen?.already_billed && (
          <p className="rounded-[var(--nf-radius-sm)] bg-[var(--nf-warning-subtle)] px-3 py-2 text-[13px] text-[var(--nf-warning)]">
            This period has already been billed. Open that run instead of creating another.
          </p>
        )}
      </div>
    </NFDialog>
  );
}
