/**
 * Water and electricity.
 *
 * One component serves both: the screens are identical apart from the unit,
 * the endpoint and whether a pass-through amount is collected. Two copies
 * would drift.
 *
 * What a resident sees and what an admin sees differ by permission, not by
 * route — the backend already scopes the data, so the page simply offers fewer
 * controls when the reader cannot record.
 */

import { CalendarDays, Droplets, Gauge, Plus, TrendingDown, TrendingUp, Zap } from "lucide-react";
import * as React from "react";

import { NFDataTable, NFDialog, NFPagination, NFStatCard, type Column } from "@/components/nestflow/data";
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
  NFSkeleton,
} from "@/components/nestflow/primitives";
import {
  ChartFrame,
  ConsumptionAreaChart,
  ConsumptionBarChart,
} from "@/features/utilities/LazyCharts";
import { ApiError, api, type Page } from "@/services/api";
import { useAppSelector } from "@/store";
import type {
  ConsumptionTrend,
  Flat,
  PendingFlat,
  SocietyConsumptionPoint,
  Utility,
  UtilityReading,
} from "@/types";
import { formatCurrency, formatDate } from "@/utils/format";
import { hasPermission } from "@/utils/permissions";

const CONFIG: Record<
  Utility,
  { title: string; unit: string; icon: React.ReactNode; readPerm: string; managePerm: string; hasAmount: boolean }
> = {
  water: {
    title: "Water",
    unit: "kL",
    icon: <Droplets />,
    readPerm: "water.read",
    managePerm: "water.manage",
    hasAmount: false,
  },
  electricity: {
    title: "Electricity",
    unit: "kWh",
    icon: <Zap />,
    readPerm: "electricity.read",
    managePerm: "electricity.manage",
    hasAmount: true,
  },
};

const LIMIT = 15;

function num(value: string | null | undefined): number {
  return value == null ? 0 : Number(value);
}

