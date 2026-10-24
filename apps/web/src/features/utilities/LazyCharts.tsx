/**
 * Lazy handles onto the chart module.
 *
 * Importing `Charts.tsx` directly would tie Recharts to whichever route pulled
 * it, and the resident dashboard — the busiest screen in the product — would
 * then wait on a chart library before painting a single number. These wrappers
 * let a page render its figures immediately and fill the chart in after.
 */

import * as React from "react";

import { NFSkeleton } from "@/components/nestflow/primitives";

const Charts = () => import("@/features/utilities/Charts");

export const ConsumptionAreaChart = React.lazy(() =>
  Charts().then((m) => ({ default: m.ConsumptionAreaChart })),
);
export const ConsumptionBarChart = React.lazy(() =>
  Charts().then((m) => ({ default: m.ConsumptionBarChart })),
);
export const ChargeBreakdownChart = React.lazy(() =>
  Charts().then((m) => ({ default: m.ChargeBreakdownChart })),
);

/** Wraps a chart with a placeholder of the same height, so nothing jumps. */
export function ChartFrame({
  height = 200,
  children,
}: {
  height?: number;
  children: React.ReactNode;
}) {
  return (
    <React.Suspense fallback={<NFSkeleton className="w-full" />}>
      <div style={{ minHeight: height }}>{children}</div>
    </React.Suspense>
  );
}
