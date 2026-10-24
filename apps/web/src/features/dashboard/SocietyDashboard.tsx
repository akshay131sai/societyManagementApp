import {
  Building,
  CalendarClock,
  Check,
  CreditCard,
  Palette,
  ShieldCheck,
  UserCog,
  Users,
} from "lucide-react";
import * as React from "react";
import { Link } from "react-router-dom";

import { NFStatCard } from "@/components/nestflow/data";
import {
  NFButton,
  NFCard,
  NFCardBody,
  NFCardHeader,
  NFPageHeader,
  NFSkeleton,
  NFStatusBadge,
} from "@/components/nestflow/primitives";
import { api } from "@/services/api";
import { useAppSelector } from "@/store";
import type { SocietyDashboard as Dashboard } from "@/types";
import { formatDate, formatNumber } from "@/utils/format";
import { hasPermission } from "@/utils/permissions";

const ROLE_LABELS: Record<string, string> = {
  SOCIETY_ADMIN: "Society Admins",
  FLAT_OWNER: "Flat Owners",
  MAINTENANCE_ADMIN: "Maintenance Admins",
  MAINTENANCE: "Maintenance Staff",
  HOUSEKEEPER_ADMIN: "Housekeeping Admins",
  HOUSEKEEPER: "Housekeeping Staff",
  SECURITY_ADMIN: "Security Admins",
  SECURITY: "Security Guards",
};

