/**
 * Reports.
 *
 * One screen for every report, because a report *is* data: the server sends
 * `columns` with a type per column and `rows` keyed to match, and this page
 * renders whatever it is given. Adding a report to the backend puts it in this
 * list without a frontend release.
 *
 * The catalogue is filtered server-side by what the caller may actually run, so
 * this page never shows a tab that would 403 — and a report it does not offer
 * returns 404 rather than 403, which is why there is no permission check here
 * at all.
 *
 * The CSV button downloads through `fetch`, not a plain `<a href>`: the export
 * needs the Authorization header, and an anchor cannot carry one.
 */

import { AlertTriangle, Download, FileSpreadsheet } from "lucide-react";
import * as React from "react";

import { NFDataTable, type Column } from "@/components/nestflow/data";
import {
  NFButton,
  NFCard,
  NFCardBody,
  NFCardHeader,
  NFEmptyState,
  NFField,
  NFInput,
  NFPageHeader,
  NFSkeleton,
  NFStatusBadge,
} from "@/components/nestflow/primitives";
import { getAccessToken } from "@/services/auth";
import { ApiError, api } from "@/services/api";
import type { ReportColumn, ReportMeta, ReportResult } from "@/types";
import { cn } from "@/utils/cn";
import { formatCurrency, formatDate, formatNumber } from "@/utils/format";

type Cell = string | number | null;

/** One formatter per declared column type — the server says which to use. */
function renderCell(column: ReportColumn, value: Cell): React.ReactNode {
  if (value === null || value === undefined || value === "") return "—";
  switch (column.type) {
    case "money":
      return formatCurrency(value as string);
    case "number":
      return formatNumber(value as number);
    case "percent":
      return `${Number(value).toFixed(1)}%`;
    case "date":
      return formatDate(String(value));
    case "status":
      return <NFStatusBadge status={String(value)} />;
    default:
      return String(value);
  }
}

const NUMERIC = new Set(["money", "number", "percent"]);

/** Turn a summary key into a label without a translation table per report. */
const humanise = (key: string) =>
  key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

function summaryValue(key: string, value: string | number | null): string {
  if (value === null) return "—";
  if (/rate|percent/.test(key)) return `${Number(value).toFixed(1)}%`;
  if (/billed|collected|outstanding|revenue|spend|cost/.test(key))
    return formatCurrency(value as string);
  if (/^(from|to)$/.test(key)) return formatDate(String(value));
  if (typeof value === "number") return formatNumber(value);
  return String(value);
}

