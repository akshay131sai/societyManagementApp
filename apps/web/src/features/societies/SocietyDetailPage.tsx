import {
  Archive,
  ArrowLeft,
  Database,
  Lock,
  RefreshCw,
  Unlock,
  Users,
} from "lucide-react";
import * as React from "react";
import { Link, useParams } from "react-router-dom";

import { NFConfirmDialog, NFStatCard } from "@/components/nestflow/data";
import {
  NFButton,
  NFCard,
  NFCardBody,
  NFCardHeader,
  NFField,
  NFPageHeader,
  NFSkeleton,
  NFStatusBadge,
  NFTextarea,
} from "@/components/nestflow/primitives";
import { ApiError, api } from "@/services/api";
import type { SocietyDetail } from "@/types";
import { formatDate, formatNumber, formatPhone } from "@/utils/format";

type Action = "lock" | "unlock" | "archive" | "retry" | null;

export default function SocietyDetailPage() {
  const { societyId = "" } = useParams();
  const [society, setSociety] = React.useState<SocietyDetail | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [action, setAction] = React.useState<Action>(null);
  const [busy, setBusy] = React.useState(false);
  const [reason, setReason] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      setSociety(await api.get<SocietyDetail>(`/platform/societies/${societyId}`));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load this society.");
    } finally {
      setLoading(false);
    }
  }, [societyId]);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function runAction() {
    if (!action) return;
    setBusy(true);
    setError(null);
    try {
      const base = `/platform/societies/${societyId}`;
      if (action === "lock") await api.post(`${base}/lock`, { reason });
      if (action === "unlock") await api.post(`${base}/unlock`);
      if (action === "archive") await api.post(`${base}/archive`);
      if (action === "retry") await api.post(`${base}/retry-provisioning`);
      setAction(null);
      setReason("");
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "That action could not be completed.");
    } finally {
      setBusy(false);
    }
  }

  if (loading && !society) {
    return (
      <div className="space-y-4">
        <NFSkeleton className="h-9 w-64" />
        <div className="grid gap-4 sm:grid-cols-3">
          <NFSkeleton className="h-28" />
          <NFSkeleton className="h-28" />
          <NFSkeleton className="h-28" />
        </div>
        <NFSkeleton className="h-64" />
      </div>
    );
  }

  if (!society) {
    return (
      <NFCard className="p-8 text-center">
        <p className="text-sm text-[var(--nf-text-muted)]">{error ?? "Society not found."}</p>
        <NFButton className="mt-5" variant="secondary" asChild>
          <Link to="/admin/societies">Back to societies</Link>
        </NFButton>
      </NFCard>
    );
  }

  const isLocked = society.status === "LOCKED" || society.status === "SUSPENDED";
  const needsRetry = society.status === "PROVISIONING_FAILED";

  return (
    <>
      <NFPageHeader
        title={society.name}
        description={`${society.city}, ${society.state} · ${society.slug}`}
        breadcrumb={
          <Link
            to="/admin/societies"
            className="inline-flex items-center gap-1.5 text-[13px] text-[var(--nf-text-muted)] hover:text-[var(--nf-primary)]"
          >
            <ArrowLeft className="size-3.5" aria-hidden /> Societies
          </Link>
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <NFStatusBadge status={society.status} />
            {needsRetry && (
              <NFButton size="sm" onClick={() => setAction("retry")}>
                <RefreshCw /> Retry setup
              </NFButton>
            )}
            {isLocked ? (
              <NFButton size="sm" variant="secondary" onClick={() => setAction("unlock")}>
                <Unlock /> Unlock
              </NFButton>
            ) : (
              society.status === "ACTIVE" && (
                <NFButton size="sm" variant="secondary" onClick={() => setAction("lock")}>
                  <Lock /> Lock
                </NFButton>
              )
            )}
            {society.status !== "ARCHIVED" && (
              <NFButton size="sm" variant="ghost" onClick={() => setAction("archive")}>
                <Archive /> Archive
              </NFButton>
            )}
          </div>
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

      {society.locked_reason && isLocked && (
        <div className="mb-5 rounded-[var(--nf-radius)] border border-[var(--nf-danger)]/30 bg-[var(--nf-danger-subtle)] p-3.5">
          <p className="text-[13px] font-semibold text-[var(--nf-danger)]">Locked</p>
          <p className="mt-0.5 text-sm text-[var(--nf-text)]">{society.locked_reason}</p>
        </div>
      )}

      {society.registry?.provisioning_error && (
        <div className="mb-5 rounded-[var(--nf-radius)] border border-[var(--nf-danger)]/30 bg-[var(--nf-danger-subtle)] p-3.5">
          <p className="text-[13px] font-semibold text-[var(--nf-danger)]">
            Setup failed at “{society.registry.provisioning_step}”
          </p>
          <p className="mt-1 font-mono text-[12px] leading-relaxed text-[var(--nf-text-muted)]">
            {society.registry.provisioning_error}
          </p>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-3">
        <NFStatCard label="Users" value={formatNumber(society.user_count)} icon={<Users />} />
        <NFStatCard label="Flats" value={formatNumber(society.total_flats)} icon={<Database />} tone="info" />
        <NFStatCard
          label="Subscription"
          value={society.subscription?.status ?? "None"}
          hint={
            society.subscription
              ? `${society.subscription.plan_name ?? "—"} · until ${formatDate(society.subscription.end_date)}`
              : undefined
          }
          icon={<RefreshCw />}
          tone={society.subscription?.status === "ACTIVE" ? "success" : "warning"}
        />
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <NFCard>
          <NFCardHeader title="Contact" />
          <NFCardBody>
            <DefinitionList
              rows={[
                ["Office email", society.contact_email],
                ["Office phone", formatPhone(society.contact_phone)],
                ["Address", society.address_line1 ?? "—"],
                ["PIN code", society.pincode],
                ["Registration", society.registration_number ?? "—"],
                ["Timezone", society.timezone],
                ["Created", formatDate(society.created_at)],
              ]}
            />
          </NFCardBody>
        </NFCard>

        <NFCard>
          <NFCardHeader
            title="Tenant database"
            description="This society's data lives in its own PostgreSQL database."
          />
          <NFCardBody>
            {society.registry ? (
              <DefinitionList
                mono
                rows={[
                  ["Database", society.registry.database_name],
                  ["Sequence", String(society.registry.sequence_number)],
                  ["State", society.registry.provisioning_state],
                  ["Schema revision", society.registry.alembic_revision ?? "—"],
                  ["Migrated", formatDate(society.registry.migrated_at)],
                ]}
              />
            ) : (
              <p className="text-sm text-[var(--nf-text-muted)]">
                No database has been registered for this society.
              </p>
            )}
          </NFCardBody>
        </NFCard>
      </div>

      {/* Confirmations */}
      <NFConfirmDialog
        open={action === "lock"}
        onOpenChange={(o) => !o && setAction(null)}
        title="Lock this society?"
        description="Everyone in this society will lose access immediately. Their data is untouched."
        confirmLabel="Lock society"
        destructive
        loading={busy}
        onConfirm={runAction}
      >
        <NFField label="Reason" htmlFor="lock-reason" required>
          <NFTextarea
            id="lock-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Shown to the society's users when they try to sign in."
          />
        </NFField>
      </NFConfirmDialog>

      <NFConfirmDialog
        open={action === "unlock"}
        onOpenChange={(o) => !o && setAction(null)}
        title="Unlock this society?"
        description="Access is restored immediately for every user in this society."
        confirmLabel="Unlock"
        loading={busy}
        onConfirm={runAction}
      />

      <NFConfirmDialog
        open={action === "archive"}
        onOpenChange={(o) => !o && setAction(null)}
        title="Archive this society?"
        description="The society is hidden and all access is revoked. The tenant database is retained, so this is reversible by an operator."
        confirmLabel="Archive"
        destructive
        loading={busy}
        onConfirm={runAction}
      />

      <NFConfirmDialog
        open={action === "retry"}
        onOpenChange={(o) => !o && setAction(null)}
        title="Retry provisioning?"
        description="Setup resumes from the first incomplete step. Anything already created is reused rather than duplicated."
        confirmLabel="Retry setup"
        loading={busy}
        onConfirm={runAction}
      />
    </>
  );
}

function DefinitionList({ rows, mono }: { rows: [string, string][]; mono?: boolean }) {
  return (
    <dl className="space-y-3 text-sm">
      {rows.map(([label, value]) => (
        <div key={label} className="flex flex-wrap justify-between gap-2">
          <dt className="text-[var(--nf-text-muted)]">{label}</dt>
          <dd
            className={
              mono
                ? "font-mono text-[13px] text-[var(--nf-text)]"
                : "text-right text-[var(--nf-text)]"
            }
          >
            {value}
          </dd>
        </div>
      ))}
    </dl>
  );
}