export default function SocietyDashboardPage() {
  const principal = useAppSelector((s) => s.auth.principal);
  const society = useAppSelector((s) => s.auth.society);
  const subscription = useAppSelector((s) => s.auth.subscription);

  const [data, setData] = React.useState<Dashboard | null>(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    const controller = new AbortController();
    api
      .get<Dashboard>("/society/dashboard", undefined, controller.signal)
      .then(setData)
      .catch(() => undefined)
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  const firstName = principal?.display_name.split(" ")[0] ?? "there";
  const canManageUsers = hasPermission(principal, "user.read");
  const canTheme = hasPermission(principal, "theme.update");

  return (
    <>
      <NFPageHeader
        title={`Good to see you, ${firstName}`}
        description={
          society ? `${society.name} · ${society.city}, ${society.state}` : "Your society at a glance"
        }
        actions={
          canTheme ? (
            <NFButton variant="secondary" asChild>
              <Link to="/app/appearance">
                <Palette /> Appearance
              </Link>
            </NFButton>
          ) : undefined
        }
      />

      {subscription?.is_trial && (
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-[var(--nf-radius)] border border-[var(--nf-info)]/25 bg-[var(--nf-info-subtle)] p-4">
          <div className="flex items-start gap-2.5">
            <CalendarClock className="mt-0.5 size-4 shrink-0 text-[var(--nf-info)]" aria-hidden />
            <div>
              <p className="text-[13px] font-semibold text-[var(--nf-info)]">
                Trial · {subscription.days_remaining} days remaining
              </p>
              <p className="mt-0.5 text-[13px] text-[var(--nf-text-muted)]">
                Your {subscription.plan_name ?? "trial"} plan runs until{" "}
                {formatDate(subscription.end_date)}.
              </p>
            </div>
          </div>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <NFStatCard
          label="Society members"
          value={formatNumber(data?.total_users ?? 0)}
          hint={data ? `${data.active_users} active` : undefined}
          icon={<Users />}
          loading={loading}
        />
        <NFStatCard
          label="Flats"
          value={formatNumber(data?.total_flats ?? 0)}
          hint={data ? `across ${data.total_buildings} building(s)` : undefined}
          icon={<Building />}
          tone="info"
          loading={loading}
        />
        <NFStatCard
          label="Subscription"
          value={subscription?.status ?? "—"}
          hint={subscription ? `${subscription.days_remaining} days remaining` : undefined}
          icon={<CreditCard />}
          tone={subscription?.status === "ACTIVE" ? "success" : "warning"}
          loading={loading}
        />
        <NFStatCard
          label="Residents"
          value={formatNumber(data?.total_residents ?? 0)}
          hint={
            data?.occupancy
              ? `${data.occupancy.VACANT ?? 0} flat(s) vacant`
              : undefined
          }
          icon={<ShieldCheck />}
          tone="primary"
          loading={loading}
        />
      </div>

      <div className="mt-6 grid gap-5 lg:grid-cols-3">
        <NFCard className="lg:col-span-2">
          <NFCardHeader
            title="Members by role"
            description="Who currently has access to this society."
            action={
              canManageUsers ? (
                <NFButton variant="ghost" size="sm" asChild>
                  <Link to="/app/users">
                    <UserCog /> Manage
                  </Link>
                </NFButton>
              ) : undefined
            }
          />
          <NFCardBody>
            {loading ? (
              <div className="space-y-3">
                {[0, 1, 2, 3].map((i) => (
                  <NFSkeleton key={i} className="h-9" />
                ))}
              </div>
            ) : (
              <ul className="space-y-1">
                {Object.entries(data?.roles_summary ?? {})
                  .sort(([, a], [, b]) => b - a)
                  .map(([code, count]) => (
                    <li
                      key={code}
                      className="flex items-center justify-between rounded-[var(--nf-radius-sm)] px-2.5 py-2 text-sm transition-colors hover:bg-[var(--nf-background)]"
                    >
                      <span className="text-[var(--nf-text)]">{ROLE_LABELS[code] ?? code}</span>
                      <span
                        className={
                          count > 0
                            ? "font-semibold tabular-nums text-[var(--nf-text)]"
                            : "tabular-nums text-[var(--nf-text-subtle)]"
                        }
                      >
                        {count}
                      </span>
                    </li>
                  ))}
              </ul>
            )}
          </NFCardBody>
        </NFCard>

        <NFCard>
          <NFCardHeader title="Society" />
          <NFCardBody>
            <dl className="space-y-3 text-sm">
              <Row label="Status">
                {society ? <NFStatusBadge status={society.status} /> : "—"}
              </Row>
              <Row label="Identifier">
                <span className="font-mono text-[13px]">{society?.slug ?? "—"}</span>
              </Row>
              <Row label="Timezone">{society?.timezone ?? "—"}</Row>
              <Row label="Set up">{formatDate(data?.provisioned_at)}</Row>
            </dl>

            <div className="mt-5 space-y-2.5 border-t border-[var(--nf-border)] pt-4">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--nf-text-muted)]">
                Setup
              </p>
              {[
                { label: "Add buildings and floors", done: (data?.total_buildings ?? 0) > 0, to: "/app/buildings" },
                { label: "Add flats", done: (data?.total_flats ?? 0) > 0, to: "/app/flats" },
                { label: "Add residents", done: (data?.total_residents ?? 0) > 0, to: "/app/residents" },
              ].map((step) => (
                <Link
                  key={step.label}
                  to={step.to}
                  className="flex items-center gap-2.5 text-[13px] transition-colors hover:text-[var(--nf-primary)]"
                >
                  <span
                    className={
                      step.done
                        ? "flex size-4 shrink-0 items-center justify-center rounded-full bg-[var(--nf-success)] text-white"
                        : "size-4 shrink-0 rounded-full border-2 border-[var(--nf-border-strong)]"
                    }
                    aria-hidden
                  >
                    {step.done && <Check className="size-2.5" strokeWidth={3} />}
                  </span>
                  <span
                    className={
                      step.done
                        ? "text-[var(--nf-text-muted)] line-through"
                        : "text-[var(--nf-text)]"
                    }
                  >
                    {step.label}
                  </span>
                </Link>
              ))}
            </div>
          </NFCardBody>
        </NFCard>
      </div>
    </>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <dt className="text-[var(--nf-text-muted)]">{label}</dt>
      <dd className="text-[var(--nf-text)]">{children}</dd>
    </div>
  );
}
