/**
 * A bill, and how it was calculated.
 *
 * The breakdown is rendered entirely from the stored snapshot — the formula,
 * the inputs and the trace as they were when the bill was generated. Nothing
 * is recomputed, so a bill from three years ago explains itself with the
 * numbers it was actually built from, even if rates and meter readings have
 * changed since.
 */

import { Calculator, FileText, Receipt } from "lucide-react";
import * as React from "react";

import { NFDialog } from "@/components/nestflow/data";
import {
  NFButton,
  NFSkeleton,
  NFStatusBadge,
} from "@/components/nestflow/primitives";
import { api } from "@/services/api";
import type { BillCalculation, BillDetail } from "@/types";
import { cn } from "@/utils/cn";
import { formatCurrency, formatDate, formatNumber } from "@/utils/format";

type Tab = "bill" | "calculation";

/** Field keys are snake_case on the wire; residents should not read that. */
const FIELD_LABELS: Record<string, string> = {
  flat_area: "Flat area",
  carpet_area: "Carpet area",
  base_maintenance: "Base maintenance",
  water_consumption: "Water consumed",
  water_previous: "Water — previous reading",
  water_current: "Water — current reading",
  electricity_units: "Electricity consumed",
  electricity_amount: "Electricity amount",
  parking_slot_count: "Parking slots",
  parking_charge_total: "Parking charges",
  vehicle_count: "Vehicles",
  two_wheeler_count: "Two-wheelers",
  four_wheeler_count: "Four-wheelers",
  pet_count: "Pets",
  pet_fee_total: "Pet fees",
  resident_count: "Residents",
  outstanding_balance: "Previous outstanding",
  days_overdue: "Days overdue",
  period_months: "Months in period",
  floor_number: "Floor",
  flat_type: "Flat type",
  occupancy_status: "Occupancy",
  is_vacant: "Vacant",
  is_rented: "Rented",
};

function humanise(key: string): string {
  if (FIELD_LABELS[key]) return FIELD_LABELS[key];
  if (key.startsWith("custom.")) return key.slice(7).replace(/_/g, " ");
  return key.replace(/_/g, " ");
}

export function BillDetailDialog({
  billId,
  onClose,
}: {
  billId: string | null;
  onClose: () => void;
}) {
  const [bill, setBill] = React.useState<BillDetail | null>(null);
  const [calculation, setCalculation] = React.useState<BillCalculation | null>(null);
  const [tab, setTab] = React.useState<Tab>("bill");
  const [loading, setLoading] = React.useState(false);

  React.useEffect(() => {
    if (!billId) {
      setBill(null);
      setCalculation(null);
      return;
    }
    setTab("bill");
    setLoading(true);
    api
      .get<BillDetail>(`/billing/bills/${billId}`)
      .then(setBill)
      .catch(() => setBill(null))
      .finally(() => setLoading(false));
  }, [billId]);

  React.useEffect(() => {
    if (tab !== "calculation" || !billId || calculation) return;
    api
      .get<BillCalculation>(`/billing/bills/${billId}/calculation`)
      .then(setCalculation)
      .catch(() => setCalculation(null));
  }, [tab, billId, calculation]);

  return (
    <NFDialog
      open={billId !== null}
      onOpenChange={(o) => !o && onClose()}
      title={bill ? `Flat ${bill.flat_number}` : "Bill"}
      description={bill ? `${bill.bill_number} · ${bill.period_label}` : undefined}
      size="lg"
      footer={
        <NFButton variant="secondary" onClick={onClose}>
          Close
        </NFButton>
      }
    >
      {loading || !bill ? (
        <div className="space-y-3">
          <NFSkeleton className="h-8" />
          <NFSkeleton className="h-40" />
        </div>
      ) : (
        <div className="space-y-4">
          {/* Tabs */}
          <div
            role="tablist"
            aria-label="Bill views"
            className="flex gap-1 rounded-[var(--nf-radius-sm)] bg-[var(--nf-background)] p-1"
          >
            {(
              [
                ["bill", "Bill", <Receipt key="r" className="size-3.5" />],
                ["calculation", "How was this calculated?", <Calculator key="c" className="size-3.5" />],
              ] as const
            ).map(([value, label, icon]) => (
              <button
                key={value}
                role="tab"
                aria-selected={tab === value}
                onClick={() => setTab(value)}
                className={cn(
                  "flex flex-1 items-center justify-center gap-1.5 rounded-[var(--nf-radius-sm)] px-3 py-1.5 text-[13px] font-medium transition-colors",
                  tab === value
                    ? "bg-[var(--nf-surface)] text-[var(--nf-text)] nf-shadow-sm"
                    : "text-[var(--nf-text-muted)] hover:text-[var(--nf-text)]",
                )}
              >
                {icon}
                <span className="truncate">{label}</span>
              </button>
            ))}
          </div>

          {tab === "bill" ? (
            <BillView bill={bill} />
          ) : (
            <CalculationView calculation={calculation} />
          )}
        </div>
      )}
    </NFDialog>
  );
}

