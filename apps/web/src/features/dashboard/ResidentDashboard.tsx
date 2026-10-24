/**
 * The resident home screen.
 *
 * Mobile-first, and deliberately so: this is the screen a resident opens on a
 * phone in a lift lobby, and everything that matters — what they owe, when it
 * is due — is above the fold at 390px before any chart has loaded.
 *
 * The whole screen comes from one request. Eight round trips on a weak
 * connection would be slow, and the numbers could disagree with each other;
 * read in one transaction they cannot.
 */

import {
  Car,
  Droplets,
  IndianRupee,
  PawPrint,
  ReceiptIndianRupee,
  SquareParking,
  TrendingDown,
  TrendingUp,
  TriangleAlert,
  Zap,
} from "lucide-react";
import * as React from "react";
import { Link } from "react-router-dom";

import { NFStatCard } from "@/components/nestflow/data";
import {
  NFButton,
  NFCard,
  NFCardBody,
  NFCardHeader,
  NFEmptyState,
  NFSkeleton,
  NFStatusBadge,
} from "@/components/nestflow/primitives";
import { ChargeBreakdownChart, ChartFrame, ConsumptionAreaChart } from "@/features/utilities/LazyCharts";
import { api } from "@/services/api";
import { useAppSelector } from "@/store";
import type { ConsumptionTrend, ResidentDashboard as Dashboard } from "@/types";
import { formatCurrency, formatDate } from "@/utils/format";
import { hasPermission } from "@/utils/permissions";

function num(value: string | null | undefined): number {
  return value == null ? 0 : Number(value);
}