export default function ReportsPage() {
  const [catalogue, setCatalogue] = React.useState<ReportMeta[]>([]);
  const [active, setActive] = React.useState<string | null>(null);
  const [fromDate, setFromDate] = React.useState("");
  const [toDate, setToDate] = React.useState("");
  const [report, setReport] = React.useState<ReportResult | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [exporting, setExporting] = React.useState(false);

  React.useEffect(() => {
    const controller = new AbortController();
    api
      .get<ReportMeta[]>("/reports", undefined, controller.signal)
      .then((rows) => {
        setCatalogue(rows);
        setActive((current) => current ?? rows[0]?.key ?? null);
      })
      .catch(() => undefined)
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  React.useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api
      .get<ReportResult>(
        `/reports/${active}`,
        { from_date: fromDate || undefined, to_date: toDate || undefined },
        controller.signal,
      )
      .then(setReport)
      .catch((e) => {
        if (e instanceof ApiError) setError(e.message);
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [active, fromDate, toDate]);

  const meta = catalogue.find((r) => r.key === active) ?? null;

  async function exportCsv() {
    if (!active) return;
    setExporting(true);
    try {
      const base = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";
      const query = new URLSearchParams();
      if (fromDate) query.set("from_date", fromDate);
      if (toDate) query.set("to_date", toDate);

      const token = await getAccessToken();
      const response = await fetch(
        `${base}/reports/${active}/export${query.size ? `?${query}` : ""}`,
        { headers: token ? { Authorization: `Bearer ${token}` } : {} },
      );
      if (!response.ok) throw new Error("export failed");

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${active}-${report?.generated_at ?? "export"}.csv`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch {
      setError("The export could not be downloaded.");
    } finally {
      setExporting(false);
    }
  }

  const columns: Column<Record<string, Cell>>[] = (report?.columns ?? []).map((c) => ({
    key: c.key,
    header: c.label,
    className: NUMERIC.has(c.type) ? "text-right tabular-nums" : undefined,
    headerClassName: NUMERIC.has(c.type) ? "text-right" : undefined,
    render: (row) => renderCell(c, row[c.key] ?? null),
  }));

  if (catalogue.length === 0 && !loading) {
    return (
      <>
        <NFPageHeader title="Reports" />
        <NFEmptyState
          icon={<FileSpreadsheet />}
          title="No reports available"
          description="Your account cannot run any of the society's reports."
        />
      </>
    );
  }

  return (
    <>
      <NFPageHeader
        title="Reports"
        description={meta?.description ?? "Collection, complaints, occupancy and the rest."}
        actions={
          <NFButton
            variant="secondary"
            onClick={exportCsv}
            loading={exporting}
            disabled={!report || report.row_count === 0}
          >
            <Download /> Export CSV
          </NFButton>
        }
      />

      {/* The catalogue is server-filtered, so every tab here is one this
          account can actually open. */}
      <div className="nf-scroll mb-5 flex gap-1.5 overflow-x-auto pb-1">
        {catalogue.map((r) => (
          <button
            key={r.key}
            type="button"
            onClick={() => setActive(r.key)}
            aria-pressed={active === r.key}
            className={cn(
              "shrink-0 rounded-full border px-3.5 py-1.5 text-[13px] font-medium transition-colors",
              active === r.key
                ? "border-[var(--nf-primary)] bg-[var(--nf-primary-subtle)] text-[var(--nf-primary)]"
                : "border-[var(--nf-border)] text-[var(--nf-text-muted)] hover:border-[var(--nf-border-strong)]",
            )}
          >
            {r.title}
          </button>
        ))}
      </div>

      {meta?.accepts_dates && (
        <div className="mb-5 flex flex-wrap items-end gap-3">
          <NFField label="From" htmlFor="r-from" className="w-40">
            <NFInput
              id="r-from"
              type="date"
              value={fromDate}
              onChange={(e) => setFromDate(e.target.value)}
            />
          </NFField>
          <NFField label="To" htmlFor="r-to" className="w-40">
            <NFInput
              id="r-to"
              type="date"
              value={toDate}
              onChange={(e) => setToDate(e.target.value)}
            />
          </NFField>
          {(fromDate || toDate) && (
            <NFButton
              variant="ghost"
              size="sm"
              onClick={() => {
                setFromDate("");
                setToDate("");
              }}
            >
              Clear
            </NFButton>
          )}
        </div>
      )}

      {error && (
        <p
          role="alert"
          className="mb-5 rounded-[var(--nf-radius-sm)] border border-[var(--nf-danger)]/30 bg-[var(--nf-danger-subtle)] px-3 py-2 text-[13px] text-[var(--nf-danger)]"
        >
          {error}
        </p>
      )}

      {report && Object.keys(report.summary).length > 0 && (
        <div className="mb-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Object.entries(report.summary).map(([key, value]) => (
            <NFCard key={key} className="p-4">
              <p className="text-[11px] font-medium uppercase tracking-wide text-[var(--nf-text-muted)]">
                {humanise(key)}
              </p>
              <p className="mt-1 text-xl font-semibold tracking-tight text-[var(--nf-text)]">
                {summaryValue(key, value)}
              </p>
            </NFCard>
          ))}
        </div>
      )}

      <NFCard>
        <NFCardHeader
          title={report?.title ?? "Report"}
          description={
            report
              ? `${report.row_count} row${report.row_count === 1 ? "" : "s"} · generated ${formatDate(report.generated_at)}${
                  report.period_label ? ` · ${report.period_label}` : ""
                }`
              : undefined
          }
        />
        <NFCardBody className="px-0 pb-0">
          {loading && !report ? (
            <div className="space-y-2 px-5 pb-5">
              {Array.from({ length: 5 }).map((_, i) => (
                <NFSkeleton key={i} className="h-9" />
              ))}
            </div>
          ) : (
            <>
              <NFDataTable
                caption={report?.title ?? "Report"}
                columns={columns}
                rows={(report?.rows ?? []) as Record<string, Cell>[]}
                rowKey={(row) => JSON.stringify(Object.values(row).slice(0, 3))}
                loading={loading}
                empty={
                  <div className="px-5 pb-5">
                    <NFEmptyState
                      icon={<FileSpreadsheet />}
                      title="Nothing to show"
                      description="There is no data in this range yet."
                    />
                  </div>
                }
              />

              {report && report.rows.length > 0 && Object.keys(report.totals).length > 0 && (
                <div className="nf-scroll w-full overflow-x-auto border-t border-[var(--nf-border)]">
                  <table className="w-full min-w-[560px] text-sm">
                    <tbody>
                      <tr className="bg-[var(--nf-background)]">
                        {report.columns.map((c, index) => (
                          <td
                            key={c.key}
                            className={cn(
                              "px-4 py-3 font-semibold text-[var(--nf-text)]",
                              NUMERIC.has(c.type) && "text-right tabular-nums",
                            )}
                          >
                            {index === 0
                              ? "Total"
                              : c.total
                                ? renderCell(c, report.totals[c.key] ?? null)
                                : ""}
                          </td>
                        ))}
                      </tr>
                    </tbody>
                  </table>
                </div>
              )}

              {report?.truncated && (
                <p className="flex items-center gap-2 border-t border-[var(--nf-border)] px-5 py-3 text-[13px] text-[var(--nf-warning)]">
                  <AlertTriangle className="size-3.5 shrink-0" aria-hidden />
                  Only the first {report.row_count} rows are shown. Narrow the date range
                  for the full picture.
                </p>
              )}
            </>
          )}
        </NFCardBody>
      </NFCard>
    </>
  );
}