/* -------------------------------------------------------------------------- */

function BillView({ bill }: { bill: BillDetail }) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <NFStatusBadge status={bill.status} />
          {bill.status === "PUBLISHED" && <NFStatusBadge status={bill.payment_status} />}
        </div>
        <p className="text-[13px] text-[var(--nf-text-muted)]">
          Due {formatDate(bill.due_date)}
        </p>
      </div>

      {bill.failure_reason && (
        <p className="rounded-[var(--nf-radius-sm)] bg-[var(--nf-danger-subtle)] px-3 py-2 text-[13px] text-[var(--nf-danger)]">
          {bill.failure_reason}
        </p>
      )}

      <div className="overflow-hidden rounded-[var(--nf-radius)] border border-[var(--nf-border)]">
        <table className="w-full text-sm">
          <caption className="sr-only">Bill breakdown</caption>
          <tbody>
            {bill.line_items.map((li) => (
              <tr key={li.id ?? li.code} className="border-b border-[var(--nf-border)]">
                <td className="px-4 py-2.5">
                  <span className="text-[var(--nf-text)]">{li.label}</span>
                  {li.quantity && li.unit && (
                    <span className="block text-[11px] text-[var(--nf-text-muted)]">
                      {formatNumber(li.quantity)} {li.unit}
                      {li.rate ? ` × ₹${Number(li.rate)}` : ""}
                    </span>
                  )}
                </td>
                <td
                  className="px-4 py-2.5 text-right tabular-nums"
                  style={{ color: li.is_credit ? "var(--nf-success)" : undefined }}
                >
                  {li.is_credit ? "−" : ""}
                  {formatCurrency(li.amount, true)}
                </td>
              </tr>
            ))}
            <tr className="bg-[var(--nf-primary-subtle)]">
              <td className="px-4 py-3 font-semibold text-[var(--nf-text)]">Total</td>
              <td className="px-4 py-3 text-right text-base font-semibold tabular-nums text-[var(--nf-primary)]">
                {formatCurrency(bill.total, true)}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      {Number(bill.amount_paid) > 0 && (
        <dl className="space-y-1.5 rounded-[var(--nf-radius)] bg-[var(--nf-background)] p-3 text-[13px]">
          <div className="flex justify-between">
            <dt className="text-[var(--nf-text-muted)]">Paid</dt>
            <dd className="tabular-nums text-[var(--nf-success)]">
              {formatCurrency(bill.amount_paid, true)}
            </dd>
          </div>
          <div className="flex justify-between font-medium">
            <dt className="text-[var(--nf-text)]">Balance due</dt>
            <dd className="tabular-nums text-[var(--nf-text)]">
              {formatCurrency(bill.balance_due, true)}
            </dd>
          </div>
        </dl>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */

function CalculationView({ calculation }: { calculation: BillCalculation | null }) {
  if (!calculation) {
    return (
      <div className="space-y-3">
        <NFSkeleton className="h-24" />
        <NFSkeleton className="h-32" />
      </div>
    );
  }

  const inputs = Object.entries(calculation.inputs);

  return (
    <div className="space-y-5">
      <p className="flex items-start gap-2 rounded-[var(--nf-radius)] bg-[var(--nf-info-subtle)] p-3 text-[12.5px] leading-relaxed text-[var(--nf-text-muted)]">
        <FileText className="mt-0.5 size-4 shrink-0 text-[var(--nf-info)]" aria-hidden />
        <span>
          These are the exact figures used when this bill was generated. They are stored with
          the bill, so this explanation never changes — even if rates or readings do.
        </span>
      </p>

      {inputs.length > 0 && (
        <section>
          <h4 className="mb-2 text-[13px] font-semibold text-[var(--nf-text)]">
            What we measured
          </h4>
          <dl className="grid gap-x-4 gap-y-2 sm:grid-cols-2">
            {inputs.map(([key, value]) => (
              <div
                key={key}
                className="flex items-baseline justify-between gap-2 border-b border-[var(--nf-border)] pb-1.5"
              >
                <dt className="text-[13px] text-[var(--nf-text-muted)]">{humanise(key)}</dt>
                <dd className="shrink-0 text-[13px] tabular-nums text-[var(--nf-text)]">
                  {formatValue(value)}
                </dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      <section>
        <h4 className="mb-2 text-[13px] font-semibold text-[var(--nf-text)]">How it added up</h4>
        <div className="overflow-hidden rounded-[var(--nf-radius)] border border-[var(--nf-border)]">
          <table className="w-full text-[13px]">
            <tbody>
              {calculation.line_items.map((li) => (
                <tr key={li.code} className="border-b border-[var(--nf-border)]">
                  <td className="px-3 py-2">
                    <span className="text-[var(--nf-text)]">{li.label}</span>
                    {li.quantity && li.unit && (
                      <span className="block text-[11px] text-[var(--nf-text-muted)]">
                        {formatNumber(li.quantity)} {li.unit}
                        {li.rate ? ` at ₹${Number(li.rate)} each` : ""}
                      </span>
                    )}
                  </td>
                  <td
                    className="px-3 py-2 text-right tabular-nums"
                    style={{ color: li.is_credit ? "var(--nf-success)" : undefined }}
                  >
                    {li.is_credit ? "−" : ""}
                    {formatCurrency(li.amount, true)}
                  </td>
                </tr>
              ))}
              <tr className="bg-[var(--nf-primary-subtle)]">
                <td className="px-3 py-2.5 font-semibold text-[var(--nf-text)]">Total</td>
                <td className="px-3 py-2.5 text-right font-semibold tabular-nums text-[var(--nf-primary)]">
                  {formatCurrency(calculation.total, true)}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      {calculation.trace.length > 0 && (
        <details>
          <summary className="cursor-pointer text-[13px] font-medium text-[var(--nf-text-muted)]">
            Step-by-step detail ({calculation.trace.length} steps)
          </summary>
          <ol className="mt-2 space-y-1.5">
            {calculation.trace.map((t, i) => (
              <li
                key={i}
                className="flex items-baseline justify-between gap-3 rounded-[var(--nf-radius-sm)] bg-[var(--nf-background)] px-2.5 py-1.5 text-[12px]"
              >
                <span className="min-w-0 text-[var(--nf-text-muted)]">
                  <span className="font-mono text-[11px] text-[var(--nf-text-subtle)]">
                    {t.node_type}
                  </span>
                  {t.detail && <span className="ml-2">{t.detail}</span>}
                  {!t.detail && t.inputs.length > 0 && (
                    <span className="ml-2">{t.inputs.join(", ")}</span>
                  )}
                </span>
                <span className="shrink-0 tabular-nums text-[var(--nf-text)]">
                  {formatValue(t.result)}
                </span>
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  );
}

function formatValue(value: string): string {
  if (value === "True") return "Yes";
  if (value === "False") return "No";
  const n = Number(value);
  return Number.isFinite(n) && value.trim() !== "" ? formatNumber(n) : value;
}
