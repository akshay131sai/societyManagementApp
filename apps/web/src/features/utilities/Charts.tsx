/**
 * Chart primitives.
 *
 * This is the **only** module that imports Recharts. Everything that draws a
 * chart pulls it in with `React.lazy`, so the library lands in its own chunk
 * and a resident who never opens an analytics screen never downloads it.
 *
 * Colours come from CSS custom properties rather than literals, because a
 * society's palette is derived per tenant at runtime — a hard-coded hex would
 * make every chart look wrong in a society that themed itself.
 */

import * as React from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

/** Reads a CSS variable off the document so charts follow the active theme. */
function cssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

/** Re-reads theme colours when the palette or colour scheme changes. */
function useChartTheme() {
  const read = React.useCallback(
    () => ({
      primary: cssVar("--nf-primary", "#3b5bdb"),
      accent: cssVar("--nf-info", "#1c7ed6"),
      grid: cssVar("--nf-border", "#e4e6eb"),
      text: cssVar("--nf-text-muted", "#6b7280"),
      surface: cssVar("--nf-surface", "#ffffff"),
      border: cssVar("--nf-border-strong", "#cbd2d9"),
    }),
    [],
  );

  const [theme, setTheme] = React.useState(read);

  React.useEffect(() => {
    const refresh = () => setTheme(read());
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", refresh);
    // The theme provider stamps data-theme on <html>; watch it rather than
    // polling, so a toggle recolours the chart immediately.
    const observer = new MutationObserver(refresh);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme", "style"],
    });
    return () => {
      media.removeEventListener("change", refresh);
      observer.disconnect();
    };
  }, [read]);

  return theme;
}

const AXIS = { fontSize: 11, fontWeight: 500 } as const;

function tooltipStyle(theme: ReturnType<typeof useChartTheme>) {
  return {
    contentStyle: {
      background: theme.surface,
      border: `1px solid ${theme.border}`,
      borderRadius: "var(--nf-radius-sm, 6px)",
      fontSize: 12,
      color: "var(--nf-text)",
      boxShadow: "var(--nf-shadow-md, 0 4px 12px rgb(0 0 0 / 0.08))",
    },
    labelStyle: { color: "var(--nf-text)", fontWeight: 600, marginBottom: 2 },
  };
}

export interface SeriesPoint {
  label: string;
  value: number;
}

/**
 * Consumption over time. An area chart rather than a line: the filled region
 * makes "how much" legible at a glance on a phone, which is the point of the
 * card it sits in.
 */
export function ConsumptionAreaChart({
  data,
  unit,
  height = 200,
}: {
  data: SeriesPoint[];
  unit: string;
  height?: number;
}) {
  const theme = useChartTheme();
  const id = React.useId().replace(/:/g, "");

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: -18 }}>
        <defs>
          <linearGradient id={`fill-${id}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={theme.primary} stopOpacity={0.28} />
            <stop offset="100%" stopColor={theme.primary} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <XAxis
          dataKey="label"
          tick={{ ...AXIS, fill: theme.text }}
          tickLine={false}
          axisLine={{ stroke: theme.grid }}
          minTickGap={12}
        />
        <YAxis
          tick={{ ...AXIS, fill: theme.text }}
          tickLine={false}
          axisLine={false}
          width={48}
        />
        <Tooltip
          {...tooltipStyle(theme)}
          formatter={(value: unknown) => [`${value} ${unit}`, "Consumption"]}
          cursor={{ stroke: theme.border, strokeDasharray: "3 3" }}
        />
        <Area
          type="monotone"
          dataKey="value"
          stroke={theme.primary}
          strokeWidth={2}
          fill={`url(#fill-${id})`}
          dot={data.length <= 12 ? { r: 2.5, strokeWidth: 0, fill: theme.primary } : false}
          activeDot={{ r: 4 }}
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

/** Society-wide totals per reading round. */
export function ConsumptionBarChart({
  data,
  unit,
  height = 240,
}: {
  data: SeriesPoint[];
  unit: string;
  height?: number;
}) {
  const theme = useChartTheme();

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: -18 }}>
        <XAxis
          dataKey="label"
          tick={{ ...AXIS, fill: theme.text }}
          tickLine={false}
          axisLine={{ stroke: theme.grid }}
          minTickGap={12}
        />
        <YAxis tick={{ ...AXIS, fill: theme.text }} tickLine={false} axisLine={false} width={48} />
        <Tooltip
          {...tooltipStyle(theme)}
          formatter={(value: unknown) => [`${value} ${unit}`, "Total"]}
          cursor={{ fill: theme.grid, fillOpacity: 0.35 }}
        />
        <Bar dataKey="value" fill={theme.primary} radius={[4, 4, 0, 0]} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  );
}

/**
 * Where a bill's money goes.
 *
 * Slices are coloured by rotating the theme's own hue rather than from a fixed
 * palette, so the chart belongs to whichever society is looking at it.
 */
export function ChargeBreakdownChart({
  data,
  height = 220,
  formatValue,
}: {
  data: { label: string; value: number }[];
  height?: number;
  formatValue?: (value: number) => string;
}) {
  const theme = useChartTheme();
  const colors = React.useMemo(
    () =>
      data.map(
        (_, i) => `color-mix(in oklab, ${theme.primary} ${Math.max(28, 100 - i * 16)}%, ${theme.surface})`,
      ),
    [data, theme.primary, theme.surface],
  );

  return (
    <ResponsiveContainer width="100%" height={height}>
      <PieChart>
        <Pie
          data={data}
          dataKey="value"
          nameKey="label"
          innerRadius="52%"
          outerRadius="80%"
          paddingAngle={1.5}
          stroke={theme.surface}
          strokeWidth={2}
          isAnimationActive={false}
        >
          {data.map((entry, i) => (
            <Cell key={entry.label} fill={colors[i]} />
          ))}
        </Pie>
        <Tooltip
          {...tooltipStyle(theme)}
          formatter={(value: unknown) => [
            formatValue ? formatValue(Number(value)) : String(value),
            "",
          ]}
        />
        <Legend
          verticalAlign="bottom"
          height={36}
          iconType="circle"
          iconSize={8}
          formatter={(value: string) => (
            <span style={{ color: theme.text, fontSize: 12 }}>{value}</span>
          )}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}