export default function UtilityPage({ utility }: { utility: Utility }) {
  const config = CONFIG[utility];
  const principal = useAppSelector((s) => s.auth.principal);
  const canManage = hasPermission(principal, config.managePerm);

  const [page, setPage] = React.useState(1);
  const [flatId, setFlatId] = React.useState<string>(principal?.flat_ids[0] ?? "");
  const [readings, setReadings] = React.useState<Page<UtilityReading> | null>(null);
  const [trend, setTrend] = React.useState<ConsumptionTrend | null>(null);
  const [society, setSociety] = React.useState<SocietyConsumptionPoint[]>([]);
  const [flats, setFlats] = React.useState<Flat[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [entryOpen, setEntryOpen] = React.useState(false);
  const [reload, setReload] = React.useState(0);

  // Flats to choose from. A resident gets only their own back, so the same
  // request serves both audiences.
  React.useEffect(() => {
    if (!hasPermission(principal, "flat.read")) return;
    const controller = new AbortController();
    api
      .get<Page<Flat>>("/flats", { limit: 100 }, controller.signal)
      .then((result) => {
        setFlats(result.items);
        setFlatId((current) => current || result.items[0]?.id || "");
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [principal]);

  React.useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    api
      .get<Page<UtilityReading>>(
        `/${utility}/readings`,
        { page, limit: LIMIT, flat_id: flatId || undefined },
        controller.signal,
      )
      .then(setReadings)
      .catch(() => undefined)
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [utility, page, flatId, reload]);

  React.useEffect(() => {
    if (!flatId) {
      setTrend(null);
      return;
    }
    const controller = new AbortController();
    api
      .get<ConsumptionTrend>(`/${utility}/trend/${flatId}`, { months: 12 }, controller.signal)
      .then(setTrend)
      .catch(() => setTrend(null));
    return () => controller.abort();
  }, [utility, flatId, reload]);

  React.useEffect(() => {
    if (!canManage) return;
    const controller = new AbortController();
    api
      .get<SocietyConsumptionPoint[]>(`/${utility}/society-trend`, { months: 12 }, controller.signal)
      .then(setSociety)
      .catch(() => undefined);
    return () => controller.abort();
  }, [utility, canManage, reload]);

  const columns: Column<UtilityReading>[] = [
    {
      key: "date",
      header: "Read on",
      render: (r) => (
        <span className="whitespace-nowrap font-medium text-[var(--nf-text)]">
          {formatDate(r.reading_date)}
        </span>
      ),
    },
    {
      key: "flat",
      header: "Flat",
      hideOnMobile: true,
      render: (r) => r.flat_number ?? "—",
    },
    {
      key: "previous",
      header: "Previous",
      hideOnMobile: true,
      className: "text-right tabular-nums",
      headerClassName: "text-right",
      render: (r) => (r.previous_reading == null ? "—" : num(r.previous_reading).toLocaleString()),
    },
    {
      key: "current",
      header: "Current",
      className: "text-right tabular-nums",
      headerClassName: "text-right",
      render: (r) => num(r.current_reading).toLocaleString(),
    },
    {
      key: "consumption",
      header: `Used (${config.unit})`,
      className: "text-right tabular-nums font-semibold",
      headerClassName: "text-right",
      render: (r) => num(r.consumption).toLocaleString(),
    },
    ...(config.hasAmount
      ? [
          {
            key: "amount",
            header: "Amount",
            hideOnMobile: true,
            className: "text-right tabular-nums",
            headerClassName: "text-right",
            render: (r: UtilityReading) => (r.amount == null ? "—" : formatCurrency(r.amount)),
          },
        ]
      : []),
  ];

  const change = trend?.change_pct == null ? null : Number(trend.change_pct);
  const points = (trend?.points ?? []).map((p) => ({ label: p.label, value: num(p.consumption) }));

  /* A manager runs the society, so their headline is the society: every flat's
     consumption added up per reading round. A resident's headline is their own
     meter. Both then get the other view as the secondary card — the admin can
     still drill into one flat, and the totals are derived from the same
     `society-trend` series the chart already used. */
  const societyPoints = society.map((p) => ({ label: p.label, value: num(p.total) }));
  const societyLatest = societyPoints.at(-1)?.value ?? null;
  const societyPrevious = societyPoints.at(-2)?.value ?? null;
  const societyChange =
    societyLatest == null || societyPrevious == null || societyPrevious === 0
      ? null
      : Math.round(((societyLatest - societyPrevious) / societyPrevious) * 1000) / 10;
  const societyTotal = societyPoints.reduce((sum, p) => sum + p.value, 0);
  const societyAverage = societyPoints.length
    ? Math.round(societyTotal / societyPoints.length)
    : null;
  const societyPeak = societyPoints.length
    ? Math.max(...societyPoints.map((p) => p.value))
    : null;

  const headline = canManage
    ? {
        label: "Society total, latest round",
        value:
          societyLatest == null ? "—" : `${societyLatest.toLocaleString()} ${config.unit}`,
        hint: societyPoints.at(-1)?.label,
        change: societyChange,
        changeHint:
          societyPrevious == null
            ? "No earlier round yet"
            : `was ${societyPrevious.toLocaleString()} ${config.unit}`,
        average:
          societyAverage == null ? "—" : `${societyAverage.toLocaleString()} ${config.unit}`,
        averageHint: societyPoints.length
          ? `across ${societyPoints.length} reading round(s)`
          : undefined,
        peak: societyPeak == null ? "—" : `${societyPeak.toLocaleString()} ${config.unit}`,
        pending: !society.length,
      }
    : {
        label: "Latest reading",
        value: trend?.latest == null ? "—" : `${num(trend.latest).toLocaleString()} ${config.unit}`,
        hint: trend?.points.at(-1)?.label,
        change,
        changeHint:
          trend?.previous == null
            ? "No earlier reading yet"
            : `was ${num(trend.previous).toLocaleString()} ${config.unit}`,
        average: trend ? `${num(trend.stats.average).toLocaleString()} ${config.unit}` : "—",
        averageHint: trend ? `over ${trend.stats.readings} reading(s)` : undefined,
        peak: trend ? `${num(trend.stats.highest).toLocaleString()} ${config.unit}` : "—",
        pending: !trend,
      };

  return (
    <>
      <NFPageHeader
        title={config.title}
        description={
          canManage
            ? "Meter readings, consumption trends and the flats still awaiting a reading."
            : "Your meter readings and how your consumption is trending."
        }
        actions={
          canManage ? (
            <NFButton onClick={() => setEntryOpen(true)}>
              <Plus /> Record readings
            </NFButton>
          ) : undefined
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <NFStatCard
          label={headline.label}
          value={headline.value}
          hint={headline.hint}
          icon={config.icon}
          loading={loading && headline.pending}
        />
        <NFStatCard
          label="Change on last period"
          value={
            headline.change == null
              ? "—"
              : `${headline.change > 0 ? "+" : ""}${headline.change}%`
          }
          hint={headline.changeHint}
          icon={headline.change != null && headline.change > 0 ? <TrendingUp /> : <TrendingDown />}
          tone={headline.change == null ? "info" : headline.change > 0 ? "warning" : "success"}
          loading={loading && headline.pending}
        />
        <NFStatCard
          label="Average per period"
          value={headline.average}
          hint={headline.averageHint}
          icon={<Gauge />}
          tone="info"
          loading={loading && headline.pending}
        />
        <NFStatCard
          label="Highest recorded"
          value={headline.peak}
          icon={<CalendarDays />}
          tone="primary"
          loading={loading && headline.pending}
        />
      </div>

      <div className="mt-6 grid gap-5 lg:grid-cols-3">
        {canManage && (
          <NFCard className="lg:col-span-2">
            <NFCardHeader
              title="Society total"
              description={`Every flat added up, per reading round, in ${config.unit}.`}
            />
            <NFCardBody>
              {societyPoints.length === 0 ? (
                <NFEmptyState
                  title="No readings yet"
                  description="Record a round of meter readings and the society total will appear here."
                />
              ) : (
                <ChartFrame height={220}>
                  <ConsumptionBarChart
                    data={societyPoints}
                    unit={config.unit}
                    height={220}
                  />
                </ChartFrame>
              )}
            </NFCardBody>
          </NFCard>
        )}

        <NFCard className={canManage ? "" : "lg:col-span-3"}>
          <NFCardHeader
            title={canManage ? "One flat" : "Consumption trend"}
            description={
              canManage
                ? "Drill into a single meter."
                : flats.length > 1
                  ? "Choose a flat to see its meter history."
                  : "Your meter history."
            }
            action={
              flats.length > 1 ? (
                <NFSelect
                  aria-label="Flat"
                  value={flatId}
                  onChange={(e) => {
                    setFlatId(e.target.value);
                    setPage(1);
                  }}
                  className="w-40"
                >
                  {flats.map((flat) => (
                    <option key={flat.id} value={flat.id}>
                      {flat.flat_number}
                    </option>
                  ))}
                </NFSelect>
              ) : undefined
            }
          />
          <NFCardBody>
            {points.length === 0 ? (
              <NFEmptyState
                title="No readings yet"
                description={
                  canManage
                    ? "Record a round of meter readings and the trend will appear here."
                    : "Once your meter has been read, your consumption will appear here."
                }
              />
            ) : (
              <ChartFrame height={220}>
                <ConsumptionAreaChart data={points} unit={config.unit} height={220} />
              </ChartFrame>
            )}
          </NFCardBody>
        </NFCard>

      </div>

      <NFCard className="mt-6">
        <NFCardHeader title="Readings" description="Newest first." />
        <NFCardBody className="px-0 pb-0">
          <NFDataTable
            caption={`${config.title} readings`}
            columns={columns}
            rows={readings?.items ?? []}
            rowKey={(r) => r.id}
            loading={loading}
            empty={
              <div className="px-5 pb-5">
                <NFEmptyState
                  title="No readings recorded"
                  description="Nothing has been read for this selection yet."
                />
              </div>
            }
          />
          {readings && readings.total > 0 && (
            <div className="px-5 py-4">
              <NFPagination
                page={readings.page}
                pages={readings.pages}
                total={readings.total}
                limit={readings.limit}
                onPageChange={setPage}
              />
            </div>
          )}
        </NFCardBody>
      </NFCard>

      {canManage && (
        <BulkEntryDialog
          open={entryOpen}
          onOpenChange={setEntryOpen}
          utility={utility}
          onSaved={() => {
            setEntryOpen(false);
            setReload((n) => n + 1);
          }}
        />
      )}
    </>
  );
}

/* -------------------------------------------------------------------------- */
/* Bulk entry                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * A meter reader walks the building once and enters one number per flat, so
 * the form is one date and a column of readings — not a flat picker repeated
 * fifty times. The opening value is prefilled from the last round.
 */
function BulkEntryDialog({
  open,
  onOpenChange,
  utility,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  utility: Utility;
  onSaved: () => void;
}) {
  const config = CONFIG[utility];
  const [pending, setPending] = React.useState<PendingFlat[]>([]);
  const [values, setValues] = React.useState<Record<string, string>>({});
  const [readingDate, setReadingDate] = React.useState(() => new Date().toISOString().slice(0, 10));
  const [loading, setLoading] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    setLoading(true);
    setError(null);
    api
      .get<PendingFlat[]>(`/${utility}/pending`)
      .then((rows) => {
        setPending(rows);
        setValues({});
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not load flats."))
      .finally(() => setLoading(false));
  }, [open, utility]);

  const rows = pending
    .filter((flat) => values[flat.flat_id]?.trim())
    .map((flat) => ({
      flat_id: flat.flat_id,
      current_reading: values[flat.flat_id].trim(),
    }));

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      await api.post(`/${utility}/readings/bulk`, { reading_date: readingDate, rows });
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save these readings.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <NFDialog
      open={open}
      onOpenChange={onOpenChange}
      title={`Record ${config.title.toLowerCase()} readings`}
      description="Enter the closing reading for each flat. Blank rows are skipped."
      size="lg"
      footer={
        <div className="flex w-full flex-wrap items-center justify-between gap-3">
          <p className="text-[13px] text-[var(--nf-text-muted)]">
            {rows.length} of {pending.length} flat(s) filled in
          </p>
          <div className="flex gap-2">
            <NFButton variant="secondary" onClick={() => onOpenChange(false)}>
              Cancel
            </NFButton>
            <NFButton onClick={submit} loading={saving} disabled={rows.length === 0}>
              Save {rows.length > 0 ? `${rows.length} reading(s)` : ""}
            </NFButton>
          </div>
        </div>
      }
    >
      <NFField label="Reading date" htmlFor="reading-date">
        <NFInput
          id="reading-date"
          type="date"
          value={readingDate}
          max={new Date().toISOString().slice(0, 10)}
          onChange={(e) => setReadingDate(e.target.value)}
        />
      </NFField>

      {error && (
        <p
          role="alert"
          className="mt-3 rounded-[var(--nf-radius-sm)] border border-[var(--nf-danger)]/30 bg-[var(--nf-danger-subtle)] px-3 py-2 text-[13px] text-[var(--nf-danger)]"
        >
          {error}
        </p>
      )}

      <div className="mt-4 max-h-[45vh] overflow-y-auto nf-scroll rounded-[var(--nf-radius-sm)] border border-[var(--nf-border)]">
        {loading ? (
          <div className="space-y-2 p-3">
            {[0, 1, 2, 3, 4].map((i) => (
              <NFSkeleton key={i} className="h-10" />
            ))}
          </div>
        ) : pending.length === 0 ? (
          <div className="p-5">
            <NFEmptyState title="No flats yet" description="Add flats before recording readings." />
          </div>
        ) : (
          <ul className="divide-y divide-[var(--nf-border)]">
            {pending.map((flat) => (
              <li key={flat.flat_id} className="flex items-center gap-3 px-3 py-2">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-medium text-[var(--nf-text)]">
                    {flat.flat_number}
                  </p>
                  <p className="truncate text-[12px] text-[var(--nf-text-muted)]">
                    {flat.previous_reading == null
                      ? "No previous reading"
                      : `Last ${num(flat.previous_reading).toLocaleString()} ${config.unit} · ${formatDate(
                          flat.last_reading_date,
                        )}`}
                  </p>
                </div>
                <NFInput
                  aria-label={`Reading for ${flat.flat_number}`}
                  inputMode="decimal"
                  type="number"
                  min={flat.previous_reading ?? 0}
                  step="0.001"
                  placeholder="Reading"
                  className="w-32 text-right tabular-nums"
                  value={values[flat.flat_id] ?? ""}
                  onChange={(e) =>
                    setValues((v) => ({ ...v, [flat.flat_id]: e.target.value }))
                  }
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    </NFDialog>
  );
}