export default function ResidentDashboardPage() {
  const principal = useAppSelector((s) => s.auth.principal);
  const society = useAppSelector((s) => s.auth.society);

  const [data, setData] = React.useState<Dashboard | null>(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    const controller = new AbortController();
    api
      .get<Dashboard>("/dashboard/resident", undefined, controller.signal)
      .then(setData)
      .catch(() => undefined)
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  const firstName = principal?.display_name.split(" ")[0] ?? "there";
  const flat = data?.flats[0];
  const outstanding = num(data?.outstanding);
  const nextDue = data?.next_due ?? null;

  return (
    <>
      <div className="mb-6">
        <h1 className="text-[22px] font-semibold tracking-tight text-[var(--nf-text)] sm:text-2xl">
          Hello, {firstName}
        </h1>
        <p className="mt-1 text-[13px] text-[var(--nf-text-muted)]">
          {flat
            ? `${flat.flat_number}${flat.building_name ? ` · ${flat.building_name}` : ""}${
                society ? ` · ${society.name}` : ""
              }`
            : society?.name ?? "Your society"}
        </p>
      </div>

      {/* The one thing a resident opens this app to find out. */}
      <NFCard
        className={
          data && data.overdue_count > 0
            ? "border-[var(--nf-danger)]/35 bg-[var(--nf-danger-subtle)]"
            : outstanding > 0
              ? "border-[var(--nf-warning)]/35 bg-[var(--nf-warning-subtle)]"
              : ""
        }
      >
        <NFCardBody>
          {loading ? (
            <div className="space-y-3">
              <NFSkeleton className="h-4 w-32" />
              <NFSkeleton className="h-9 w-44" />
            </div>
          ) : (
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div>
                <p className="text-[12px] font-semibold uppercase tracking-wider text-[var(--nf-text-muted)]">
                  {outstanding > 0 ? "Amount due" : "You're all paid up"}
                </p>
                <p className="mt-1 text-[30px] font-semibold leading-none tabular-nums text-[var(--nf-text)] sm:text-[34px]">
                  {formatCurrency(outstanding)}
                </p>
                {nextDue && (
                  <p className="mt-2 flex flex-wrap items-center gap-1.5 text-[13px] text-[var(--nf-text-muted)]">
                    {nextDue.is_overdue ? (
                      <>
                        <TriangleAlert
                          className="size-3.5 text-[var(--nf-danger)]"
                          aria-hidden
                        />
                        <span className="font-medium text-[var(--nf-danger)]">
                          Overdue by {Math.abs(nextDue.days_until_due)} day
                          {Math.abs(nextDue.days_until_due) === 1 ? "" : "s"}
                        </span>
                      </>
                    ) : (
                      <span>
                        Due {formatDate(nextDue.due_date)} · in {nextDue.days_until_due} day
                        {nextDue.days_until_due === 1 ? "" : "s"}
                      </span>
                    )}
                    <span className="text-[var(--nf-text-subtle)]">·</span>
                    <span>{nextDue.period_label}</span>
                  </p>
                )}
              </div>
              <NFButton asChild>
                <Link to="/app/bills">
                  <ReceiptIndianRupee /> {outstanding > 0 ? "View & pay" : "View bills"}
                </Link>
              </NFButton>
            </div>
          )}
        </NFCardBody>
      </NFCard>

      <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <NFStatCard
          label="Paid this year"
          value={formatCurrency(data?.paid_this_year ?? 0)}
          hint="Since April"
          icon={<IndianRupee />}
          tone="success"
          loading={loading}
        />
        <NFStatCard
          label="Vehicles"
          value={data?.vehicles ?? 0}
          icon={<Car />}
          tone="info"
          loading={loading}
        />
        <NFStatCard
          label="Parking"
          value={data?.parking_slots ?? 0}
          hint={data?.parking_slots === 0 ? "No slot allotted" : "slot(s) allotted"}
          icon={<SquareParking />}
          loading={loading}
        />
        <NFStatCard
          label="Pets"
          value={data?.pets ?? 0}
          icon={<PawPrint />}
          tone="primary"
          loading={loading}
        />
      </div>

      <div className="mt-6 grid gap-5 lg:grid-cols-3">
        <NFCard className="lg:col-span-2">
          <NFCardHeader
            title="Recent bills"
            description="Your last few maintenance bills."
            action={
              <NFButton variant="ghost" size="sm" asChild>
                <Link to="/app/bills">View all</Link>
              </NFButton>
            }
          />
          <NFCardBody className={data?.recent_bills.length ? "px-0 pb-0" : undefined}>
            {loading ? (
              <div className="space-y-3">
                {[0, 1, 2].map((i) => (
                  <NFSkeleton key={i} className="h-11" />
                ))}
              </div>
            ) : data?.recent_bills.length ? (
              <ul className="divide-y divide-[var(--nf-border)]">
                {data.recent_bills.map((bill) => (
                  <li key={bill.id} className="flex items-center justify-between gap-3 px-5 py-3">
                    <div className="min-w-0">
                      <p className="truncate text-[13px] font-medium text-[var(--nf-text)]">
                        {bill.period_label}
                      </p>
                      <p className="truncate font-mono text-[12px] text-[var(--nf-text-muted)]">
                        {bill.bill_number}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-3">
                      <span className="tabular-nums text-[13px] font-semibold text-[var(--nf-text)]">
                        {formatCurrency(bill.total_amount)}
                      </span>
                      <NFStatusBadge status={bill.status} />
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <NFEmptyState
                title="No bills yet"
                description="Your first maintenance bill will appear here once it's published."
              />
            )}
          </NFCardBody>
        </NFCard>

        <NFCard>
          <NFCardHeader
            title="Where it goes"
            description={
              data?.recent_bills[0]
                ? `Breakdown of ${data.recent_bills[0].period_label}`
                : "Your latest bill, by charge."
            }
          />
          <NFCardBody>
            {loading ? (
              <NFSkeleton className="h-[220px]" />
            ) : data?.charge_breakdown.length ? (
              <ChartFrame height={220}>
                <ChargeBreakdownChart
                  data={data.charge_breakdown.map((c) => ({
                    label: c.label,
                    value: num(c.amount),
                  }))}
                  height={220}
                  formatValue={(v) => formatCurrency(v)}
                />
              </ChartFrame>
            ) : (
              <NFEmptyState
                title="Nothing to break down"
                description="Once a bill is published you'll see what makes it up."
              />
            )}
          </NFCardBody>
        </NFCard>
      </div>

      <div className="mt-6 grid gap-5 lg:grid-cols-2">
        <UtilityCard
          title="Water"
          to="/app/water"
          icon={<Droplets />}
          trend={data?.water ?? null}
          loading={loading}
          visible={hasPermission(principal, "water.read")}
        />
        <UtilityCard
          title="Electricity"
          to="/app/electricity"
          icon={<Zap />}
          trend={data?.electricity ?? null}
          loading={loading}
          visible={hasPermission(principal, "electricity.read")}
        />
      </div>

      {(loading || (data?.recent_payments.length ?? 0) > 0) && (
        <NFCard className="mt-6">
          <NFCardHeader title="Recent payments" />
          <NFCardBody className="px-0 pb-0">
            {loading ? (
              <div className="space-y-3 px-5 pb-5">
                {[0, 1].map((i) => (
                  <NFSkeleton key={i} className="h-11" />
                ))}
              </div>
            ) : (
              <ul className="divide-y divide-[var(--nf-border)]">
                {data?.recent_payments.map((payment) => (
                  <li
                    key={payment.id}
                    className="flex items-center justify-between gap-3 px-5 py-3"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-[13px] font-medium text-[var(--nf-text)]">
                        {formatDate(payment.paid_on)} · {payment.method}
                      </p>
                      <p className="truncate text-[12px] text-[var(--nf-text-muted)]">
                        {payment.bill_number ?? payment.reference ?? "Payment"}
                      </p>
                    </div>
                    <span className="shrink-0 tabular-nums text-[13px] font-semibold text-[var(--nf-success)]">
                      {formatCurrency(payment.amount)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </NFCardBody>
        </NFCard>
      )}
    </>
  );
}

/** A utility's own card: the headline number first, the chart underneath. */
function UtilityCard({
  title,
  to,
  icon,
  trend,
  loading,
  visible,
}: {
  title: string;
  to: string;
  icon: React.ReactNode;
  trend: ConsumptionTrend | null;
  loading: boolean;
  visible: boolean;
}) {
  if (!visible) return null;

  const change = trend?.change_pct == null ? null : Number(trend.change_pct);
  const points = (trend?.points ?? []).map((p) => ({ label: p.label, value: num(p.consumption) }));

  return (
    <NFCard>
      <NFCardHeader
        title={
          <span className="inline-flex items-center gap-2 [&_svg]:size-4 [&_svg]:text-[var(--nf-primary)]">
            {icon} {title}
          </span>
        }
        description={trend ? `Last 12 readings, in ${trend.unit}` : undefined}
        action={
          <NFButton variant="ghost" size="sm" asChild>
            <Link to={to}>Details</Link>
          </NFButton>
        }
      />
      <NFCardBody>
        {loading ? (
          <NFSkeleton className="h-[190px]" />
        ) : !trend || points.length === 0 ? (
          <NFEmptyState
            title="No readings yet"
            description={`Your ${title.toLowerCase()} consumption will appear here once your meter has been read.`}
          />
        ) : (
          <>
            <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="text-[26px] font-semibold leading-none tabular-nums text-[var(--nf-text)]">
                {num(trend.latest).toLocaleString()}
              </span>
              <span className="text-[13px] text-[var(--nf-text-muted)]">{trend.unit}</span>
              {change != null && (
                <span
                  className={
                    change > 0
                      ? "inline-flex items-center gap-1 text-[12px] font-medium text-[var(--nf-warning)]"
                      : "inline-flex items-center gap-1 text-[12px] font-medium text-[var(--nf-success)]"
                  }
                >
                  {change > 0 ? (
                    <TrendingUp className="size-3.5" aria-hidden />
                  ) : (
                    <TrendingDown className="size-3.5" aria-hidden />
                  )}
                  {change > 0 ? "+" : ""}
                  {change}% on last period
                </span>
              )}
            </div>
            <ChartFrame height={170}>
              <ConsumptionAreaChart data={points} unit={trend.unit} height={170} />
            </ChartFrame>
          </>
        )}
      </NFCardBody>
    </NFCard>
  );
}
